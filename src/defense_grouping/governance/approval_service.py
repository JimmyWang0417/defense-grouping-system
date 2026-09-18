from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal
from defense_grouping.db.base import as_utc
from defense_grouping.governance.audit import write_audit
from defense_grouping.governance.schemas import ExceptionRequest
from defense_grouping.master_data.service import require_department_scope
from defense_grouping.models.defense import DefenseActivity, DefenseSlot
from defense_grouping.models.governance import ApprovalStatus, ConstraintException
from defense_grouping.models.identity import Role, RoleAssignment, User
from defense_grouping.models.master import Student, Teacher


async def get_exception_scoped(
    session: AsyncSession,
    principal: Principal,
    exception_id: UUID,
) -> ConstraintException:
    exception = await session.get(ConstraintException, exception_id)
    if exception is None:
        raise APIError(status_code=404, code="exception_not_found", message="例外申请不存在")
    activity = await session.get(DefenseActivity, exception.activity_id)
    if activity is None:
        raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
    require_department_scope(principal, activity.department_id)
    return exception


async def _validate_subjects(
    session: AsyncSession,
    payload: ExceptionRequest,
    department_id: UUID,
) -> None:
    if payload.teacher_id is not None:
        teacher = await session.get(Teacher, payload.teacher_id)
        if teacher is None or teacher.department_id != department_id:
            raise APIError(
                status_code=422,
                code="exception_teacher_invalid",
                message="例外教师不存在或不属于活动院系",
            )
    if payload.student_id is not None:
        student = await session.get(Student, payload.student_id)
        if student is None or student.department_id != department_id:
            raise APIError(
                status_code=422,
                code="exception_student_invalid",
                message="例外学生不存在或不属于活动院系",
            )
    if payload.person_id is not None:
        student = await session.get(Student, payload.person_id)
        teacher = await session.get(Teacher, payload.person_id)
        if not (
            (student is not None and student.department_id == department_id)
            or (teacher is not None and teacher.department_id == department_id)
        ):
            raise APIError(
                status_code=422,
                code="exception_person_invalid",
                message="例外人员不存在或不属于活动院系",
            )
    if payload.slot_id is not None:
        slot = await session.get(DefenseSlot, payload.slot_id)
        if slot is None or slot.activity_id != payload.activity_id:
            raise APIError(
                status_code=422,
                code="exception_slot_invalid",
                message="例外时段不存在或不属于当前活动",
            )


async def request_exception(
    session: AsyncSession,
    principal: Principal,
    payload: ExceptionRequest,
    request_id: str,
) -> ConstraintException:
    activity = await session.get(DefenseActivity, payload.activity_id)
    if activity is None:
        raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
    require_department_scope(principal, activity.department_id)
    if payload.expires_at.tzinfo is None:
        raise APIError(status_code=422, code="timezone_required", message="例外有效期必须包含时区")
    if payload.expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise APIError(status_code=422, code="exception_expired", message="例外有效期必须晚于当前时间")
    await _validate_subjects(session, payload, activity.department_id)
    exception = ConstraintException(
        activity_id=payload.activity_id,
        constraint_code=payload.constraint_code,
        subject_type=payload.subject_type,
        teacher_id=payload.teacher_id,
        student_id=payload.student_id,
        person_id=payload.person_id,
        slot_id=payload.slot_id,
        reason=payload.reason.strip(),
        requester_id=principal.user_id,
        expires_at=payload.expires_at.astimezone(UTC),
        status=ApprovalStatus.PENDING,
    )
    session.add(exception)
    await session.flush()
    await write_audit(
        session,
        actor_id=principal.user_id,
        action="exception.requested",
        object_type="constraint_exception",
        object_id=exception.id,
        request_id=request_id,
        before_summary=None,
        after_summary={
            "status": ApprovalStatus.PENDING.value,
            "constraint_code": exception.constraint_code,
            "subject_type": exception.subject_type,
        },
    )
    await session.commit()
    return exception


async def _can_approve(
    session: AsyncSession,
    principal: Principal,
    department_id: UUID,
) -> bool:
    if Role.SYSTEM_ADMIN in principal.roles:
        return True
    assignment = await session.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == principal.user_id,
            RoleAssignment.role == Role.ACADEMIC_ADMIN,
            RoleAssignment.department_id == department_id,
            RoleAssignment.can_approve_exceptions.is_(True),
        )
    )
    user = await session.get(User, principal.user_id)
    return assignment is not None and user is not None and user.is_active


async def decide_exception(
    session: AsyncSession,
    principal: Principal,
    exception: ConstraintException,
    decision: ApprovalStatus,
    request_id: str,
) -> ConstraintException:
    if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
        raise ValueError("decision must be approved or rejected")
    if exception.status != ApprovalStatus.PENDING:
        raise APIError(status_code=409, code="invalid_exception_transition", message="例外申请已经处理")
    if exception.requester_id == principal.user_id:
        raise APIError(
            status_code=403,
            code="self_approval_forbidden",
            message="申请人不能审批自己的例外",
        )
    activity = await session.get(DefenseActivity, exception.activity_id)
    if activity is None:
        raise APIError(status_code=404, code="activity_not_found", message="答辩活动不存在")
    if not await _can_approve(session, principal, activity.department_id):
        raise APIError(status_code=403, code="approval_forbidden", message="当前账号没有例外审批权限")
    if decision == ApprovalStatus.APPROVED and as_utc(exception.expires_at) <= datetime.now(UTC):
        raise APIError(status_code=409, code="exception_expired", message="已过期例外不能批准")
    exception.status = decision
    exception.approver_id = principal.user_id
    exception.decided_at = datetime.now(UTC)
    exception.version += 1
    await write_audit(
        session,
        actor_id=principal.user_id,
        action=f"exception.{decision.value}",
        object_type="constraint_exception",
        object_id=exception.id,
        request_id=request_id,
        before_summary={"status": ApprovalStatus.PENDING.value},
        after_summary={"status": decision.value},
    )
    await session.commit()
    return exception


async def revoke_exception(
    session: AsyncSession,
    principal: Principal,
    exception: ConstraintException,
    request_id: str,
) -> ConstraintException:
    if exception.status != ApprovalStatus.APPROVED:
        raise APIError(status_code=409, code="invalid_exception_transition", message="只有已批准例外可撤销")
    exception.status = ApprovalStatus.REVOKED
    exception.revoked_at = datetime.now(UTC)
    exception.version += 1
    await write_audit(
        session,
        actor_id=principal.user_id,
        action="exception.revoked",
        object_type="constraint_exception",
        object_id=exception.id,
        request_id=request_id,
        before_summary={"status": ApprovalStatus.APPROVED.value},
        after_summary={"status": ApprovalStatus.REVOKED.value},
    )
    await session.commit()
    return exception
