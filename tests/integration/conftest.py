from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx2
import pytest_asyncio

from defense_grouping.api.main import create_app
from defense_grouping.auth.security import hash_password
from defense_grouping.config import Settings
from defense_grouping.db.base import Base
from defense_grouping.db.session import Database
from defense_grouping.models.identity import Role, RoleAssignment, User
from defense_grouping.models.master import Department, Teacher

INTEGRATION_PASSWORD = "Admin Password 2026"


@dataclass(frozen=True)
class MasterHarness:
    client: httpx2.AsyncClient
    database: Database
    department_id: UUID
    other_department_id: UUID
    other_teacher_id: UUID

    async def token(self, username: str = "academic-admin") -> str:
        response = await self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": INTEGRATION_PASSWORD},
        )
        assert response.status_code == 200, response.text
        return str(response.json()["access_token"])

    async def headers(self, username: str = "academic-admin") -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.token(username)}"}


@pytest_asyncio.fixture
async def master_harness(tmp_path: Path) -> AsyncIterator[MasterHarness]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'master.db'}",
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

        for username, role, scope in (
            ("system-admin", Role.SYSTEM_ADMIN, None),
            ("academic-admin", Role.ACADEMIC_ADMIN, department.id),
            ("other-admin", Role.ACADEMIC_ADMIN, other_department.id),
        ):
            user = User(
                username=username,
                password_hash=hash_password(INTEGRATION_PASSWORD),
                is_active=True,
                must_change_password=False,
            )
            session.add(user)
            await session.flush()
            session.add(
                RoleAssignment(
                    user_id=user.id,
                    role=role,
                    department_id=scope,
                    can_approve_exceptions=role is Role.ACADEMIC_ADMIN,
                )
            )

        other_teacher = Teacher(
            employee_number="OTHER-T001",
            name="外院教师",
            department_id=other_department.id,
            title="教授",
            title_rank=5,
            workload_limit=10,
            is_active=True,
        )
        session.add(other_teacher)
        await session.commit()

    app = create_app(settings)
    app.state.database = database
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield MasterHarness(
            client=client,
            database=database,
            department_id=department.id,
            other_department_id=other_department.id,
            other_teacher_id=other_teacher.id,
        )
    await database.dispose()
