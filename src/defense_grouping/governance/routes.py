from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.dependencies import get_db_session
from defense_grouping.auth.permissions import Principal, require_roles
from defense_grouping.governance.approval_service import (
    decide_exception,
    get_exception_scoped,
    request_exception,
    revoke_exception,
)
from defense_grouping.governance.schemas import (
    AuditPage,
    AuditRead,
    ExceptionRead,
    ExceptionRequest,
)
from defense_grouping.master_data.service import require_department_scope
from defense_grouping.models.defense import DefenseActivity
from defense_grouping.models.governance import ApprovalStatus, AuditLog, ConstraintException
from defense_grouping.models.identity import Role

router = APIRouter(prefix="/api/v1")

ScopedAdmin = Annotated[
    Principal,
    Depends(require_roles(Role.SYSTEM_ADMIN, Role.ACADEMIC_ADMIN)),
]
SystemAdmin = Annotated[Principal, Depends(require_roles(Role.SYSTEM_ADMIN))]
Session = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("/exceptions", response_model=ExceptionRead, status_code=201)
async def create_exception(
    payload: ExceptionRequest,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> ExceptionRead:
    return ExceptionRead.model_validate(
        await request_exception(session, principal, payload, request.state.request_id)
    )


@router.get("/exceptions", response_model=list[ExceptionRead])
async def list_exceptions(
    activity_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> list[ExceptionRead]:
    activity = await session.get(DefenseActivity, activity_id)
    if activity is None:
        return []
    require_department_scope(principal, activity.department_id)
    rows = list(
        await session.scalars(
            select(ConstraintException)
            .where(ConstraintException.activity_id == activity_id)
            .order_by(ConstraintException.created_at.desc())
        )
    )
    return [ExceptionRead.model_validate(item) for item in rows]


@router.post("/exceptions/{exception_id}/approve", response_model=ExceptionRead)
async def approve_exception(
    exception_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> ExceptionRead:
    exception = await get_exception_scoped(session, principal, exception_id)
    return ExceptionRead.model_validate(
        await decide_exception(
            session,
            principal,
            exception,
            ApprovalStatus.APPROVED,
            request.state.request_id,
        )
    )


@router.post("/exceptions/{exception_id}/reject", response_model=ExceptionRead)
async def reject_exception(
    exception_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> ExceptionRead:
    exception = await get_exception_scoped(session, principal, exception_id)
    return ExceptionRead.model_validate(
        await decide_exception(
            session,
            principal,
            exception,
            ApprovalStatus.REJECTED,
            request.state.request_id,
        )
    )


@router.post("/exceptions/{exception_id}/revoke", response_model=ExceptionRead)
async def revoke_exception_route(
    exception_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> ExceptionRead:
    exception = await get_exception_scoped(session, principal, exception_id)
    return ExceptionRead.model_validate(
        await revoke_exception(session, principal, exception, request.state.request_id)
    )


@router.get("/audit-logs", response_model=AuditPage)
async def audit_logs(
    _principal: SystemAdmin,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    action: str | None = None,
    request_id: str | None = None,
) -> AuditPage:
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    if request_id:
        statement = statement.where(AuditLog.request_id == request_id)
    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    rows = list(
        await session.scalars(
            statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return AuditPage(
        items=[AuditRead.model_validate(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )
