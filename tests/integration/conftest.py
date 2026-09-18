from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from uuid import UUID

import httpx2
import pytest_asyncio
from fastapi import FastAPI

from defense_grouping.api.main import create_app
from defense_grouping.auth.security import hash_password
from defense_grouping.config import Settings
from defense_grouping.db.base import Base
from defense_grouping.db.session import Database
from defense_grouping.models.availability import Room
from defense_grouping.models.defense import (
    ActivityRoom,
    ActivityRuleSet,
    DefenseActivity,
    DefenseSlot,
)
from defense_grouping.models.identity import Role, RoleAssignment, User
from defense_grouping.models.master import (
    Department,
    Direction,
    Major,
    Student,
    StudentDirection,
    Teacher,
    TeacherDirection,
)

INTEGRATION_PASSWORD = "Admin Password 2026"


@dataclass(frozen=True)
class MasterHarness:
    client: httpx2.AsyncClient
    app: FastAPI
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


@dataclass(frozen=True)
class ConfiguredSchedule:
    activity_id: UUID
    student_ids: tuple[UUID, ...]
    teacher_ids: tuple[UUID, ...]
    slot_ids: tuple[UUID, ...]
    room_ids: tuple[UUID, ...]


@pytest_asyncio.fixture
async def master_harness(tmp_path: Path) -> AsyncIterator[MasterHarness]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'master.db'}",
        jwt_secret="test-secret-with-at-least-32-characters",
        storage_dir=tmp_path / "storage",
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
            app=app,
            database=database,
            department_id=department.id,
            other_department_id=other_department.id,
            other_teacher_id=other_teacher.id,
        )
    task_executor = getattr(app.state, "task_executor", None)
    if task_executor is not None:
        await task_executor.shutdown()
    await database.dispose()


@pytest_asyncio.fixture
async def configured_schedule(master_harness: MasterHarness) -> ConfiguredSchedule:
    async with master_harness.database.session() as session:
        major = Major(
            department_id=master_harness.department_id,
            code="SCHED-SE",
            name="排组软件工程",
            is_active=True,
        )
        direction = Direction(
            department_id=master_harness.department_id,
            code="SCHED-AI",
            name="智能软件",
        )
        teacher_user = User(
            username="teacher-user",
            password_hash=hash_password(INTEGRATION_PASSWORD),
            is_active=True,
            must_change_password=False,
        )
        session.add_all([major, direction, teacher_user])
        await session.flush()
        session.add(
            RoleAssignment(
                user_id=teacher_user.id,
                role=Role.TEACHER,
                department_id=master_harness.department_id,
                can_approve_exceptions=False,
            )
        )
        panel_one = Teacher(
            employee_number="SCHED-T001",
            name="排组教师一",
            department_id=master_harness.department_id,
            user_id=teacher_user.id,
            title="教授",
            title_rank=5,
            workload_limit=5,
            is_active=True,
        )
        panel_two = Teacher(
            employee_number="SCHED-T002",
            name="排组教师二",
            department_id=master_harness.department_id,
            title="副教授",
            title_rank=4,
            workload_limit=5,
            is_active=True,
        )
        advisor = Teacher(
            employee_number="SCHED-A001",
            name="学生导师",
            department_id=master_harness.department_id,
            title="教授",
            title_rank=5,
            workload_limit=5,
            is_active=True,
        )
        session.add_all([panel_one, panel_two, advisor])
        await session.flush()
        session.add_all(
            [
                TeacherDirection(teacher_id=teacher.id, direction_id=direction.id)
                for teacher in (panel_one, panel_two, advisor)
            ]
        )
        students = (
            Student(
                student_number=f"SCHED-S{index:03d}",
                name=f"答辩学生{index}",
                department_id=master_harness.department_id,
                major_id=major.id,
                advisor_id=advisor.id,
                grade="2022",
                is_active=True,
            )
            for index in (1, 2)
        )
        student_rows = tuple(students)
        session.add_all(student_rows)
        await session.flush()
        session.add_all(
            [
                StudentDirection(student_id=student.id, direction_id=direction.id)
                for student in student_rows
            ]
        )
        activity = DefenseActivity(
            department_id=master_harness.department_id,
            name="Task 8 集成答辩",
            academic_year="2026-2027",
            semester="秋",
            current_rule_version=1,
        )
        session.add(activity)
        await session.flush()
        rules = ActivityRuleSet(
            activity_id=activity.id,
            rule_version=1,
            students_per_group=2,
            teachers_per_group=2,
            chair_min_title_rank=4,
            teacher_workload_limit=5,
            soft_weights={
                "balance_students": 100,
                "balance_teacher_load": 50,
                "direction_match": 30,
                "compact_schedule": 20,
                "exception_use": 500,
            },
        )
        slots = (
            DefenseSlot(
                activity_id=activity.id,
                slot_date=date(2026, 10, 12),
                start_time=time(8, 0),
                end_time=time(10, 0),
                max_groups=1,
            ),
            DefenseSlot(
                activity_id=activity.id,
                slot_date=date(2026, 10, 12),
                start_time=time(10, 0),
                end_time=time(12, 0),
                max_groups=1,
            ),
        )
        rooms = (
            Room(
                department_id=master_harness.department_id,
                campus="创新港",
                building="泓理楼",
                name="SCHED-101",
                capacity=20,
            ),
            Room(
                department_id=master_harness.department_id,
                campus="创新港",
                building="泓理楼",
                name="SCHED-102",
                capacity=20,
            ),
        )
        session.add_all([rules, *slots, *rooms])
        await session.flush()
        session.add_all(
            [ActivityRoom(activity_id=activity.id, room_id=room.id) for room in rooms]
        )
        await session.commit()
        return ConfiguredSchedule(
            activity_id=activity.id,
            student_ids=tuple(student.id for student in student_rows),
            teacher_ids=(panel_one.id, panel_two.id, advisor.id),
            slot_ids=tuple(slot.id for slot in slots),
            room_ids=tuple(room.id for room in rooms),
        )
