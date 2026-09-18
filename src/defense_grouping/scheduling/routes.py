from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.dependencies import get_db_session
from defense_grouping.auth.permissions import Principal, require_roles
from defense_grouping.models.defense import SchedulePlan
from defense_grouping.models.identity import Role
from defense_grouping.scheduling.executor import TaskExecutor
from defense_grouping.scheduling.schemas import (
    ConfirmationRead,
    GroupAdjustment,
    PlanComparison,
    PlanRead,
    ScheduleJobCreate,
    ScheduleJobRead,
    TeacherScheduleItem,
)
from defense_grouping.scheduling.service import (
    adjust_group,
    archive_plan,
    cancel_schedule_job,
    compare_plans,
    confirm_teacher_assignment,
    copy_plan,
    create_schedule_job,
    get_activity_scoped,
    get_job_scoped,
    get_plan_scoped,
    job_read,
    plan_read,
    publish_plan,
    teacher_schedule,
    validate_plan,
)

router = APIRouter(prefix="/api/v1")

ScopedAdmin = Annotated[
    Principal,
    Depends(require_roles(Role.SYSTEM_ADMIN, Role.ACADEMIC_ADMIN)),
]
TeacherPrincipal = Annotated[Principal, Depends(require_roles(Role.TEACHER))]
Session = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]


@router.post(
    "/activities/{activity_id}/schedule-jobs",
    response_model=ScheduleJobRead,
    status_code=202,
)
async def create_job(
    activity_id: UUID,
    payload: ScheduleJobCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    principal: ScopedAdmin,
    session: Session,
) -> ScheduleJobRead:
    job, data = await create_schedule_job(
        session,
        principal,
        activity_id,
        payload,
        idempotency_key.strip(),
    )
    if data is not None:
        cast(TaskExecutor, request.app.state.task_executor).submit(job.id, data)
    return job_read(job)


@router.get("/schedule-jobs/{job_id}", response_model=ScheduleJobRead)
async def read_job(
    job_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> ScheduleJobRead:
    return job_read(await get_job_scoped(session, principal, job_id))


@router.delete("/schedule-jobs/{job_id}", response_model=ScheduleJobRead)
async def cancel_job(
    job_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> ScheduleJobRead:
    job = await get_job_scoped(session, principal, job_id)
    job = await cancel_schedule_job(session, job)
    cast(TaskExecutor, request.app.state.task_executor).cancel(job.id)
    return job_read(job)


@router.get("/activities/{activity_id}/plans", response_model=list[PlanRead])
async def list_plans(
    activity_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> list[PlanRead]:
    await get_activity_scoped(session, principal, activity_id)
    plans = list(
        await session.scalars(
            select(SchedulePlan)
            .where(SchedulePlan.activity_id == activity_id)
            .order_by(SchedulePlan.version_number.desc())
        )
    )
    return [await plan_read(session, plan) for plan in plans]


@router.get("/plans/{plan_id}", response_model=PlanRead)
async def read_plan(
    plan_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    return await plan_read(session, await get_plan_scoped(session, principal, plan_id))


@router.post("/plans/{plan_id}/copy", response_model=PlanRead, status_code=201)
async def duplicate_plan(
    plan_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    source = await get_plan_scoped(session, principal, plan_id)
    return await plan_read(session, await copy_plan(session, source, principal))


@router.get("/plans/{plan_id}/compare/{other_plan_id}", response_model=PlanComparison)
async def compare_plan_versions(
    plan_id: UUID,
    other_plan_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> PlanComparison:
    left = await get_plan_scoped(session, principal, plan_id)
    right = await get_plan_scoped(session, principal, other_plan_id)
    return await compare_plans(session, left, right)


@router.patch("/plans/{plan_id}/groups/{group_id}", response_model=PlanRead)
async def edit_group(
    plan_id: UUID,
    group_id: UUID,
    payload: GroupAdjustment,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    plan = await get_plan_scoped(session, principal, plan_id)
    return await plan_read(session, await adjust_group(session, plan, group_id, payload))


@router.post("/plans/{plan_id}/validate", response_model=PlanRead)
async def revalidate_plan(
    plan_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    plan = await get_plan_scoped(session, principal, plan_id)
    return await plan_read(session, await validate_plan(session, plan))


@router.post("/plans/{plan_id}/publish", response_model=PlanRead)
async def publish_plan_version(
    plan_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    plan = await get_plan_scoped(session, principal, plan_id)
    published = await publish_plan(session, plan, principal, request.state.request_id)
    return await plan_read(session, published)


@router.post("/plans/{plan_id}/withdraw", response_model=PlanRead)
@router.post("/plans/{plan_id}/archive", response_model=PlanRead)
async def withdraw_plan_version(
    plan_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
) -> PlanRead:
    plan = await get_plan_scoped(session, principal, plan_id)
    archived = await archive_plan(session, plan, principal, request.state.request_id)
    return await plan_read(session, archived)


@router.get("/teacher/schedule", response_model=list[TeacherScheduleItem])
async def read_teacher_schedule(
    principal: TeacherPrincipal,
    session: Session,
) -> list[TeacherScheduleItem]:
    return await teacher_schedule(session, principal)


@router.post(
    "/teacher/assignments/{panel_assignment_id}/confirm",
    response_model=ConfirmationRead,
)
async def confirm_assignment(
    panel_assignment_id: UUID,
    principal: TeacherPrincipal,
    session: Session,
) -> ConfirmationRead:
    return await confirm_teacher_assignment(session, principal, panel_assignment_id)
