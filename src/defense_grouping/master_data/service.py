import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal, ensure_department_access
from defense_grouping.db.base import as_utc
from defense_grouping.db.types import PersonType
from defense_grouping.master_data.schemas import (
    ActivityCreate,
    ActivityRead,
    ActivityRoomsWrite,
    ActivityRulesRead,
    ActivityRulesWrite,
    DepartmentChildCreate,
    MajorRead,
    RoomRead,
    SlotRead,
    SlotWrite,
    StudentCreate,
    StudentRead,
    TeacherCreate,
    TeacherRead,
)
from defense_grouping.models.availability import (
    CourseOccupancy,
    LeaveRecord,
    LeaveStatus,
    Room,
)
from defense_grouping.models.defense import (
    ActivityRoom,
    ActivityRuleSet,
    DefenseActivity,
    DefenseSlot,
    PlanStatus,
    SchedulePlan,
)
from defense_grouping.models.identity import Role
from defense_grouping.models.master import (
    Direction,
    Major,
    Student,
    StudentDirection,
    Teacher,
    TeacherDirection,
)


def require_department_scope(principal: Principal, department_id: UUID) -> None:
    try:
        ensure_department_access(principal, department_id)
    except PermissionError as exc:
        raise APIError(
            status_code=403,
            code="department_scope_denied",
            message="无权访问该院系数据",
        ) from exc


def scoped_department_ids(principal: Principal) -> set[UUID] | None:
    if Role.SYSTEM_ADMIN in principal.roles:
        return None
    return set(principal.department_ids)


def check_version(current: int, supplied: int) -> None:
    if current != supplied:
        raise APIError(
            status_code=409,
            code="optimistic_lock_conflict",
            message="数据已被他人修改，请刷新后重试",
        )


def normalized_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise APIError(
            status_code=422,
            code="timezone_required",
            message="日期时间必须包含时区",
        )
    return value.astimezone(UTC)


def interval_fingerprint(*parts: object) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def validate_directions(
    session: AsyncSession,
    department_id: UUID,
    direction_ids: set[UUID],
) -> None:
    if not direction_ids:
        return
    found = set(
        await session.scalars(
            select(Direction.id).where(
                Direction.department_id == department_id,
                Direction.id.in_(direction_ids),
            )
        )
    )
    if found != direction_ids:
        raise APIError(
            status_code=422,
            code="direction_department_mismatch",
            message="专业方向不存在或不属于当前院系",
        )


async def teacher_read(session: AsyncSession, teacher: Teacher) -> TeacherRead:
    direction_ids = list(
        await session.scalars(
            select(TeacherDirection.direction_id)
            .where(TeacherDirection.teacher_id == teacher.id)
            .order_by(TeacherDirection.direction_id)
        )
    )
    return TeacherRead(
        id=teacher.id,
        employee_number=teacher.employee_number,
        name=teacher.name,
        department_id=teacher.department_id,
        title=teacher.title,
        title_rank=teacher.title_rank,
        direction_ids=direction_ids,
        workload_limit=teacher.workload_limit,
        is_active=teacher.is_active,
        version=teacher.version,
    )


async def student_read(session: AsyncSession, student: Student) -> StudentRead:
    direction_ids = list(
        await session.scalars(
            select(StudentDirection.direction_id)
            .where(StudentDirection.student_id == student.id)
            .order_by(StudentDirection.direction_id)
        )
    )
    return StudentRead(
        id=student.id,
        student_number=student.student_number,
        name=student.name,
        department_id=student.department_id,
        major_id=student.major_id,
        grade=student.grade,
        direction_ids=direction_ids,
        advisor_id=student.advisor_id,
        is_active=student.is_active,
        version=student.version,
    )


async def create_major(
    session: AsyncSession,
    principal: Principal,
    payload: DepartmentChildCreate,
) -> MajorRead:
    require_department_scope(principal, payload.department_id)
    existing = await session.scalar(
        select(Major.id).where(
            Major.department_id == payload.department_id,
            Major.code == payload.code.strip(),
        )
    )
    if existing is not None:
        raise APIError(status_code=409, code="major_code_exists", message="专业代码已存在")
    major = Major(
        department_id=payload.department_id,
        code=payload.code.strip(),
        name=payload.name.strip(),
        is_active=True,
    )
    session.add(major)
    await session.commit()
    return MajorRead.model_validate(major)


async def create_direction(
    session: AsyncSession,
    principal: Principal,
    payload: DepartmentChildCreate,
) -> Direction:
    require_department_scope(principal, payload.department_id)
    existing = await session.scalar(
        select(Direction.id).where(
            Direction.department_id == payload.department_id,
            Direction.code == payload.code.strip(),
        )
    )
    if existing is not None:
        raise APIError(
            status_code=409,
            code="direction_code_exists",
            message="专业方向代码已存在",
        )
    direction = Direction(
        department_id=payload.department_id,
        code=payload.code.strip(),
        name=payload.name.strip(),
    )
    session.add(direction)
    await session.commit()
    return direction


async def create_teacher(
    session: AsyncSession,
    principal: Principal,
    payload: TeacherCreate,
) -> TeacherRead:
    require_department_scope(principal, payload.department_id)
    if await session.scalar(
        select(Teacher.id).where(Teacher.employee_number == payload.employee_number.strip())
    ) is not None:
        raise APIError(
            status_code=409,
            code="teacher_number_exists",
            message="教师工号已存在",
        )
    await validate_directions(session, payload.department_id, payload.direction_ids)
    teacher = Teacher(
        employee_number=payload.employee_number.strip(),
        name=payload.name.strip(),
        department_id=payload.department_id,
        title=payload.title.strip(),
        title_rank=payload.title_rank,
        workload_limit=payload.workload_limit,
        is_active=True,
    )
    session.add(teacher)
    await session.flush()
    session.add_all(
        [TeacherDirection(teacher_id=teacher.id, direction_id=item) for item in payload.direction_ids]
    )
    await session.commit()
    return await teacher_read(session, teacher)


