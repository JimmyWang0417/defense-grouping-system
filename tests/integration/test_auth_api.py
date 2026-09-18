from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.main import create_app
from defense_grouping.auth.security import create_access_token, hash_password
from defense_grouping.config import Settings
from defense_grouping.db.base import Base
from defense_grouping.db.session import Database
from defense_grouping.models.identity import Role, RoleAssignment, User
from defense_grouping.models.master import Department

PASSWORD = "Admin Password 2026"
NEW_PASSWORD = "New Admin Password 2026"


@dataclass(frozen=True)
class AuthHarness:
    client: httpx2.AsyncClient
    department_id: UUID
    other_department_id: UUID

    async def login(self, username: str, password: str = PASSWORD) -> dict[str, object]:
        response = await self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()


async def add_user(
    session: AsyncSession,
    *,
    username: str,
    role: Role,
    department_id: UUID | None,
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        is_active=True,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.flush()
    session.add(
        RoleAssignment(
            user_id=user.id,
            role=role,
            department_id=department_id,
            can_approve_exceptions=role is Role.ACADEMIC_ADMIN,
        )
    )
    return user


@pytest_asyncio.fixture
async def auth_harness(tmp_path: Path) -> AsyncIterator[AuthHarness]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}",
        jwt_secret="test-secret-with-at-least-32-characters",
    )
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with database.session() as session:
        department = Department(code="SE", name="软件学院")
        other_department = Department(code="CS", name="计算机学院")
        session.add_all([department, other_department])
        await session.flush()
        await add_user(
            session,
            username="system-admin",
            role=Role.SYSTEM_ADMIN,
            department_id=None,
        )
        await add_user(
            session,
            username="first-login-admin",
            role=Role.SYSTEM_ADMIN,
            department_id=None,
            must_change_password=True,
        )
        await add_user(
            session,
            username="academic-admin",
            role=Role.ACADEMIC_ADMIN,
            department_id=department.id,
        )
        await add_user(
            session,
            username="teacher-001",
            role=Role.TEACHER,
            department_id=department.id,
        )
        await session.commit()

    app = create_app(settings)
    app.state.database = database
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield AuthHarness(client, department.id, other_department.id)
    await database.dispose()


@pytest.mark.asyncio
async def test_login_and_current_user(auth_harness: AuthHarness) -> None:
    tokens = await auth_harness.login("academic-admin")

    response = await auth_harness.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["roles"] == ["academic_admin"]
    assert response.json()["department_ids"] == [str(auth_harness.department_id)]


@pytest.mark.asyncio
async def test_teacher_cannot_access_admin_route(auth_harness: AuthHarness) -> None:
    tokens = await auth_harness.login("teacher-001")

    response = await auth_harness.client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_first_login_requires_password_change(auth_harness: AuthHarness) -> None:
    tokens = await auth_harness.login("first-login-admin")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    blocked = await auth_harness.client.get("/api/v1/users", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"

    changed = await auth_harness.client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200
    allowed = await auth_harness.client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {changed.json()['access_token']}"},
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rotation_and_logout_revocation(auth_harness: AuthHarness) -> None:
    tokens = await auth_harness.login("system-admin")
    old_refresh = tokens["refresh_token"]

    rotated = await auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != old_refresh

    reused = await auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "invalid_refresh_token"

    new_refresh = rotated.json()["refresh_token"]
    logged_out = await auth_harness.client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_refresh},
    )
    assert logged_out.status_code == 204
    after_logout = await auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_refresh},
    )
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_expired_access_token_is_rejected(auth_harness: AuthHarness) -> None:
    expired = create_access_token(
        "00000000-0000-0000-0000-000000000000",
        "test-secret-with-at-least-32-characters",
        expires_delta=timedelta(seconds=-1),
    )

    response = await auth_harness.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"


@pytest.mark.asyncio
async def test_login_rate_limit(auth_harness: AuthHarness) -> None:
    for _attempt in range(5):
        response = await auth_harness.client.post(
            "/api/v1/auth/login",
            json={"username": "system-admin", "password": "wrong-password"},
        )
        assert response.status_code == 401

    limited = await auth_harness.client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "wrong-password"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "login_rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_system_admin_user_lifecycle(auth_harness: AuthHarness) -> None:
    tokens = await auth_harness.login("system-admin")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    created = await auth_harness.client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "new-teacher",
            "temporary_password": "Temporary Password 2026",
            "roles": [
                {
                    "role": "teacher",
                    "department_id": str(auth_harness.department_id),
                    "can_approve_exceptions": False,
                }
            ],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    deactivated = await auth_harness.client.patch(
        f"/api/v1/users/{user_id}/status",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    rejected = await auth_harness.client.post(
        "/api/v1/auth/login",
        json={"username": "new-teacher", "password": "Temporary Password 2026"},
    )
    assert rejected.status_code == 401

    reactivated = await auth_harness.client.patch(
        f"/api/v1/users/{user_id}/status",
        headers=headers,
        json={"is_active": True},
    )
    assert reactivated.status_code == 200
    roles = await auth_harness.client.put(
        f"/api/v1/users/{user_id}/roles",
        headers=headers,
        json={
            "roles": [
                {
                    "role": "academic_admin",
                    "department_id": str(auth_harness.department_id),
                    "can_approve_exceptions": True,
                }
            ]
        },
    )
    assert roles.status_code == 200
    assert roles.json()["roles"][0]["role"] == "academic_admin"

    reset = await auth_harness.client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=headers,
        json={"temporary_password": "Reset Password 2026"},
    )
    assert reset.status_code == 200
    relogin = await auth_harness.login("new-teacher", "Reset Password 2026")
    assert relogin["must_change_password"] is True
