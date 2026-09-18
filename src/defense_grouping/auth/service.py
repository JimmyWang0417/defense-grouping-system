import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.auth.rate_limit import LoginRateLimiter
from defense_grouping.auth.schemas import (
    RoleAssignmentWrite,
    TokenPair,
    UserCreate,
    UserRead,
)
from defense_grouping.auth.security import (
    create_access_token,
    hash_password,
    new_refresh_token,
    refresh_token_digest,
    verify_password,
)
from defense_grouping.config import Settings
from defense_grouping.db.base import as_utc
from defense_grouping.models.identity import RefreshToken, Role, RoleAssignment, User

_DUMMY_PASSWORD_HASH = hash_password("Timing Protection Password 2026")


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def validate_role_assignments(assignments: list[RoleAssignmentWrite]) -> None:
    seen: set[tuple[Role, UUID | None]] = set()
    for assignment in assignments:
        if assignment.role is Role.SYSTEM_ADMIN and assignment.department_id is not None:
            raise APIError(
                status_code=422,
                code="invalid_role_scope",
                message="系统管理员不能绑定单个院系",
                fields={"roles": "系统管理员的 department_id 必须为空"},
            )
        if assignment.role is not Role.SYSTEM_ADMIN and assignment.department_id is None:
            raise APIError(
                status_code=422,
                code="invalid_role_scope",
                message="该角色必须指定院系",
                fields={"roles": "教务管理员和教师必须指定 department_id"},
            )
        key = (assignment.role, assignment.department_id)
        if key in seen:
            raise APIError(
                status_code=422,
                code="duplicate_role_assignment",
                message="角色与院系范围重复",
                fields={"roles": "存在重复项"},
            )
        seen.add(key)


def _access_token(user: User, settings: Settings) -> str:
    return create_access_token(
        str(user.id),
        settings.jwt_secret,
        settings.access_token_minutes,
        password_change_required=user.must_change_password,
    )


def _add_refresh_token(
    session: AsyncSession,
    user: User,
    settings: Settings,
    device_info: str | None,
) -> tuple[str, RefreshToken]:
    raw, digest = new_refresh_token()
    record = RefreshToken(
        user_id=user.id,
        token_digest=digest,
        device_info=device_info,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
    )
    session.add(record)
    return raw, record


def _token_pair(user: User, settings: Settings, refresh_token: str) -> TokenPair:
    return TokenPair(
        access_token=_access_token(user, settings),
        refresh_token=refresh_token,
        expires_in=settings.access_token_minutes * 60,
        must_change_password=user.must_change_password,
    )


async def login(
    session: AsyncSession,
    settings: Settings,
    limiter: LoginRateLimiter,
    *,
    username: str,
    password: str,
    client_ip: str,
    device_info: str | None,
) -> TokenPair:
    retry_after = limiter.retry_after(username, client_ip)
    if retry_after is not None:
        raise APIError(
            status_code=429,
            code="login_rate_limited",
            message="登录失败次数过多，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    normalized = normalize_username(username)
    user = await session.scalar(select(User).where(User.username == normalized))
    encoded = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, encoded)
    if user is None or not user.is_active or not password_valid:
        limiter.record_failure(username, client_ip)
        raise APIError(
            status_code=401,
            code="invalid_credentials",
            message="用户名或密码错误",
        )

    limiter.clear(username, client_ip)
    user.last_login_at = datetime.now(UTC)
    raw_refresh, _record = _add_refresh_token(session, user, settings, device_info)
    await session.commit()
    return _token_pair(user, settings, raw_refresh)


async def rotate_refresh_token(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    device_info: str | None,
) -> TokenPair:
    now = datetime.now(UTC)
    record = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_digest == refresh_token_digest(raw_token))
        .with_for_update()
    )
    if record is None or record.revoked_at is not None or as_utc(record.expires_at) <= now:
        raise APIError(
            status_code=401,
            code="invalid_refresh_token",
            message="刷新令牌无效或已过期",
        )
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise APIError(
            status_code=401,
            code="invalid_refresh_token",
            message="刷新令牌无效或已过期",
        )

    record.revoked_at = now
    raw_refresh, _new_record = _add_refresh_token(session, user, settings, device_info)
    await session.commit()
    return _token_pair(user, settings, raw_refresh)