async def list_teachers(
    session: AsyncSession,
    principal: Principal,
    *,
    page: int,
    page_size: int,
    search: str,
    sort: str,
) -> tuple[list[TeacherRead], int]:
    query = select(Teacher)
    scope = scoped_department_ids(principal)
    if scope is not None:
        query = query.where(Teacher.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(Teacher.name.ilike(pattern), Teacher.employee_number.ilike(pattern))
        )
    order_columns = {
        "employee_number": Teacher.employee_number,
        "name": Teacher.name,
        "title_rank": Teacher.title_rank,
    }
    order_column = order_columns.get(sort, Teacher.employee_number)
    count = await session.scalar(select(func.count()).select_from(query.subquery()))
    teachers = (
        await session.scalars(
            query.order_by(order_column, Teacher.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return [await teacher_read(session, teacher) for teacher in teachers], int(count or 0)


async def create_student(
    session: AsyncSession,
    principal: Principal,
    payload: StudentCreate,
) -> StudentRead:
    require_department_scope(principal, payload.department_id)
    if await session.scalar(
        select(Student.id).where(Student.student_number == payload.student_number.strip())
    ) is not None:
        raise APIError(
            status_code=409,
            code="student_number_exists",
            message="学生学号已存在",
        )
    major = await session.get(Major, payload.major_id)
    if major is None or major.department_id != payload.department_id:
        raise APIError(
            status_code=422,
            code="major_department_mismatch",
            message="专业不存在或不属于学生院系",
        )
    advisor = await session.get(Teacher, payload.advisor_id)
    if advisor is None or advisor.department_id != payload.department_id:
        raise APIError(
            status_code=422,
            code="advisor_department_mismatch",
            message="导师不存在或不属于学生院系",
        )
    await validate_directions(session, payload.department_id, payload.direction_ids)
    student = Student(
        student_number=payload.student_number.strip(),
        name=payload.name.strip(),
        department_id=payload.department_id,
        major_id=payload.major_id,
        advisor_id=payload.advisor_id,
        grade=payload.grade.strip(),
        is_active=True,
    )
    session.add(student)
    await session.flush()
    session.add_all(
        [StudentDirection(student_id=student.id, direction_id=item) for item in payload.direction_ids]
    )
    await session.commit()
    return await student_read(session, student)


async def ensure_person_in_department(
    session: AsyncSession,
    department_id: UUID,
    person_type: PersonType,
    person_id: UUID,
) -> None:
    if person_type is PersonType.TEACHER:
        teacher = await session.get(Teacher, person_id)
        matches = teacher is not None and teacher.department_id == department_id
    else:
        student = await session.get(Student, person_id)
        matches = student is not None and student.department_id == department_id
    if not matches:
        raise APIError(
            status_code=422,
            code="person_department_mismatch",
            message="人员不存在或不属于指定院系",
        )


@dataclass(frozen=True)
class AvailabilityBlock:
    code: str
    source_id: UUID
    message: str


@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    blocks: tuple[AvailabilityBlock, ...]


class AvailabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_interval(
        self,
        person_type: PersonType | str,
        person_id: UUID | str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> AvailabilityResult:
        normalized_type = PersonType(person_type)
        normalized_id = UUID(str(person_id))
        start = normalized_utc(starts_at)
        end = normalized_utc(ends_at)
        occupancies = (
            await self.session.scalars(
                select(CourseOccupancy).where(
                    CourseOccupancy.person_type == normalized_type,
                    CourseOccupancy.person_id == normalized_id,
                    CourseOccupancy.starts_at < end,
                    CourseOccupancy.ends_at > start,
                )
            )
        ).all()
        leaves = (
            await self.session.scalars(
                select(LeaveRecord).where(
                    LeaveRecord.person_type == normalized_type,
                    LeaveRecord.person_id == normalized_id,
                    LeaveRecord.status == LeaveStatus.APPROVED,
                    LeaveRecord.starts_at < end,
                    LeaveRecord.ends_at > start,
                )
            )
        ).all()
        blocks = tuple(
            [
                AvailabilityBlock("course_conflict", item.id, "与课程占用时间重叠")
                for item in occupancies
            ]
            + [
                AvailabilityBlock("leave_conflict", item.id, f"与已批准请假重叠：{item.reason}")
                for item in leaves
            ]
        )
        return AvailabilityResult(available=not blocks, blocks=blocks)

    async def is_available(
        self,
        person_type: PersonType | str,
        person_id: UUID | str,
        slot_id: UUID | str,
    ) -> AvailabilityResult:
        slot = await self.session.get(DefenseSlot, UUID(str(slot_id)))
        if slot is None:
            raise APIError(status_code=404, code="slot_not_found", message="答辩时段不存在")
        timezone = ZoneInfo("Asia/Shanghai")
        starts_at = datetime.combine(slot.slot_date, slot.start_time, timezone).astimezone(UTC)
        ends_at = datetime.combine(slot.slot_date, slot.end_time, timezone).astimezone(UTC)
        return await self.for_interval(person_type, person_id, starts_at, ends_at)


async def create_activity(
    session: AsyncSession,
    principal: Principal,
    payload: ActivityCreate,
) -> ActivityRead:
    require_department_scope(principal, payload.department_id)
    activity = DefenseActivity(
        department_id=payload.department_id,
        academic_term_id=payload.academic_term_id,
        name=payload.name.strip(),
        academic_year=payload.academic_year.strip(),
        semester=payload.semester.strip(),
    )
    session.add(activity)
    await session.commit()
    return ActivityRead.model_validate(activity)


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


async def create_slot(
    session: AsyncSession,
    principal: Principal,
    activity_id: UUID,
    payload: SlotWrite,
) -> SlotRead:
    await get_activity_scoped(session, principal, activity_id)
    overlap = await session.scalar(
        select(DefenseSlot.id).where(
            DefenseSlot.activity_id == activity_id,
            DefenseSlot.slot_date == payload.date,
            DefenseSlot.start_time < payload.end_time,
            DefenseSlot.end_time > payload.start_time,
        )
    )
    if overlap is not None:
        raise APIError(status_code=409, code="slot_overlap", message="答辩时段发生重叠")
    slot = DefenseSlot(
        activity_id=activity_id,
        slot_date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        max_groups=payload.max_groups,
    )
    session.add(slot)
    await session.commit()
    return SlotRead(
        id=slot.id,
        activity_id=slot.activity_id,
        date=slot.slot_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        max_groups=slot.max_groups,
        version=slot.version,
    )


def rule_weights(payload: ActivityRulesWrite) -> dict[str, int]:
    return {
        "balance_students": payload.balance_students_weight,
        "balance_teacher_load": payload.balance_teacher_load_weight,
        "direction_match": payload.direction_match_weight,
        "compact_schedule": payload.compact_schedule_weight,
        "exception_use": payload.exception_use_weight,
    }


def rules_read(rules: ActivityRuleSet) -> ActivityRulesRead:
    weights = rules.soft_weights
    return ActivityRulesRead(
        id=rules.id,
        activity_id=rules.activity_id,
        rule_version=rules.rule_version,
        students_per_group=rules.students_per_group,
        teachers_per_group=rules.teachers_per_group,
        chair_min_title_rank=rules.chair_min_title_rank,
        teacher_workload_limit=rules.teacher_workload_limit,
        balance_students_weight=int(weights.get("balance_students", 0)),
        balance_teacher_load_weight=int(weights.get("balance_teacher_load", 0)),
        direction_match_weight=int(weights.get("direction_match", 0)),
        compact_schedule_weight=int(weights.get("compact_schedule", 0)),
        exception_use_weight=int(weights.get("exception_use", 0)),
    )


async def write_rules(
    session: AsyncSession,
    principal: Principal,
    activity_id: UUID,
    payload: ActivityRulesWrite,
) -> ActivityRulesRead:
    activity = await get_activity_scoped(session, principal, activity_id)
    existing = await session.scalar(
        select(ActivityRuleSet.id).where(ActivityRuleSet.activity_id == activity_id)
    )
    next_version = activity.current_rule_version if existing is None else activity.current_rule_version + 1
    activity.current_rule_version = next_version
    activity.version += 1
    rules = ActivityRuleSet(
        activity_id=activity_id,
        rule_version=next_version,
        students_per_group=payload.students_per_group,
        teachers_per_group=payload.teachers_per_group,
        chair_min_title_rank=payload.chair_min_title_rank,
        teacher_workload_limit=payload.teacher_workload_limit,
        soft_weights=rule_weights(payload),
    )
    session.add(rules)
    await session.execute(
        update(SchedulePlan)
        .where(
            SchedulePlan.activity_id == activity_id,
            SchedulePlan.status.in_(
                (PlanStatus.DRAFT, PlanStatus.VALIDATING, PlanStatus.READY)
            ),
        )
        .values(
            status=PlanStatus.DRAFT,
            validated_at=None,
            version=SchedulePlan.version + 1,
        )
    )
    await session.commit()
    return rules_read(rules)


async def set_activity_rooms(
    session: AsyncSession,
    principal: Principal,
    activity_id: UUID,
    payload: ActivityRoomsWrite,
) -> list[RoomRead]:
    activity = await get_activity_scoped(session, principal, activity_id)
    rooms = list(
        await session.scalars(select(Room).where(Room.id.in_(payload.room_ids)))
    ) if payload.room_ids else []
    if len(rooms) != len(payload.room_ids) or any(
        room.department_id != activity.department_id for room in rooms
    ):
        raise APIError(
            status_code=422,
            code="room_department_mismatch",
            message="教室不存在或不属于活动院系",
        )
    await session.execute(delete(ActivityRoom).where(ActivityRoom.activity_id == activity_id))
    session.add_all([ActivityRoom(activity_id=activity_id, room_id=room.id) for room in rooms])
    await session.commit()
    return [RoomRead.model_validate(room) for room in rooms]


@dataclass(frozen=True)
class ActivitySnapshot:
    activity_id: str
    department_id: str
    students: tuple[dict[str, Any], ...]
    teachers: tuple[dict[str, Any], ...]
    slots: tuple[dict[str, Any], ...]
    rooms: tuple[dict[str, Any], ...]
    rules: dict[str, Any]
    occupancies: tuple[dict[str, Any], ...]
    leaves: tuple[dict[str, Any], ...]


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(self, activity_id: UUID | str) -> ActivitySnapshot:
        normalized_id = UUID(str(activity_id))
        activity = await self.session.get(DefenseActivity, normalized_id)
        if activity is None:
            raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
        students = (
            await self.session.scalars(
                select(Student).where(
                    Student.department_id == activity.department_id,
                    Student.is_active.is_(True),
                )
            )
        ).all()
        teachers = (
            await self.session.scalars(
                select(Teacher).where(
                    Teacher.department_id == activity.department_id,
                    Teacher.is_active.is_(True),
                )
            )
        ).all()
        slots = (
            await self.session.scalars(
                select(DefenseSlot)
                .where(DefenseSlot.activity_id == normalized_id)
                .order_by(DefenseSlot.slot_date, DefenseSlot.start_time)
            )
        ).all()
        rooms = (
            await self.session.scalars(
                select(Room)
                .join(ActivityRoom, ActivityRoom.room_id == Room.id)
                .where(ActivityRoom.activity_id == normalized_id)
                .order_by(Room.campus, Room.building, Room.name)
            )
        ).all()
        rules = await self.session.scalar(
            select(ActivityRuleSet).where(
                ActivityRuleSet.activity_id == normalized_id,
                ActivityRuleSet.rule_version == activity.current_rule_version,
            )
        )
        if rules is None:
            raise APIError(
                status_code=409,
                code="activity_rules_missing",
                message="答辩活动尚未配置规则",
            )
        person_ids = [student.id for student in students] + [teacher.id for teacher in teachers]
        occupancies = (
            await self.session.scalars(
                select(CourseOccupancy).where(CourseOccupancy.person_id.in_(person_ids))
            )
        ).all() if person_ids else []
        leaves = (
            await self.session.scalars(
                select(LeaveRecord).where(
                    LeaveRecord.person_id.in_(person_ids),
                    LeaveRecord.status == LeaveStatus.APPROVED,
                )
            )
        ).all() if person_ids else []
        return ActivitySnapshot(
            activity_id=str(activity.id),
            department_id=str(activity.department_id),
            students=tuple(
                {
                    "id": str(item.id),
                    "advisor_id": str(item.advisor_id),
                    "major_id": str(item.major_id),
                }
                for item in students
            ),
            teachers=tuple(
                {
                    "id": str(item.id),
                    "title_rank": item.title_rank,
                    "workload_limit": item.workload_limit,
                }
                for item in teachers
            ),
            slots=tuple(
                {
                    "id": str(item.id),
                    "date": item.slot_date.isoformat(),
                    "start_time": item.start_time.isoformat(),
                    "end_time": item.end_time.isoformat(),
                    "max_groups": item.max_groups,
                }
                for item in slots
            ),
            rooms=tuple(
                {"id": str(item.id), "capacity": item.capacity}
                for item in rooms
            ),
            rules=rules_read(rules).model_dump(mode="json"),
            occupancies=tuple(
                {
                    "id": str(item.id),
                    "person_id": str(item.person_id),
                    "starts_at": as_utc(item.starts_at).isoformat(),
                    "ends_at": as_utc(item.ends_at).isoformat(),
                }
                for item in occupancies
            ),
            leaves=tuple(
                {
                    "id": str(item.id),
                    "person_id": str(item.person_id),
                    "starts_at": as_utc(item.starts_at).isoformat(),
                    "ends_at": as_utc(item.ends_at).isoformat(),
                }
                for item in leaves
            ),
        )
