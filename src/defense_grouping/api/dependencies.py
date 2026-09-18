from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal
from defense_grouping.auth.security import InvalidTokenError, decode_access_token
from defense_grouping.db.session import Database
from defense_grouping.models.identity import RoleAssignment, User


@dataclass(frozen=True)
class AuthContext:
    user: User
    principal: Principal
    claims: dict[str, Any]


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async with database.session() as session:
        yield session


async def get_auth_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthContext:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise APIError(
            status_code=401,
            code="authentication_required",
            message="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(token, request.app.state.settings.jwt_secret)
        user_id = UUID(claims["sub"])
    except (InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise APIError(
            status_code=401,
            code="invalid_access_token",
            message="登录状态已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise APIError(
            status_code=401,
            code="invalid_access_token",
            message="登录状态已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    assignments = (
        await session.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user.id))
    ).all()
    principal = Principal(
        user_id=user.id,
        roles=frozenset(assignment.role for assignment in assignments),
        department_ids=frozenset(
            assignment.department_id
            for assignment in assignments
            if assignment.department_id is not None
        ),
    )
    request.state.actor_id = user.id
    return AuthContext(user=user, principal=principal, claims=claims)


async def get_current_principal(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> Principal:
    if context.user.must_change_password:
        raise APIError(
            status_code=403,
            code="password_change_required",
            message="首次登录必须先修改临时密码",
        )
    return context.principal