async def logout(session: AsyncSession, raw_token: str) -> None:
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_digest == refresh_token_digest(raw_token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await session.commit()


async def change_password(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    current_password: str,
    new_password: str,
) -> TokenPair:
    if not verify_password(current_password, user.password_hash):
        raise APIError(
            status_code=422,
            code="current_password_incorrect",
            message="当前密码不正确",
            fields={"current_password": "当前密码不正确"},
        )
    if current_password == new_password:
        raise APIError(
            status_code=422,
            code="password_unchanged",
            message="新密码不能与当前密码相同",
            fields={"new_password": "请输入不同的新密码"},
        )

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    raw_refresh, _record = _add_refresh_token(session, user, settings, None)
    await session.commit()
    return _token_pair(user, settings, raw_refresh)


async def _role_writes_for_user(
    session: AsyncSession,
    user_id: UUID,
) -> list[RoleAssignmentWrite]:
    assignments = (
        await session.scalars(
            select(RoleAssignment)
            .where(RoleAssignment.user_id == user_id)
            .order_by(RoleAssignment.role, RoleAssignment.department_id)
        )
    ).all()
    return [
        RoleAssignmentWrite(
            role=assignment.role,
            department_id=assignment.department_id,
            can_approve_exceptions=assignment.can_approve_exceptions,
        )
        for assignment in assignments
    ]


async def read_user(session: AsyncSession, user: User) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        roles=await _role_writes_for_user(session, user.id),
    )


async def list_users(session: AsyncSession) -> list[UserRead]:
    users = (await session.scalars(select(User).order_by(User.username))).all()
    return [await read_user(session, user) for user in users]


async def create_user(session: AsyncSession, payload: UserCreate) -> UserRead:
    validate_role_assignments(payload.roles)
    username = normalize_username(payload.username)
    if await session.scalar(select(User.id).where(User.username == username)) is not None:
        raise APIError(status_code=409, code="username_exists", message="用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(payload.temporary_password),
        is_active=True,
        must_change_password=True,
    )
    session.add(user)
    await session.flush()
    session.add_all(
        [
            RoleAssignment(
                user_id=user.id,
                role=role.role,
                department_id=role.department_id,
                can_approve_exceptions=role.can_approve_exceptions,
            )
            for role in payload.roles
        ]
    )
    await session.commit()
    return await read_user(session, user)


async def set_user_status(session: AsyncSession, user_id: UUID, is_active: bool) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise APIError(status_code=404, code="user_not_found", message="用户不存在")
    user.is_active = is_active
    if not is_active:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await session.commit()
    return await read_user(session, user)


async def replace_user_roles(
    session: AsyncSession,
    user_id: UUID,
    assignments: list[RoleAssignmentWrite],
) -> UserRead:
    validate_role_assignments(assignments)
    user = await session.get(User, user_id)
    if user is None:
        raise APIError(status_code=404, code="user_not_found", message="用户不存在")
    await session.execute(delete(RoleAssignment).where(RoleAssignment.user_id == user_id))
    session.add_all(
        [
            RoleAssignment(
                user_id=user_id,
                role=assignment.role,
                department_id=assignment.department_id,
                can_approve_exceptions=assignment.can_approve_exceptions,
            )
            for assignment in assignments
        ]
    )
    await session.commit()
    return await read_user(session, user)


async def reset_user_password(
    session: AsyncSession,
    user_id: UUID,
    temporary_password: str | None,
) -> str:
    user = await session.get(User, user_id)
    if user is None:
        raise APIError(status_code=404, code="user_not_found", message="用户不存在")
    generated = temporary_password or secrets.token_urlsafe(18)
    user.password_hash = hash_password(generated)
    user.must_change_password = True
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return generated
