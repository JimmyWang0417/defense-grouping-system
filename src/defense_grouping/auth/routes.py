from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.dependencies import (
    AuthContext,
    get_auth_context,
    get_db_session,
)
from defense_grouping.auth.permissions import Principal, require_roles
from defense_grouping.auth.rate_limit import LoginRateLimiter
from defense_grouping.auth.schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenPair,
    UserCreate,
    UserRead,
    UserRolesWrite,
    UserStatusWrite,
)
from defense_grouping.auth.service import (
    change_password,
    create_user,
    list_users,
    login,
    logout,
    replace_user_roles,
    reset_user_password,
    rotate_refresh_token,
    set_user_status,
)
from defense_grouping.models.identity import Role

router = APIRouter(prefix="/api/v1")


def get_rate_limiter(request: Request) -> LoginRateLimiter:
    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if limiter is None:
        limiter = LoginRateLimiter()
        request.app.state.login_rate_limiter = limiter
    return cast(LoginRateLimiter, limiter)


@router.post("/auth/login", response_model=TokenPair)
async def login_route(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenPair:
    client_ip = request.client.host if request.client is not None else "unknown"
    return await login(
        session,
        request.app.state.settings,
        get_rate_limiter(request),
        username=payload.username,
        password=payload.password,
        client_ip=client_ip,
        device_info=payload.device_info,
    )


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh_route(
    payload: RefreshRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenPair:
    return await rotate_refresh_token(
        session,
        request.app.state.settings,
        raw_token=payload.refresh_token,
        device_info=payload.device_info,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_route(
    payload: LogoutRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    await logout(session, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/change-password", response_model=TokenPair)
async def change_password_route(
    payload: ChangePasswordRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenPair:
    return await change_password(
        session,
        request.app.state.settings,
        context.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.get("/auth/me", response_model=CurrentUserResponse)
async def current_user_route(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=context.user.id,
        username=context.user.username,
        roles=sorted(context.principal.roles, key=str),
        department_ids=sorted(context.principal.department_ids, key=str),
        must_change_password=context.user.must_change_password,
    )


SystemAdmin = Annotated[Principal, Depends(require_roles(Role.SYSTEM_ADMIN))]


@router.get("/users", response_model=list[UserRead])
async def list_users_route(
    _principal: SystemAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[UserRead]:
    return await list_users(session)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user_route(
    payload: UserCreate,
    _principal: SystemAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    return await create_user(session, payload)


@router.patch("/users/{user_id}/status", response_model=UserRead)
async def set_user_status_route(
    user_id: UUID,
    payload: UserStatusWrite,
    _principal: SystemAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    return await set_user_status(session, user_id, payload.is_active)


@router.put("/users/{user_id}/roles", response_model=UserRead)
async def replace_user_roles_route(
    user_id: UUID,
    payload: UserRolesWrite,
    _principal: SystemAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    return await replace_user_roles(session, user_id, payload.roles)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_user_password_route(
    user_id: UUID,
    payload: ResetPasswordRequest,
    _principal: SystemAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ResetPasswordResponse:
    password = await reset_user_password(session, user_id, payload.temporary_password)
    return ResetPasswordResponse(temporary_password=password)
