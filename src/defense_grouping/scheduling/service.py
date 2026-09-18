from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal
from defense_grouping.db.base import as_utc, utc_now
from defense_grouping.master_data.service import check_version, require_department_scope
from defense_grouping.models.availability import (
    CourseOccupancy,
    LeaveRecord,
    LeaveStatus,
    Room,
    RoomAvailability,
)
from defense_grouping.models.defense import (
    ActivityRoom,
    ActivityRuleSet,
    ConfirmationStatus,
    DefenseActivity,
    DefenseGroup,
    DefenseSlot,
    JobStatus,
    PanelAssignment,
    PlanStatus,
    ScheduleJob,
    SchedulePlan,
    StudentAssignment,
    TeacherConfirmation,
)
from defense_grouping.models.governance import ApprovalStatus, AuditLog, ConstraintException
from defense_grouping.models.master import (
    Student,
    StudentDirection,
    Teacher,
    TeacherDirection,
)
from defense_grouping.scheduling.domain import (
    ApprovedException,
    AvailabilityConflict,
    GroupSolution,
    RoomSupply,
    ScheduleSolution,
    SchedulingInput,
    SchedulingRules,
    SlotSupply,
    StudentDemand,
    TeacherSupply,
)
from defense_grouping.scheduling.schemas import (
    ConfirmationRead,
    GroupAdjustment,
    GroupRead,
    PlanComparison,
    PlanRead,
    ScheduleJobCreate,
    ScheduleJobRead,
    TeacherScheduleItem,
)
from defense_grouping.scheduling.solver import SolveOutcome
from defense_grouping.scheduling.validator import validate_solution

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _integer_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    return default


def _numeric_value(value: object) -> float:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return float(value)
    return 0


def job_read(job: ScheduleJob) -> ScheduleJobRead:
    return ScheduleJobRead(
        id=job.id,
        activity_id=job.activity_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        random_seed=job.random_seed,
        plan_id=job.result_plan_id,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def get_activity_scoped(
    session: AsyncSession,
    principal: Principal,
    activity_id: UUID,
) -> DefenseActivity:
    activity = await session.get(DefenseActivity, activity_id)
    if activity is None:
        raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
    require_department_scope(principal, activity.department_id)
    return activity


async def get_job_scoped(
    session: AsyncSession,
    principal: Principal,
    job_id: UUID,
) -> ScheduleJob:
    job = await session.get(ScheduleJob, job_id)
    if job is None:
        raise APIError(status_code=404, code="schedule_job_not_found", message="排组任务不存在")
    await get_activity_scoped(session, principal, job.activity_id)
    return job


async def get_plan_scoped(
    session: AsyncSession,
    principal: Principal,
    plan_id: UUID,
) -> SchedulePlan:
    plan = await session.get(SchedulePlan, plan_id)
    if plan is None:
        raise APIError(status_code=404, code="plan_not_found", message="排组方案不存在")
    await get_activity_scoped(session, principal, plan.activity_id)
    return plan


def _slot_bounds(slot: DefenseSlot) -> tuple[datetime, datetime]:
    starts_at = datetime.combine(slot.slot_date, slot.start_time, LOCAL_TIMEZONE).astimezone(UTC)
    ends_at = datetime.combine(slot.slot_date, slot.end_time, LOCAL_TIMEZONE).astimezone(UTC)
    return starts_at, ends_at


def _overlaps(
    starts_at: datetime,
    ends_at: datetime,
    other_starts_at: datetime,
    other_ends_at: datetime,
) -> bool:
    return starts_at < other_ends_at and ends_at > other_starts_at


async def build_scheduling_input(
    session: AsyncSession,
    activity_id: UUID,
    *,
    seed: int,
) -> SchedulingInput:
    activity = await session.get(DefenseActivity, activity_id)
    if activity is None:
        raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
    rules = await session.scalar(
        select(ActivityRuleSet).where(
            ActivityRuleSet.activity_id == activity.id,
            ActivityRuleSet.rule_version == activity.current_rule_version,
        )
    )
    if rules is None:
        raise APIError(status_code=409, code="activity_rules_missing", message="答辩活动尚未配置规则")

    students = list(
        await session.scalars(
            select(Student)
            .where(
                Student.department_id == activity.department_id,
                Student.is_active.is_(True),
            )
            .order_by(Student.student_number, Student.id)
        )
    )
    teachers = list(
        await session.scalars(
            select(Teacher)
            .where(
                Teacher.department_id == activity.department_id,
                Teacher.is_active.is_(True),
            )
            .order_by(Teacher.employee_number, Teacher.id)
        )
    )
    slots = list(
        await session.scalars(
            select(DefenseSlot)
            .where(DefenseSlot.activity_id == activity.id)
            .order_by(DefenseSlot.slot_date, DefenseSlot.start_time, DefenseSlot.id)
        )
    )
    rooms = list(
        await session.scalars(
            select(Room)
            .join(ActivityRoom, ActivityRoom.room_id == Room.id)
            .where(ActivityRoom.activity_id == activity.id)
            .order_by(Room.campus, Room.building, Room.name, Room.id)
        )
    )

    student_directions: dict[UUID, set[str]] = defaultdict(set)
    if students:
        direction_rows = await session.execute(
            select(StudentDirection.student_id, StudentDirection.direction_id).where(
                StudentDirection.student_id.in_(student.id for student in students)
            )
        )
        for student_id, direction_id in direction_rows:
            student_directions[student_id].add(str(direction_id))
    teacher_directions: dict[UUID, set[str]] = defaultdict(set)
    if teachers:
        direction_rows = await session.execute(
            select(TeacherDirection.teacher_id, TeacherDirection.direction_id).where(
                TeacherDirection.teacher_id.in_(teacher.id for teacher in teachers)
            )
        )
        for teacher_id, direction_id in direction_rows:
            teacher_directions[teacher_id].add(str(direction_id))

    person_ids = [student.id for student in students] + [teacher.id for teacher in teachers]
    occupancies = list(
        await session.scalars(
            select(CourseOccupancy).where(CourseOccupancy.person_id.in_(person_ids))
        )
    ) if person_ids else []
    leaves = list(
        await session.scalars(
            select(LeaveRecord).where(
                LeaveRecord.person_id.in_(person_ids),
                LeaveRecord.status == LeaveStatus.APPROVED,
            )
        )
    ) if person_ids else []
    blocks_by_person: dict[UUID, list[tuple[str, datetime, datetime]]] = defaultdict(list)
    for occupancy in occupancies:
        blocks_by_person[occupancy.person_id].append(
            ("course_conflict", as_utc(occupancy.starts_at), as_utc(occupancy.ends_at))
        )
    for leave in leaves:
        blocks_by_person[leave.person_id].append(
            ("leave_conflict", as_utc(leave.starts_at), as_utc(leave.ends_at))
        )

    slot_bounds = {slot.id: _slot_bounds(slot) for slot in slots}
    conflicts: set[tuple[str, str, str]] = set()

    def available_slots(person_id: UUID) -> frozenset[str]:
        available: set[str] = set()
        for slot in slots:
            slot_starts, slot_ends = slot_bounds[slot.id]
            blocked = False
            for code, starts_at, ends_at in blocks_by_person[person_id]:
                if _overlaps(slot_starts, slot_ends, starts_at, ends_at):
                    conflicts.add((str(person_id), str(slot.id), code))
                    blocked = True
            if not blocked:
                available.add(str(slot.id))
        return frozenset(available)

    room_availabilities = list(
        await session.scalars(
            select(RoomAvailability).where(
                RoomAvailability.room_id.in_(room.id for room in rooms)
            )
        )
    ) if rooms else []
    availability_by_room: dict[UUID, list[RoomAvailability]] = defaultdict(list)
    for availability in room_availabilities:
        availability_by_room[availability.room_id].append(availability)

    def room_slots(room_id: UUID) -> frozenset[str]:
        configured = availability_by_room[room_id]
        if not configured:
            return frozenset(str(slot.id) for slot in slots)
        return frozenset(
            str(slot.id)
            for slot in slots
            if any(
                item.available_date == slot.slot_date
                and item.start_time <= slot.start_time
                and item.end_time >= slot.end_time
                for item in configured
            )
        )

    approved_rows = list(
        await session.scalars(
            select(ConstraintException).where(
                ConstraintException.activity_id == activity.id,
                ConstraintException.status == ApprovalStatus.APPROVED,
            )
        )
    )
    now = utc_now()
    approved_rows = [item for item in approved_rows if as_utc(item.expires_at) >= now]
    weights = rules.soft_weights
    return SchedulingInput(
        activity_id=str(activity.id),
        seed=seed,
        students=tuple(
            StudentDemand(
                id=str(student.id),
                advisor_id=str(student.advisor_id),
                direction_ids=frozenset(student_directions[student.id]),
                available_slot_ids=available_slots(student.id),
            )
            for student in students
        ),
        teachers=tuple(
            TeacherSupply(
                id=str(teacher.id),
                title_rank=teacher.title_rank,
                direction_ids=frozenset(teacher_directions[teacher.id]),
                available_slot_ids=available_slots(teacher.id),
                workload_limit=teacher.workload_limit,
            )
            for teacher in teachers
        ),
        slots=tuple(
            SlotSupply(id=str(slot.id), max_groups=slot.max_groups, sequence=index)
            for index, slot in enumerate(slots, start=1)
        ),
        rooms=tuple(
            RoomSupply(
                id=str(room.id),
                capacity=room.capacity,
                available_slot_ids=room_slots(room.id),
            )
            for room in rooms
        ),
        rules=SchedulingRules(
            students_per_group=rules.students_per_group,
            teachers_per_group=rules.teachers_per_group,
            chair_min_title_rank=rules.chair_min_title_rank,
            teacher_workload_limit=rules.teacher_workload_limit,
            balance_students_weight=int(weights.get("balance_students", 0)),
            balance_teacher_load_weight=int(weights.get("balance_teacher_load", 0)),
            direction_match_weight=int(weights.get("direction_match", 0)),
            compact_schedule_weight=int(weights.get("compact_schedule", 0)),
            exception_use_weight=int(weights.get("exception_use", 0)),
        ),
        exceptions=tuple(
            ApprovedException(
                id=str(item.id),
                constraint_code=item.constraint_code,
                teacher_id=str(item.teacher_id) if item.teacher_id else None,
                student_id=str(item.student_id) if item.student_id else None,
                person_id=str(item.person_id) if item.person_id else None,
                slot_id=str(item.slot_id) if item.slot_id else None,
            )
            for item in approved_rows
        ),
        availability_conflicts=tuple(
            AvailabilityConflict(person_id, slot_id, code)
            for person_id, slot_id, code in sorted(conflicts)
        ),
    )


async def create_schedule_job(
    session: AsyncSession,
    principal: Principal,
    activity_id: UUID,
    payload: ScheduleJobCreate,
    idempotency_key: str,
) -> tuple[ScheduleJob, SchedulingInput | None]:
    await get_activity_scoped(session, principal, activity_id)
    existing = await session.scalar(
        select(ScheduleJob).where(
            ScheduleJob.created_by_id == principal.user_id,
            ScheduleJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.activity_id != activity_id:
            raise APIError(
                status_code=409,
                code="idempotency_key_conflict",
                message="幂等键已用于其他答辩活动",
            )
        return existing, None
    data = await build_scheduling_input(session, activity_id, seed=payload.seed)
    job = ScheduleJob(
        activity_id=activity_id,
        created_by_id=principal.user_id,
        status=JobStatus.PENDING,
        stage="pending",
        progress=0,
        input_summary={
            "students": len(data.students),
            "teachers": len(data.teachers),
            "slots": len(data.slots),
            "rooms": len(data.rooms),
            "time_limit_seconds": payload.time_limit_seconds,
        },
        random_seed=payload.seed,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    await session.commit()
    return job, data


async def cancel_schedule_job(session: AsyncSession, job: ScheduleJob) -> ScheduleJob:
    if job.status == JobStatus.CANCELLED:
        return job
    if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
        raise APIError(status_code=409, code="job_already_finished", message="任务已经结束")
    job.status = JobStatus.CANCELLED
    job.stage = "cancelled"
    job.error_code = "cancelled_by_user"
    job.error_message = "任务已由用户取消"
    job.finished_at = utc_now()
    job.version += 1
    await session.commit()
    return job


def _exception_snapshot(
    data: SchedulingInput,
    used_exception_ids: frozenset[str],
) -> list[dict[str, object]]:
    return [
        {
            "id": exception.id,
            "constraint_code": exception.constraint_code,
            "teacher_id": exception.teacher_id,
            "student_id": exception.student_id,
            "person_id": exception.person_id,
            "slot_id": exception.slot_id,
        }
        for exception in data.exceptions
        if exception.id in used_exception_ids
    ]


async def persist_solve_outcome(
    session: AsyncSession,
    job_id: UUID,
    data: SchedulingInput,
    outcome: SolveOutcome,
) -> None:
    job = await session.get(ScheduleJob, job_id)
    if job is None or job.status == JobStatus.CANCELLED:
        return
    if outcome.solution is None or outcome.status not in {"feasible", "optimal"}:
        job.status = JobStatus.FAILED
        job.stage = "failed"
        job.progress = 1
        job.error_code = outcome.status
        job.error_message = "; ".join(item.message for item in outcome.diagnostics)[:2000]
        job.finished_at = utc_now()
        job.version += 1
        await session.commit()
        return

    report = validate_solution(data, outcome.solution)
    if not report.valid:
        codes = ", ".join(item.code for item in report.violations)
        raise RuntimeError(f"solver result failed persistence validation: {codes}")
    version_number = int(
        await session.scalar(
            select(func.coalesce(func.max(SchedulePlan.version_number), 0)).where(
                SchedulePlan.activity_id == job.activity_id
            )
        )
        or 0
    ) + 1
    plan = SchedulePlan(
        activity_id=job.activity_id,
        version_number=version_number,
        created_by_id=job.created_by_id,
        status=PlanStatus.READY,
        solver_parameters={
            "seed": data.seed,
            "time_limit_seconds": job.input_summary.get("time_limit_seconds", 60),
            "status": outcome.status,
            "elapsed_seconds": outcome.elapsed_seconds,
        },
        quality_metrics=dict(outcome.solution.objective_components),
        exception_snapshot=_exception_snapshot(data, report.used_exception_ids),
        validated_at=utc_now(),
    )
    session.add(plan)
    await session.flush()
    for group_solution in outcome.solution.groups:
        group = DefenseGroup(
            plan_id=plan.id,
            code=group_solution.id,
            slot_id=UUID(group_solution.slot_id),
            room_id=UUID(group_solution.room_id),
        )
        session.add(group)
        await session.flush()
        session.add_all(
            [
                StudentAssignment(
                    plan_id=plan.id,
                    group_id=group.id,
                    student_id=UUID(student_id),
                )
                for student_id in group_solution.student_ids
            ]
        )
        session.add_all(
            [
                PanelAssignment(
                    plan_id=plan.id,
                    group_id=group.id,
                    teacher_id=UUID(teacher_id),
                    is_chair=teacher_id == group_solution.chair_id,
                )
                for teacher_id in group_solution.teacher_ids
            ]
        )
    job.status = JobStatus.SUCCEEDED
    job.stage = "completed"
    job.progress = 1
    job.result_plan_id = plan.id
    job.finished_at = utc_now()
    job.error_code = None
    job.error_message = None
    job.version += 1
    await session.commit()


async def plan_solution(session: AsyncSession, plan: SchedulePlan) -> ScheduleSolution:
    groups = list(
        await session.scalars(
            select(DefenseGroup)
            .where(DefenseGroup.plan_id == plan.id)
            .order_by(DefenseGroup.code, DefenseGroup.id)
        )
    )
    students = list(
        await session.scalars(
            select(StudentAssignment).where(StudentAssignment.plan_id == plan.id)
        )
    )
    panels = list(
        await session.scalars(
            select(PanelAssignment).where(PanelAssignment.plan_id == plan.id)
        )
    )
    students_by_group: dict[UUID, list[str]] = defaultdict(list)
    teachers_by_group: dict[UUID, list[str]] = defaultdict(list)
    chairs: dict[UUID, str] = {}
    for student_assignment in students:
        students_by_group[student_assignment.group_id].append(str(student_assignment.student_id))
    for panel_assignment in panels:
        teachers_by_group[panel_assignment.group_id].append(str(panel_assignment.teacher_id))
        if panel_assignment.is_chair:
            chairs[panel_assignment.group_id] = str(panel_assignment.teacher_id)
    return ScheduleSolution(
        groups=tuple(
            GroupSolution(
                id=str(group.id),
                student_ids=tuple(sorted(students_by_group[group.id])),
                teacher_ids=tuple(sorted(teachers_by_group[group.id])),
                chair_id=chairs.get(group.id, ""),
                slot_id=str(group.slot_id),
                room_id=str(group.room_id),
            )
            for group in groups
        ),
        objective_components=tuple(
            sorted(
                (key, _integer_value(value))
                for key, value in plan.quality_metrics.items()
                if isinstance(value, int | float) and not isinstance(value, bool)
            )
        ),
    )


async def plan_read(session: AsyncSession, plan: SchedulePlan) -> PlanRead:
    solution = await plan_solution(session, plan)
    groups = {
        group.id: group
        for group in await session.scalars(
            select(DefenseGroup).where(DefenseGroup.plan_id == plan.id)
        )
    }
    solution_by_id = {UUID(item.id): item for item in solution.groups}
    return PlanRead(
        id=plan.id,
        activity_id=plan.activity_id,
        version_number=plan.version_number,
        source_plan_id=plan.source_plan_id,
        status=plan.status,
        solver_parameters=plan.solver_parameters,
        quality_metrics=plan.quality_metrics,
        exception_snapshot=plan.exception_snapshot,
        validated_at=plan.validated_at,
        published_at=plan.published_at,
        version=plan.version,
        groups=[
            GroupRead(
                id=group.id,
                code=group.code,
                slot_id=group.slot_id,
                room_id=group.room_id,
                student_ids=[UUID(item) for item in solution_by_id[group.id].student_ids],
                teacher_ids=[UUID(item) for item in solution_by_id[group.id].teacher_ids],
                chair_id=UUID(solution_by_id[group.id].chair_id),
                version=group.version,
            )
            for group in sorted(groups.values(), key=lambda item: (item.code, item.id))
        ],
    )


async def copy_plan(
    session: AsyncSession,
    source: SchedulePlan,
    principal: Principal,
) -> SchedulePlan:
    next_version = int(
        await session.scalar(
            select(func.coalesce(func.max(SchedulePlan.version_number), 0)).where(
                SchedulePlan.activity_id == source.activity_id
            )
        )
        or 0
    ) + 1
    copied = SchedulePlan(
        activity_id=source.activity_id,
        version_number=next_version,
        source_plan_id=source.id,
        created_by_id=principal.user_id,
        status=PlanStatus.DRAFT,
        solver_parameters=dict(source.solver_parameters),
        quality_metrics=dict(source.quality_metrics),
        exception_snapshot=list(source.exception_snapshot),
    )
    session.add(copied)
    await session.flush()
    source_groups = list(
        await session.scalars(
            select(DefenseGroup)
            .where(DefenseGroup.plan_id == source.id)
            .order_by(DefenseGroup.code, DefenseGroup.id)
        )
    )
    students = list(
        await session.scalars(
            select(StudentAssignment).where(StudentAssignment.plan_id == source.id)
        )
    )
    panels = list(
        await session.scalars(
            select(PanelAssignment).where(PanelAssignment.plan_id == source.id)
        )
    )
    students_by_group: dict[UUID, list[StudentAssignment]] = defaultdict(list)
    panels_by_group: dict[UUID, list[PanelAssignment]] = defaultdict(list)
    for student_assignment in students:
        students_by_group[student_assignment.group_id].append(student_assignment)
    for panel_assignment in panels:
        panels_by_group[panel_assignment.group_id].append(panel_assignment)
    for source_group in source_groups:
        group = DefenseGroup(
            plan_id=copied.id,
            code=source_group.code,
            slot_id=source_group.slot_id,
            room_id=source_group.room_id,
        )
        session.add(group)
        await session.flush()
        session.add_all(
            [
                StudentAssignment(
                    plan_id=copied.id,
                    group_id=group.id,
                    student_id=item.student_id,
                )
                for item in students_by_group[source_group.id]
            ]
        )
        session.add_all(
            [
                PanelAssignment(
                    plan_id=copied.id,
                    group_id=group.id,
                    teacher_id=item.teacher_id,
                    is_chair=item.is_chair,
                )
                for item in panels_by_group[source_group.id]
            ]
        )
    await session.commit()
    return copied


def _validation_error(report_codes: list[str]) -> APIError:
    return APIError(
        status_code=409,
        code="plan_validation_failed",
        message="方案存在未批准的硬约束冲突",
        fields={f"violations.{index}": code for index, code in enumerate(report_codes)},
    )


async def adjust_group(
    session: AsyncSession,
    plan: SchedulePlan,
    group_id: UUID,
    payload: GroupAdjustment,
) -> SchedulePlan:
    if plan.status == PlanStatus.PUBLISHED:
        raise APIError(
            status_code=409,
            code="published_plan_immutable",
            message="已发布方案不可原地修改，请先复制为新草稿",
        )
    if plan.status != PlanStatus.DRAFT:
        raise APIError(status_code=409, code="plan_not_editable", message="只有草稿方案可调整")
    check_version(plan.version, payload.version)
    group = await session.get(DefenseGroup, group_id)
    if group is None or group.plan_id != plan.id:
        raise APIError(status_code=404, code="group_not_found", message="答辩组不存在")
    if payload.slot_id is not None:
        group.slot_id = payload.slot_id
    if payload.room_id is not None:
        group.room_id = payload.room_id
    if payload.student_ids is not None:
        await session.execute(
            delete(StudentAssignment).where(StudentAssignment.group_id == group.id)
        )
        session.add_all(
            [
                StudentAssignment(plan_id=plan.id, group_id=group.id, student_id=student_id)
                for student_id in payload.student_ids
            ]
        )
    if payload.teacher_ids is not None:
        await session.execute(
            delete(PanelAssignment).where(PanelAssignment.group_id == group.id)
        )
        chair_id = payload.chair_id
        if chair_id is None:
            raise APIError(
                status_code=422,
                code="chair_required",
                message="修改答辩组教师时必须指定组长",
            )
        session.add_all(
            [
                PanelAssignment(
                    plan_id=plan.id,
                    group_id=group.id,
                    teacher_id=teacher_id,
                    is_chair=teacher_id == chair_id,
                )
                for teacher_id in payload.teacher_ids
            ]
        )
    elif payload.chair_id is not None:
        assignments = list(
            await session.scalars(
                select(PanelAssignment).where(PanelAssignment.group_id == group.id)
            )
        )
        for assignment in assignments:
            assignment.is_chair = assignment.teacher_id == payload.chair_id
    group.version += 1
    await session.flush()
    data = await build_scheduling_input(
        session,
        plan.activity_id,
        seed=_integer_value(plan.solver_parameters.get("seed")),
    )
    report = validate_solution(data, await plan_solution(session, plan))
    if not report.valid:
        codes = [item.code for item in report.violations]
        await session.rollback()
        raise _validation_error(codes)
    plan.version += 1
    plan.validated_at = None
    plan.quality_metrics = {**plan.quality_metrics, "manually_adjusted": True}
    await session.commit()
    return plan


async def validate_plan(session: AsyncSession, plan: SchedulePlan) -> SchedulePlan:
    if plan.status not in {PlanStatus.DRAFT, PlanStatus.READY}:
        raise APIError(status_code=409, code="invalid_plan_transition", message="当前方案状态不可复检")
    plan.status = PlanStatus.VALIDATING
    await session.flush()
    data = await build_scheduling_input(
        session,
        plan.activity_id,
        seed=_integer_value(plan.solver_parameters.get("seed")),
    )
    solution = await plan_solution(session, plan)
    report = validate_solution(data, solution)
    if not report.valid:
        plan.status = PlanStatus.DRAFT
        plan.validated_at = None
        plan.version += 1
        await session.commit()
        raise _validation_error([item.code for item in report.violations])
    plan.status = PlanStatus.READY
    plan.validated_at = utc_now()
    plan.exception_snapshot = _exception_snapshot(data, report.used_exception_ids)
    plan.version += 1
    await session.commit()
    return plan


async def publish_plan(
    session: AsyncSession,
    plan: SchedulePlan,
    principal: Principal,
    request_id: str,
) -> SchedulePlan:
    if plan.status != PlanStatus.READY:
        raise APIError(status_code=409, code="invalid_plan_transition", message="只有已复检方案可发布")
    data = await build_scheduling_input(
        session,
        plan.activity_id,
        seed=_integer_value(plan.solver_parameters.get("seed")),
    )
    report = validate_solution(data, await plan_solution(session, plan))
    if not report.valid:
        plan.status = PlanStatus.DRAFT
        plan.validated_at = None
        plan.version += 1
        await session.commit()
        raise _validation_error([item.code for item in report.violations])
    await session.execute(
        update(SchedulePlan)
        .where(
            SchedulePlan.activity_id == plan.activity_id,
            SchedulePlan.id != plan.id,
            SchedulePlan.status == PlanStatus.PUBLISHED,
        )
        .values(status=PlanStatus.ARCHIVED, version=SchedulePlan.version + 1)
    )
    plan.status = PlanStatus.PUBLISHED
    plan.published_at = utc_now()
    plan.validated_at = utc_now()
    plan.exception_snapshot = _exception_snapshot(data, report.used_exception_ids)
    plan.version += 1
    panels = list(
        await session.scalars(
            select(PanelAssignment).where(PanelAssignment.plan_id == plan.id)
        )
    )
    existing_confirmation_ids = set(
        await session.scalars(
            select(TeacherConfirmation.panel_assignment_id).where(
                TeacherConfirmation.panel_assignment_id.in_(item.id for item in panels)
            )
        )
    ) if panels else set()
    session.add_all(
        [
            TeacherConfirmation(panel_assignment_id=item.id)
            for item in panels
            if item.id not in existing_confirmation_ids
        ]
    )
    session.add(
        AuditLog(
            actor_id=principal.user_id,
            action="plan.publish",
            object_type="schedule_plan",
            object_id=plan.id,
            request_id=request_id,
            before_summary={"status": PlanStatus.READY.value},
            after_summary={"status": PlanStatus.PUBLISHED.value},
        )
    )
    await session.commit()
    return plan


async def archive_plan(
    session: AsyncSession,
    plan: SchedulePlan,
    principal: Principal,
    request_id: str,
) -> SchedulePlan:
    if plan.status != PlanStatus.PUBLISHED:
        raise APIError(status_code=409, code="invalid_plan_transition", message="只有已发布方案可撤回")
    plan.status = PlanStatus.ARCHIVED
    plan.version += 1
    session.add(
        AuditLog(
            actor_id=principal.user_id,
            action="plan.withdraw",
            object_type="schedule_plan",
            object_id=plan.id,
            request_id=request_id,
            before_summary={"status": PlanStatus.PUBLISHED.value},
            after_summary={"status": PlanStatus.ARCHIVED.value},
        )
    )
    await session.commit()
    return plan


async def compare_plans(
    session: AsyncSession,
    left: SchedulePlan,
    right: SchedulePlan,
) -> PlanComparison:
    if left.activity_id != right.activity_id:
        raise APIError(status_code=409, code="plan_activity_mismatch", message="只能比较同一活动的方案")
    left_read = await plan_read(session, left)
    right_read = await plan_read(session, right)
    left_groups = {item.code: item for item in left_read.groups}
    right_groups = {item.code: item for item in right_read.groups}
    left_students = {
        student_id: group.code for group in left_read.groups for student_id in group.student_ids
    }
    right_students = {
        student_id: group.code for group in right_read.groups for student_id in group.student_ids
    }
    student_moves: list[dict[str, object]] = [
        {
            "student_id": str(student_id),
            "from_group": left_students.get(student_id),
            "to_group": right_students.get(student_id),
        }
        for student_id in sorted(set(left_students) | set(right_students), key=str)
        if left_students.get(student_id) != right_students.get(student_id)
    ]
    teacher_changes: list[dict[str, object]] = []
    resource_changes: list[dict[str, object]] = []
    for code in sorted(set(left_groups) | set(right_groups)):
        left_group = left_groups.get(code)
        right_group = right_groups.get(code)
        left_teachers = set(left_group.teacher_ids) if left_group else set()
        right_teachers = set(right_group.teacher_ids) if right_group else set()
        if left_teachers != right_teachers:
            teacher_changes.append(
                {
                    "group_code": code,
                    "added": [str(item) for item in sorted(right_teachers - left_teachers, key=str)],
                    "removed": [str(item) for item in sorted(left_teachers - right_teachers, key=str)],
                }
            )
        if left_group is None or right_group is None or (
            left_group.slot_id != right_group.slot_id or left_group.room_id != right_group.room_id
        ):
            resource_changes.append(
                {
                    "group_code": code,
                    "slot_changed": left_group is None
                    or right_group is None
                    or left_group.slot_id != right_group.slot_id,
                    "room_changed": left_group is None
                    or right_group is None
                    or left_group.room_id != right_group.room_id,
                }
            )
    numeric_keys = {
        key
        for key, value in {**left.quality_metrics, **right.quality_metrics}.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    objective_deltas = {
        key: _numeric_value(right.quality_metrics.get(key))
        - _numeric_value(left.quality_metrics.get(key))
        for key in sorted(numeric_keys)
    }
    return PlanComparison(
        left_plan_id=left.id,
        right_plan_id=right.id,
        student_moves=student_moves,
        teacher_changes=teacher_changes,
        resource_changes=resource_changes,
        objective_deltas=objective_deltas,
        exception_use_delta=len(right.exception_snapshot) - len(left.exception_snapshot),
    )


async def teacher_schedule(
    session: AsyncSession,
    principal: Principal,
) -> list[TeacherScheduleItem]:
    teacher = await session.scalar(select(Teacher).where(Teacher.user_id == principal.user_id))
    if teacher is None:
        raise APIError(status_code=404, code="teacher_profile_not_found", message="教师档案不存在")
    rows = (
        await session.execute(
            select(
                PanelAssignment,
                DefenseGroup,
                SchedulePlan,
                DefenseSlot,
                TeacherConfirmation,
            )
            .join(DefenseGroup, DefenseGroup.id == PanelAssignment.group_id)
            .join(SchedulePlan, SchedulePlan.id == PanelAssignment.plan_id)
            .join(DefenseSlot, DefenseSlot.id == DefenseGroup.slot_id)
            .join(
                TeacherConfirmation,
                TeacherConfirmation.panel_assignment_id == PanelAssignment.id,
            )
            .where(
                PanelAssignment.teacher_id == teacher.id,
                SchedulePlan.status == PlanStatus.PUBLISHED,
            )
            .order_by(DefenseSlot.slot_date, DefenseSlot.start_time, DefenseGroup.code)
        )
    ).all()
    result: list[TeacherScheduleItem] = []
    for panel, group, plan, slot, confirmation in rows:
        student_ids = list(
            await session.scalars(
                select(StudentAssignment.student_id)
                .where(StudentAssignment.group_id == group.id)
                .order_by(StudentAssignment.student_id)
            )
        )
        fellow_ids = list(
            await session.scalars(
                select(PanelAssignment.teacher_id)
                .where(
                    PanelAssignment.group_id == group.id,
                    PanelAssignment.teacher_id != teacher.id,
                )
                .order_by(PanelAssignment.teacher_id)
            )
        )
        result.append(
            TeacherScheduleItem(
                plan_id=plan.id,
                group_id=group.id,
                group_code=group.code,
                panel_assignment_id=panel.id,
                student_ids=student_ids,
                fellow_teacher_ids=fellow_ids,
                date=slot.slot_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                room_id=group.room_id,
                exception_marker=bool(plan.exception_snapshot),
                confirmation_status=confirmation.status,
            )
        )
    return result


async def confirm_teacher_assignment(
    session: AsyncSession,
    principal: Principal,
    panel_assignment_id: UUID,
) -> ConfirmationRead:
    row = await session.execute(
        select(TeacherConfirmation, PanelAssignment, Teacher, SchedulePlan)
        .join(
            PanelAssignment,
            PanelAssignment.id == TeacherConfirmation.panel_assignment_id,
        )
        .join(Teacher, Teacher.id == PanelAssignment.teacher_id)
        .join(SchedulePlan, SchedulePlan.id == PanelAssignment.plan_id)
        .where(
            TeacherConfirmation.panel_assignment_id == panel_assignment_id,
            Teacher.user_id == principal.user_id,
            SchedulePlan.status == PlanStatus.PUBLISHED,
        )
    )
    found = row.one_or_none()
    if found is None:
        raise APIError(status_code=404, code="assignment_not_found", message="教师答辩安排不存在")
    confirmation, _panel, _teacher, _plan = found
    if confirmation.status != ConfirmationStatus.CONFIRMED:
        confirmation.status = ConfirmationStatus.CONFIRMED
        confirmation.confirmed_at = utc_now()
        confirmation.version += 1
        await session.commit()
    return ConfirmationRead(
        panel_assignment_id=confirmation.panel_assignment_id,
        status=confirmation.status,
        confirmed_at=confirmation.confirmed_at,
        version=confirmation.version,
    )
