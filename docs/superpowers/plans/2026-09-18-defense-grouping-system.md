# Defense Grouping System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable Flet + FastAPI defense-grouping system that imports academic data, generates conflict-free defense schedules, supports governed exceptions and versioned publication, and can later migrate from SQLite to PostgreSQL.

**Architecture:** The Flet client communicates only with a versioned FastAPI REST API. FastAPI owns authentication, RBAC, transactional imports, scheduling services, plan versioning, approvals, auditing, and exports; SQLAlchemy 2.x isolates SQLite/PostgreSQL persistence, while a serializable scheduling domain feeds OR-Tools CP-SAT through a replaceable task executor.

**Tech Stack:** Python 3.12–3.14, uv, Flet 1.x, FastAPI, Pydantic 2, SQLAlchemy 2.x async ORM, Alembic, SQLite/aiosqlite, PostgreSQL/asyncpg, pwdlib Argon2, PyJWT, openpyxl, OR-Tools 9.15, pytest, Hypothesis, Ruff, mypy.

## Global Constraints

- The authoritative product requirements are in `docs/superpowers/specs/2026-09-18-defense-grouping-system-design.md`.
- The Flet client must never import database models or open a database connection.
- All API routes live below `/api/v1`; every error response contains `code`, `message`, and `request_id`.
- Unapproved hard constraints may not be violated by the solver, manual adjustment, or publication.
- Published plans are immutable; changes create a new draft version.
- Local mode uses SQLite and one command to start the API and client; server mode uses the same business code with PostgreSQL.
- Use UUID primary keys, UTC timestamps in storage, Asia/Shanghai for default display, and optimistic-lock `version` columns on mutable aggregate roots.
- Support Windows, macOS, Linux desktop, and modern browsers; mobile is read-only for published schedules.
- Use `uv run` for project commands and commit `uv.lock`.
- Work test-first, run `uv run ruff check .`, `uv run mypy src`, and the relevant pytest selection before every task commit.

---

## Planned File Structure

```text
.
├── .env.example
├── .github/workflows/ci.yml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── main.py
├── pyproject.toml
├── scripts/dev.py
├── src/defense_grouping/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── errors.py
│   │   └── main.py
│   ├── auth/
│   │   ├── permissions.py
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   └── service.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── types.py
│   ├── models/
│   │   ├── identity.py
│   │   ├── master.py
│   │   ├── availability.py
│   │   ├── defense.py
│   │   └── governance.py
│   ├── master_data/
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   └── service.py
│   ├── imports_exports/
│   │   ├── export_service.py
│   │   ├── import_service.py
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   └── templates.py
│   ├── scheduling/
│   │   ├── domain.py
│   │   ├── executor.py
│   │   ├── precheck.py
│   │   ├── routes.py
│   │   ├── service.py
│   │   ├── solver.py
│   │   └── validator.py
│   ├── governance/
│   │   ├── approval_service.py
│   │   ├── audit.py
│   │   └── routes.py
│   └── client/
│       ├── api_client.py
│       ├── main.py
│       ├── router.py
│       ├── session.py
│       ├── theme.py
│       ├── components/
│       └── views/
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    ├── client/
    ├── e2e/
    └── performance/
```

---

### Task 1: Project Skeleton and Quality Gates

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/defense_grouping/__init__.py`
- Create: `src/defense_grouping/config.py`
- Create: `src/defense_grouping/api/errors.py`
- Create: `src/defense_grouping/api/main.py`
- Create: `src/defense_grouping/cli.py`
- Create: `scripts/dev.py`
- Create: `tests/unit/test_app_boot.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `Settings`, `get_settings() -> Settings`, `create_app(settings: Settings | None = None) -> FastAPI`, and the `defense-grouping` CLI.
- Produces: API error envelope `{"error": {"code": str, "message": str, "request_id": str, "fields": dict[str, str]}}`.

- [x] **Step 1: Write the bootstrap tests**

```python
# tests/unit/test_app_boot.py
from fastapi.testclient import TestClient

from defense_grouping.api.main import create_app
from defense_grouping.config import Settings


def test_health_endpoint_reports_local_database(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret-with-at-least-32-characters",
    )
    response = TestClient(create_app(settings)).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "sqlite"}


def test_unknown_route_uses_error_envelope(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret-with-at-least-32-characters",
    )
    response = TestClient(create_app(settings)).get("/api/v1/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"]
```

- [x] **Step 2: Create the package metadata and lock dependencies**

> **2026-09-18 dependency note:** The locked FastAPI release resolves Starlette 1.6,
> whose official test-client documentation now prefers `httpx2`; its deprecated
> plain-`httpx` fallback hangs with the resolved AnyIO combination in this environment.
> Add `httpx2>=2,<3` to the development group while retaining `httpx` for the
> application API client. This changes only the test transport, not the public API.

Use this project configuration, then run `uv lock`:

```toml
[project]
name = "defense-grouping-system"
version = "0.1.0"
description = "Defense grouping and academic scheduling system"
requires-python = ">=3.12,<3.15"
dependencies = [
  "aiosqlite>=0.21,<1",
  "alembic>=1.16,<2",
  "asyncpg>=0.30,<1",
  "fastapi[standard]>=0.116,<1",
  "flet>=1,<2",
  "httpx>=0.28,<1",
  "keyring>=25,<26",
  "openpyxl>=3.1,<4",
  "ortools>=9.15,<10",
  "pwdlib[argon2]>=0.3,<1",
  "pydantic-settings>=2.10,<3",
  "pyjwt[crypto]>=2.10,<3",
  "sqlalchemy[asyncio]>=2.0,<2.1",
  "typer>=0.16,<1",
]

[dependency-groups]
dev = [
  "hypothesis>=6.138,<7",
  "mypy>=1.17,<2",
  "psutil>=7,<8",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1,<2",
  "pytest-cov>=6,<8",
  "ruff>=0.12,<1",
  "testcontainers[postgres]>=4.12,<5",
]

[project.scripts]
defense-grouping = "defense_grouping.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/defense_grouping"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["defense_grouping"]
```

- [x] **Step 3: Run the bootstrap tests and confirm the expected import failure**

Run: `uv run pytest tests/unit/test_app_boot.py -q`

Expected: FAIL because `defense_grouping.api.main` does not exist.

- [x] **Step 4: Implement settings, request IDs, errors, and the app factory**

```python
# src/defense_grouping/config.py
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DEFENSE_", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./data/defense_grouping.db"
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    display_timezone: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# src/defense_grouping/api/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from defense_grouping.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    app = FastAPI(title="答辩分组系统", version="0.1.0")
    app.state.settings = active_settings

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        import uuid

        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "资源不存在", "request_id": request.state.request_id, "fields": {}}},
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        engine_name = "sqlite" if active_settings.database_url.startswith("sqlite") else "postgresql"
        return {"status": "ok", "database": engine_name}

    return app
```

Implement `scripts/dev.py` so it generates `.runtime/local.env` with a cryptographically random secret when absent, exports those values to its child-process environment, starts Uvicorn with `defense_grouping.api.main:create_app --factory` on port 8765, waits for `/api/v1/health`, and then runs the Flet entry point. Terminating the script must terminate both child processes.

- [x] **Step 5: Run quality gates**

Run: `uv run pytest tests/unit/test_app_boot.py -q && uv run ruff check . && uv run mypy src`

Expected: all commands pass.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .env.example README.md scripts src tests/unit/test_app_boot.py
git commit -m "build: bootstrap Flet and FastAPI project"
```

**Progress (2026-09-18):** Added the locked Python project, settings and API factory,
stable request/error envelopes, CLI, supervised local launcher, ignore rules, and bootstrap
tests. The test was first observed failing with `ModuleNotFoundError`; after implementation,
`pytest` reports 3 passed, Ruff reports all checks passed, and strict mypy reports no issues.

---

### Task 2: Async Database Model and Alembic Migration

**Files:**
- Create: `src/defense_grouping/db/base.py`
- Create: `src/defense_grouping/db/session.py`
- Create: `src/defense_grouping/db/types.py`
- Create: `src/defense_grouping/models/identity.py`
- Create: `src/defense_grouping/models/master.py`
- Create: `src/defense_grouping/models/availability.py`
- Create: `src/defense_grouping/models/defense.py`
- Create: `src/defense_grouping/models/governance.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial_schema.py`
- Create: `tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `Base`, `Database`, `get_session() -> AsyncIterator[AsyncSession]`.
- Produces: UUID-keyed ORM models named in design section 6 plus `AcademicTerm`.
- Consumes: `Settings.database_url`.

- [x] **Step 1: Write migration tests**

```python
# tests/integration/test_migrations.py
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_required_tables(tmp_path: Path):
    database = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")
    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names())
    assert {
        "users", "role_assignments", "departments", "majors", "directions",
        "teachers", "students", "academic_terms", "course_occupancies",
        "leave_records", "rooms", "defense_activities", "defense_slots",
        "activity_rooms", "activity_rule_sets", "schedule_jobs", "schedule_plans", "defense_groups",
        "panel_assignments", "student_assignments", "constraint_exceptions",
        "teacher_confirmations", "import_batches", "audit_logs", "refresh_tokens",
    } <= tables
```

- [x] **Step 2: Run the migration test and verify failure**

Run: `uv run pytest tests/integration/test_migrations.py -q`

Expected: FAIL because `alembic.ini` is absent.

- [x] **Step 3: Implement cross-database base types and sessions**

```python
# src/defense_grouping/db/base.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDTimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
```

Use SQLAlchemy's portable `Uuid(as_uuid=True)` for IDs. `Database` must create one `AsyncEngine` and one `async_sessionmaker`, enable SQLite foreign keys on connect, and expose `dispose()` for tests and shutdown.

- [x] **Step 4: Implement focused model modules**

Use these exact enums and relationships:

```python
from enum import StrEnum


class Role(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    ACADEMIC_ADMIN = "academic_admin"
    TEACHER = "teacher"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
```

Add named uniqueness constraints for department code, major code within department, teacher employee number, student number, activity slot interval, room identity, plan version within activity, and one student assignment per plan. Store rule weights and audit before/after summaries as JSON; do not store whole uploaded workbooks in the database.

- [x] **Step 5: Create and verify the initial migration**

Run:

```bash
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
uv run pytest tests/integration/test_migrations.py -q
```

Expected: migration test passes and `alembic check` reports no pending model change.

- [x] **Step 6: Run quality gates and commit**

```bash
uv run alembic check
uv run pytest tests/integration/test_migrations.py -q
uv run ruff check .
uv run mypy src
git add alembic.ini alembic src/defense_grouping/db src/defense_grouping/models tests/integration/test_migrations.py
git commit -m "feat: add portable academic scheduling schema"
```

**Progress (2026-09-18):** Added the async database owner/session boundary, portable UUID
and string-enum models, named uniqueness constraints, 28 initial tables, and an autogenerated
`0001` Alembic migration. The migration test was first observed failing because no Alembic
configuration existed; it now passes, `alembic check` reports no new operations, and Ruff plus
strict mypy pass.

---

### Task 3: Authentication, Refresh Tokens, and Department-Scoped RBAC

**Files:**
- Create: `src/defense_grouping/auth/security.py`
- Create: `src/defense_grouping/auth/schemas.py`
- Create: `src/defense_grouping/auth/permissions.py`
- Create: `src/defense_grouping/auth/service.py`
- Create: `src/defense_grouping/auth/routes.py`
- Create: `src/defense_grouping/api/dependencies.py`
- Modify: `src/defense_grouping/api/main.py`
- Modify: `src/defense_grouping/cli.py`
- Create: `src/defense_grouping/auth/rate_limit.py`
- Create: `tests/unit/test_security.py`
- Create: `tests/integration/test_auth_api.py`

**Interfaces:**
- Produces: `Principal(user_id: UUID, roles: frozenset[Role], department_ids: frozenset[UUID])`.
- Produces: `require_roles(*roles: Role)` and `require_department(principal, department_id)`.
- Produces API: `POST /api/v1/auth/login`, `/refresh`, `/logout`, `/change-password`, and `GET /me`.
- Produces system-admin APIs for user creation, activation/deactivation, role assignment, department scope, and temporary-password reset.

- [ ] **Step 1: Write password and token tests**

```python
# tests/unit/test_security.py
from defense_grouping.auth.security import hash_password, verify_password


def test_password_hash_uses_argon2_and_verifies():
    encoded = hash_password("Correct Horse Battery Staple 2026")
    assert encoded.startswith("$argon2")
    assert verify_password("Correct Horse Battery Staple 2026", encoded)
    assert not verify_password("wrong", encoded)
```

```python
# tests/integration/test_auth_api.py
def test_teacher_cannot_access_admin_route(client, teacher_token):
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
```

- [ ] **Step 2: Run auth tests and verify failure**

Run: `uv run pytest tests/unit/test_security.py tests/integration/test_auth_api.py -q`

Expected: FAIL because auth modules and fixtures are absent.

- [ ] **Step 3: Implement security primitives**

```python
# src/defense_grouping/auth/security.py
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(subject: str, secret: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "iat": now, "exp": now + timedelta(minutes=minutes)}, secret, algorithm="HS256")


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()
```

Store only the refresh-token SHA-256 digest. Rotate refresh tokens on every refresh and revoke the old record in the same transaction. Return a generic login error for unknown username and wrong password.

- [ ] **Step 4: Implement RBAC and bootstrap admin CLI**

```python
from dataclasses import dataclass
from uuid import UUID

from defense_grouping.models.identity import Role


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    roles: frozenset[Role]
    department_ids: frozenset[UUID]


def ensure_department_access(principal: Principal, department_id: UUID) -> None:
    if Role.SYSTEM_ADMIN not in principal.roles and department_id not in principal.department_ids:
        raise PermissionError("department_scope_denied")
```

Implement `defense-grouping init-admin --username admin`. It generates a random temporary password when the user supplies none, prints it once, stores only the Argon2 hash, and sets `must_change_password=True`. Re-running the command for an existing active admin must not reset the password.

Implement a `LoginRateLimiter` keyed by normalized username and client IP. In local mode it allows 5 failed attempts per 15 minutes and clears the counter after a successful login. Expose a storage protocol so server deployment can replace the in-memory implementation with Redis. The rate-limit response is HTTP 429 with code `login_rate_limited` and a `Retry-After` header.

- [ ] **Step 5: Register auth routes and test refresh rotation**

Add integration cases for successful login, mandatory first password change, expired access token, refresh rotation, logout revocation, login rate limiting, system-admin user lifecycle, and an academic administrator denied access to another department.

Run: `uv run pytest tests/unit/test_security.py tests/integration/test_auth_api.py -q`

Expected: all cases pass.

- [ ] **Step 6: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/unit/test_security.py tests/integration/test_auth_api.py -q
git add src/defense_grouping/auth src/defense_grouping/api src/defense_grouping/cli.py tests
git commit -m "feat: add secure authentication and scoped RBAC"
```

---

### Task 4: Master Data, Availability, Rooms, and Defense Activities

**Files:**
- Create: `src/defense_grouping/master_data/schemas.py`
- Create: `src/defense_grouping/master_data/service.py`
- Create: `src/defense_grouping/master_data/routes.py`
- Modify: `src/defense_grouping/api/main.py`
- Create: `tests/integration/test_master_data_api.py`
- Create: `tests/integration/test_activity_api.py`

**Interfaces:**
- Produces paginated CRUD APIs for departments, majors, directions, teachers, students, terms, occupancies, leaves, rooms, activities, slots, and rules.
- Produces: `AvailabilityService.is_available(person_type, person_id, slot_id) -> AvailabilityResult`.
- Produces: `ActivityService.snapshot(activity_id) -> ActivitySnapshot` for import and scheduling tasks.

- [ ] **Step 1: Write cross-entity and scope tests**

```python
def test_student_advisor_must_belong_to_activity_department(admin_client, department, other_teacher):
    response = admin_client.post(
        "/api/v1/students",
        json={
            "student_number": "S001",
            "name": "李明",
            "department_id": str(department.id),
            "major_id": str(department.major_id),
            "advisor_id": str(other_teacher.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "advisor_department_mismatch"


def test_overlapping_slots_are_rejected(admin_client, activity, slot):
    response = admin_client.post(
        f"/api/v1/activities/{activity.id}/slots",
        json={"date": str(slot.date), "start_time": "09:00", "end_time": "11:00"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_overlap"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/integration/test_master_data_api.py tests/integration/test_activity_api.py -q`

Expected: FAIL with missing routes.

- [ ] **Step 3: Implement schemas and service contracts**

```python
from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, Field


class TeacherCreate(BaseModel):
    employee_number: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    department_id: UUID
    title_rank: int = Field(ge=1, le=10)
    direction_ids: set[UUID] = Field(default_factory=set)
    workload_limit: int = Field(ge=1, le=100)


class ActivityRulesWrite(BaseModel):
    students_per_group: int = Field(ge=1, le=100)
    teachers_per_group: int = Field(ge=1, le=20)
    chair_min_title_rank: int = Field(ge=1, le=10)
    teacher_workload_limit: int = Field(ge=1, le=100)
    balance_students_weight: int = Field(ge=0, le=1000)
    balance_teacher_load_weight: int = Field(ge=0, le=1000)
    direction_match_weight: int = Field(ge=0, le=1000)
    compact_schedule_weight: int = Field(ge=0, le=1000)
    exception_use_weight: int = Field(ge=0, le=1000)


class SlotWrite(BaseModel):
    date: date
    start_time: time
    end_time: time
    max_groups: int = Field(ge=1, le=200)
```

Every list endpoint accepts `page`, `page_size`, `search`, and deterministic `sort`; cap `page_size` at 200. Service methods accept `Principal`, enforce department scope, and raise typed domain errors translated by one API exception handler.

- [ ] **Step 4: Implement availability normalization**

Persist expanded, exact-date course occupancies. The course import service may derive them from term/week data, but the scheduler reads only exact intervals. `AvailabilityService` reports all blocking records, not only a boolean:

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AvailabilityBlock:
    code: str
    source_id: UUID
    message: str


@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    blocks: tuple[AvailabilityBlock, ...]
```

- [ ] **Step 5: Pass API and invariant tests**

Add tests for duplicate business numbers, pagination, department isolation, leave/slot overlap boundaries, activity rule validation, room capacity, and optimistic lock conflicts.

Run: `uv run pytest tests/integration/test_master_data_api.py tests/integration/test_activity_api.py -q`

Expected: all cases pass.

- [ ] **Step 6: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/integration/test_master_data_api.py tests/integration/test_activity_api.py -q
git add src/defense_grouping/master_data src/defense_grouping/api tests/integration
git commit -m "feat: add scoped academic data and activity APIs"
```

---

### Task 5: Transactional Excel Template, Preflight, and Confirmed Import

**Files:**
- Create: `src/defense_grouping/imports_exports/templates.py`
- Create: `src/defense_grouping/imports_exports/schemas.py`
- Create: `src/defense_grouping/imports_exports/import_service.py`
- Create: `src/defense_grouping/imports_exports/routes.py`
- Modify: `src/defense_grouping/api/main.py`
- Create: `tests/fixtures/imports/`
- Create: `tests/integration/test_imports.py`

**Interfaces:**
- Produces: `ImportKind = student | teacher | course | leave | slot | room`.
- Produces: `preflight(kind, workbook, principal) -> ImportPreview` and `confirm(batch_id, principal) -> ImportResult`.
- Produces API: template download, upload/preflight, preview retrieval, and confirm.

- [ ] **Step 1: Write preflight and rollback tests**

```python
def test_student_preflight_reports_exact_cell(admin_client, student_workbook_with_bad_advisor):
    created = admin_client.post(
        "/api/v1/imports/student/preflight",
        files={"file": ("学生信息.xlsx", student_workbook_with_bad_advisor, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert created.status_code == 202
    preview = wait_for_import(admin_client, created.json()["id"])
    issue = preview["issues"][0]
    assert issue["sheet"] == "学生信息"
    assert issue["row"] == 3
    assert issue["field"] == "导师工号"
    assert issue["severity"] == "error"


def test_confirm_rolls_back_every_row_when_write_fails(admin_client, valid_preview, count_students):
    before = count_students()
    admin_client.app.dependency_overrides[get_import_writer] = lambda: FailingImportWriter(fail_on_row=2)
    response = admin_client.post(f"/api/v1/imports/{valid_preview.id}/confirm")
    assert response.status_code == 500
    assert count_students() == before
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/integration/test_imports.py -q`

Expected: FAIL with missing import routes.

- [ ] **Step 3: Implement stable preview contracts**

```python
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ImportIssue:
    sheet: str
    row: int
    field: str
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class ImportPreview:
    batch_id: str
    kind: str
    creates: int
    updates: int
    unchanged: int
    issues: tuple[ImportIssue, ...]
```

The upload endpoint returns HTTP 202 with an `ImportBatch` ID. Parse and preflight in a bounded thread executor, persist progress and terminal status, and let the client poll `GET /api/v1/imports/{id}`. The uploaded file is saved under `uploads/imports/<batch-uuid>.xlsx`; database records store SHA-256, original name, size, uploader, template kind, and preview JSON. Reject macro-enabled files, files over 20 MiB, wrong sheet names, unknown columns, formulas in identity fields, and more than 20,000 data rows.

- [ ] **Step 4: Implement six templates and idempotent upserts**

Generate workbooks from code with locked header names documented in design section 7. Student and teacher imports key by business number; course and leave imports key by a normalized source fingerprint; slots key by activity/date/start/end; rooms key by campus/building/name.

For week-based course rows, require academic term code, teaching week number, weekday, and section interval, then expand to exact datetimes using `AcademicTerm.start_date` and the configured section timetable.

- [ ] **Step 5: Verify preflight, transaction, and idempotency**

Add tests for every template, duplicate rows, repeated file import, file hash mismatch between preview and confirm, wrong department, and a successful import audit record.

Run: `uv run pytest tests/integration/test_imports.py -q`

Expected: all cases pass.

- [ ] **Step 6: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/integration/test_imports.py -q
git add src/defense_grouping/imports_exports tests/fixtures/imports tests/integration/test_imports.py
git commit -m "feat: add transactional Excel import workflow"
```

---

### Task 6: Serializable Scheduling Domain, Prechecks, and Independent Validator

**Files:**
- Create: `src/defense_grouping/scheduling/domain.py`
- Create: `src/defense_grouping/scheduling/precheck.py`
- Create: `src/defense_grouping/scheduling/validator.py`
- Create: `tests/unit/scheduling/test_precheck.py`
- Create: `tests/unit/scheduling/test_validator.py`

**Interfaces:**
- Produces immutable `SchedulingInput` and `ScheduleSolution` dataclasses with primitive values and UUID strings so process workers can serialize them.
- Produces: `run_prechecks(data: SchedulingInput) -> tuple[Diagnostic, ...]`.
- Produces: `validate_solution(data, solution) -> ValidationReport` independent from solver code.

- [ ] **Step 1: Write hard-constraint validator tests**

```python
def test_validator_rejects_student_with_advisor_on_panel(simple_input, solution_factory):
    solution = solution_factory(panel_teacher_ids=("teacher-advisor",))
    report = validate_solution(simple_input, solution)
    assert not report.valid
    assert report.violations[0].code == "advisor_conflict"


def test_precheck_reports_insufficient_chairs(simple_input):
    data = simple_input.with_required_groups(3).with_chair_candidates(("teacher-1", "teacher-2"))
    diagnostics = run_prechecks(data)
    assert diagnostics[0].code == "insufficient_chairs"
    assert diagnostics[0].details == {"required": 3, "available": 2}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/unit/scheduling -q`

Expected: FAIL because scheduling domain modules are absent.

- [ ] **Step 3: Implement immutable process boundary types**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class StudentDemand:
    id: str
    advisor_id: str
    direction_ids: frozenset[str]
    available_slot_ids: frozenset[str]


@dataclass(frozen=True)
class TeacherSupply:
    id: str
    title_rank: int
    direction_ids: frozenset[str]
    available_slot_ids: frozenset[str]
    workload_limit: int


@dataclass(frozen=True)
class SchedulingInput:
    activity_id: str
    seed: int
    students: tuple[StudentDemand, ...]
    teachers: tuple[TeacherSupply, ...]
    slots: tuple["SlotSupply", ...]
    rooms: tuple["RoomSupply", ...]
    rules: "SchedulingRules"
    exceptions: tuple["ApprovedException", ...]
```

Define `GroupSolution`, `ScheduleSolution`, `Violation`, `ValidationReport`, and `Diagnostic` in the same module. No SQLAlchemy or FastAPI import is allowed in `scheduling/domain.py`.

- [ ] **Step 4: Implement deterministic prechecks and validator**

Prechecks must cover zero participants, capacity lower bound, number of chair candidates, panel supply, student with no candidate slot, teacher with no candidate slot, and direction with no eligible non-advisor teacher. The validator must check every hard constraint from design section 8.1 and emit stable codes with affected IDs.

- [ ] **Step 5: Add property tests**

Use Hypothesis to generate small assignment sets and verify that duplicate student assignment, duplicate room/slot use, teacher double-booking, capacity overflow, and unscoped exceptions are always detected.

Run: `uv run pytest tests/unit/scheduling -q`

Expected: all deterministic and property tests pass.

- [ ] **Step 6: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/unit/scheduling -q
git add src/defense_grouping/scheduling tests/unit/scheduling
git commit -m "feat: add scheduling contracts and independent validation"
```

---

### Task 7: OR-Tools CP-SAT Solver and Explainable Outcomes

**Files:**
- Create: `src/defense_grouping/scheduling/solver.py`
- Create: `tests/unit/scheduling/test_solver.py`
- Create: `tests/fixtures/scheduling/feasible_small.json`
- Create: `tests/fixtures/scheduling/infeasible_chair.json`

**Interfaces:**
- Produces: `solve(data: SchedulingInput, time_limit_seconds: float, on_progress: ProgressCallback | None = None) -> SolveOutcome`.
- `SolveOutcome.status` is `feasible`, `optimal`, `infeasible`, or `timeout`; a successful outcome contains a validator-clean solution and objective components.

- [ ] **Step 1: Write solver behavior tests**

```python
def test_solver_returns_reproducible_valid_solution(feasible_input):
    first = solve(feasible_input, time_limit_seconds=5)
    second = solve(feasible_input, time_limit_seconds=5)
    assert first.status in {"feasible", "optimal"}
    assert first.solution == second.solution
    assert validate_solution(feasible_input, first.solution).valid


def test_solver_never_uses_unapproved_advisor_exception(feasible_input):
    outcome = solve(feasible_input, time_limit_seconds=5)
    for group in outcome.solution.groups:
        advisors = {student.advisor_id for student in feasible_input.students if student.id in group.student_ids}
        assert advisors.isdisjoint(group.teacher_ids)
```

- [ ] **Step 2: Run solver tests and verify failure**

Run: `uv run pytest tests/unit/scheduling/test_solver.py -q`

Expected: FAIL because `solve` is absent.

- [ ] **Step 3: Implement CP-SAT decision variables and hard constraints**

Create Boolean variables for student-to-group, teacher-to-group, group-to-slot, group-to-room, and chair-to-group. Use linear equalities for unique assignments and `AddImplication`/reified constraints for advisor, availability, room/slot, workload, and exception scopes. Derive the exact number of groups as `ceil(student_count / students_per_group)`.

Configure deterministic solving:

```python
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = time_limit_seconds
solver.parameters.random_seed = data.seed
solver.parameters.num_search_workers = 1
```

- [ ] **Step 4: Add weighted objective components**

Represent each objective component with an integer penalty: maximum-minus-minimum student load, teacher load deviation from scaled mean, unmatched directions, non-consecutive teacher slot gaps, and used approved exceptions. Multiply by the exact rule weights and minimize the sum. Return both raw component values and weighted total.

- [ ] **Step 5: Validate every returned solution and explain failure**

Call the independent validator before returning success; raise an internal consistency error if it finds a violation. For infeasible inputs, combine precheck diagnostics with CP-SAT assumption literals for advisor, availability, panel, room, and capacity families, and map the infeasible assumption set to stable Chinese diagnostics.

Run: `uv run pytest tests/unit/scheduling/test_solver.py tests/unit/scheduling/test_validator.py -q`

Expected: all cases pass, including fixtures and seed reproducibility.

- [ ] **Step 6: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/unit/scheduling -q
git add src/defense_grouping/scheduling/solver.py tests/unit/scheduling/test_solver.py tests/fixtures/scheduling
git commit -m "feat: generate explainable CP-SAT defense schedules"
```

---

### Task 8: Persistent Jobs, Plan Versions, Manual Adjustment, and Publication

**Files:**
- Create: `src/defense_grouping/scheduling/executor.py`
- Create: `src/defense_grouping/scheduling/service.py`
- Create: `src/defense_grouping/scheduling/routes.py`
- Modify: `src/defense_grouping/api/main.py`
- Create: `tests/integration/test_schedule_jobs.py`
- Create: `tests/integration/test_plan_lifecycle.py`

**Interfaces:**
- Produces: `TaskExecutor.submit(job_id: UUID, payload: SchedulingInput) -> None`.
- Produces API to create/poll/cancel jobs; list/compare/copy plans; adjust assignments; validate, publish, withdraw, and archive plans.
- Produces teacher API: list the current teacher's published schedule and confirm one assignment.
- Consumes: solver and validator from Tasks 6–7.

- [ ] **Step 1: Write job and immutable publication tests**

```python
def test_schedule_job_creates_new_ready_plan(admin_client, configured_activity):
    created = admin_client.post(
        f"/api/v1/activities/{configured_activity.id}/schedule-jobs",
        json={"seed": 20260918, "time_limit_seconds": 30},
        headers={"Idempotency-Key": "activity-1-run-1"},
    )
    job = wait_for_job(admin_client, created.json()["id"])
    assert job["status"] == "succeeded"
    plan = admin_client.get(f"/api/v1/plans/{job['plan_id']}").json()
    assert plan["status"] == "ready"


def test_published_plan_cannot_be_mutated(admin_client, published_plan):
    response = admin_client.patch(
        f"/api/v1/plans/{published_plan.id}/groups/{published_plan.group_id}",
        json={"room_id": str(published_plan.other_room_id), "version": published_plan.version},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "published_plan_immutable"
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `uv run pytest tests/integration/test_schedule_jobs.py tests/integration/test_plan_lifecycle.py -q`

Expected: FAIL because task and plan routes are absent.

- [ ] **Step 3: Implement the local executor**

Use one `ProcessPoolExecutor` for CP-SAT work. Build `SchedulingInput` and persist job state before submitting. Worker processes return only `SolveOutcome`; the API process writes plans and progress. On application startup, mark jobs left in `running` as `failed` with code `worker_interrupted`.

Do not pass database sessions, ORM objects, loggers, or callbacks across the process boundary.

- [ ] **Step 4: Implement plan versioning and adjustments**

Copying a plan creates `version_number = max + 1`, `source_plan_id`, and draft group/assignment rows in one transaction. Manual adjustment accepts the client's optimistic-lock version, modifies only the draft, validates the whole affected plan, and rolls back on any unapproved hard conflict.

Plan comparison returns assignment moves, teacher changes, slot/room changes, objective deltas, and exception-use deltas.

- [ ] **Step 5: Implement publication state machine**

Allowed transitions are:

```text
draft -> validating -> ready
ready -> published
published -> archived
ready -> draft
```

Publishing executes the independent validator in the same transaction, archives the previously published plan for that activity, publishes the selected plan, and records an audit event. A failed validation restores the plan to draft.

- [ ] **Step 6: Pass job, idempotency, conflict, and lifecycle tests**

Test progress polling, duplicate idempotency key, worker exception, cancellation before start, timeout with a feasible incumbent, optimistic lock conflict, plan comparison, copy-on-change, publication rollback, teacher schedule isolation, and idempotent teacher confirmation.

Run: `uv run pytest tests/integration/test_schedule_jobs.py tests/integration/test_plan_lifecycle.py -q`

Expected: all cases pass.

- [ ] **Step 7: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/integration/test_schedule_jobs.py tests/integration/test_plan_lifecycle.py -q
git add src/defense_grouping/scheduling src/defense_grouping/api tests/integration
git commit -m "feat: add asynchronous jobs and governed plan lifecycle"
```

---

### Task 9: Exception Approval, Audit, Exports, and Local Backup

**Files:**
- Create: `src/defense_grouping/governance/audit.py`
- Create: `src/defense_grouping/governance/approval_service.py`
- Create: `src/defense_grouping/governance/routes.py`
- Create: `src/defense_grouping/imports_exports/export_service.py`
- Modify: `src/defense_grouping/imports_exports/routes.py`
- Modify: `src/defense_grouping/auth/service.py`
- Modify: `src/defense_grouping/master_data/service.py`
- Modify: `src/defense_grouping/imports_exports/import_service.py`
- Modify: `src/defense_grouping/scheduling/service.py`
- Modify: `src/defense_grouping/cli.py`
- Create: `tests/integration/test_approvals.py`
- Create: `tests/integration/test_audit_and_export.py`
- Create: `tests/integration/test_backup_restore.py`

**Interfaces:**
- Produces four-eyes exception workflow and append-only audit query API.
- Produces `.xlsx` export for published plans.
- Produces CLI: `backup`, `restore`, and `seed-demo`.

- [ ] **Step 1: Write four-eyes and export consistency tests**

```python
def test_requester_cannot_approve_own_exception(admin_client, own_exception):
    response = admin_client.post(f"/api/v1/exceptions/{own_exception.id}/approve")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_approval_forbidden"


def test_export_matches_published_plan(admin_client, published_plan):
    workbook = load_workbook(admin_client.get(f"/api/v1/plans/{published_plan.id}/export").content)
    assert workbook["分组总表"]["A2"].value == published_plan.group_code
    assert workbook["方案信息"]["B2"].value == published_plan.version_number
```

- [ ] **Step 2: Run governance tests and verify failure**

Run: `uv run pytest tests/integration/test_approvals.py tests/integration/test_audit_and_export.py tests/integration/test_backup_restore.py -q`

Expected: FAIL because governance routes and exporters are absent.

- [ ] **Step 3: Implement exact-scope exception approval**

Use this command contract:

```python
class ExceptionRequest(BaseModel):
    activity_id: UUID
    constraint_code: Literal["advisor_conflict", "course_conflict", "leave_conflict", "workload_limit"]
    subject_type: Literal["teacher_student", "person_slot", "teacher"]
    teacher_id: UUID | None = None
    student_id: UUID | None = None
    person_id: UUID | None = None
    slot_id: UUID | None = None
    reason: str = Field(min_length=10, max_length=1000)
    expires_at: datetime
```

Validate required ID combinations for each constraint code. The requester and approver must be different active users with access to the activity department. Revocation affects only future schedule validation; published plans retain the historical approval snapshot.

- [ ] **Step 4: Add append-only audit middleware and services**

Record actor, action, object type/ID, request ID, UTC time, and redacted before/after summaries. Refuse update/delete operations on `audit_logs` at the repository layer. Redact fields named `password`, `password_hash`, `token`, `refresh_token`, and `jwt_secret` recursively. Instrument the existing auth, master-data, import, scheduling, plan-publication, and teacher-confirmation services in this task so every sensitive operation uses the same audit writer.

- [ ] **Step 5: Implement Excel export and SQLite backup/restore**

Export sheets named `分组总表`, `教师安排`, `学生安排`, `教室时段`, `冲突与例外`, and `方案信息`. Use the persisted published plan, not a new solver snapshot.

For SQLite backup, use the SQLite online backup API to create a timestamped file and SHA-256 manifest. Restore verifies the hash and schema revision, creates a pre-restore backup, replaces the database only while the API is stopped, then runs a read-only integrity check.

- [ ] **Step 6: Pass governance and recovery tests**

Test approve/reject/revoke transitions, self-approval, expired exception, audit redaction, export rows, backup hash failure, and successful round-trip restore.

Run: `uv run pytest tests/integration/test_approvals.py tests/integration/test_audit_and_export.py tests/integration/test_backup_restore.py -q`

Expected: all cases pass.

- [ ] **Step 7: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/integration/test_approvals.py tests/integration/test_audit_and_export.py tests/integration/test_backup_restore.py -q
git add src/defense_grouping/governance src/defense_grouping/imports_exports src/defense_grouping/cli.py tests/integration
git commit -m "feat: add approvals auditing exports and recovery"
```

---

### Task 10: Flet Client Shell, Authentication, Routing, and API Error Handling

**Files:**
- Create: `main.py`
- Create: `src/defense_grouping/client/api_client.py`
- Create: `src/defense_grouping/client/session.py`
- Create: `src/defense_grouping/client/theme.py`
- Create: `src/defense_grouping/client/router.py`
- Create: `src/defense_grouping/client/main.py`
- Create: `src/defense_grouping/client/components/app_shell.py`
- Create: `src/defense_grouping/client/components/feedback.py`
- Create: `src/defense_grouping/client/views/login.py`
- Create: `src/defense_grouping/client/views/dashboard.py`
- Create: `tests/client/test_api_client.py`
- Create: `tests/client/test_role_navigation.py`

**Interfaces:**
- Produces: `ApiClient`, `SessionState`, declarative Flet router, role-aware navigation, login, first-password-change, and dashboard views.
- Consumes only `/api/v1`; no client module imports `defense_grouping.models` or `defense_grouping.db`.

- [ ] **Step 1: Write client boundary and role-navigation tests**

```python
def test_client_package_does_not_import_database_modules():
    source = Path("src/defense_grouping/client").read_text() if Path("src/defense_grouping/client").is_file() else "\n".join(
        path.read_text() for path in Path("src/defense_grouping/client").rglob("*.py")
    )
    assert "defense_grouping.db" not in source
    assert "defense_grouping.models" not in source


def test_teacher_navigation_is_read_only():
    items = navigation_for({"teacher"})
    assert [item.route for item in items] == ["/dashboard", "/my-schedule"]
```

- [ ] **Step 2: Run client tests and verify failure**

Run: `uv run pytest tests/client/test_api_client.py tests/client/test_role_navigation.py -q`

Expected: FAIL because client modules are absent.

- [ ] **Step 3: Implement async API client and session refresh**

```python
from typing import Any


class ApiError(Exception):
    def __init__(self, code: str, message: str, request_id: str, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.fields = fields or {}


class ApiClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=30)
        self._access_token: str | None = None

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}))
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = await self._client.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            payload = response.json()["error"]
            raise ApiError(payload["code"], payload["message"], payload["request_id"], payload.get("fields"))
        return response.json()
```

Retry once after a 401 only when a refresh token is present and refresh succeeds. Keep access tokens in memory. Use OS keyring for desktop refresh tokens and server-side Flet session storage for Web; clearing either store logs the user out.

- [ ] **Step 4: Implement Flet declarative router and shell**

Use Flet 1.x `ft.Router`, nested routes, and one route table derived from `SessionState`. Rebuild authorized routes after login. Unknown routes show a Chinese 404 view; unauthenticated routes redirect to `/login`; forbidden routes show a 403 view without briefly rendering protected data.

The shell includes left navigation, current activity selector, task indicator, account menu, responsive breakpoint, and a content outlet. The root `main.py` is a combined desktop launcher: when `DEFENSE_API_URL` is absent and local health is unavailable, it starts the packaged FastAPI sidecar, waits for health, then launches Flet. Web deployment requires an explicit API URL and never starts a per-session sidecar.

- [ ] **Step 5: Pass login, refresh, and navigation tests**

Test successful login, first password change, refresh-once behavior, logout clearing stores, teacher navigation, academic-admin navigation, system-admin navigation, API field errors, network timeout, and request-ID display.

Run: `uv run pytest tests/client/test_api_client.py tests/client/test_role_navigation.py -q`

Expected: all cases pass.

- [ ] **Step 6: Run desktop and Web smoke commands**

Run:

```bash
uv run flet run main.py
uv run flet run --web main.py
```

Expected: both modes display the login page and can reach the local health endpoint.

- [ ] **Step 7: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/client -q
git add main.py src/defense_grouping/client tests/client
git commit -m "feat: add secure role-aware Flet application shell"
```

---

### Task 11: Flet Administrative Workflows and Teacher Portal

**Files:**
- Create: `src/defense_grouping/client/components/data_table.py`
- Create: `src/defense_grouping/client/components/task_progress.py`
- Create: `src/defense_grouping/client/views/master_data.py`
- Create: `src/defense_grouping/client/views/availability.py`
- Create: `src/defense_grouping/client/views/imports.py`
- Create: `src/defense_grouping/client/views/activity_wizard.py`
- Create: `src/defense_grouping/client/views/scheduling.py`
- Create: `src/defense_grouping/client/views/plans.py`
- Create: `src/defense_grouping/client/views/approvals.py`
- Create: `src/defense_grouping/client/views/audit.py`
- Create: `src/defense_grouping/client/views/system_admin.py`
- Create: `src/defense_grouping/client/views/my_schedule.py`
- Modify: `src/defense_grouping/client/router.py`
- Create: `tests/client/test_workflows.py`
- Create: `tests/e2e/test_admin_to_teacher_flow.py`

**Interfaces:**
- Produces all pages listed in design section 11.
- Consumes the stable API client from Task 10 and never duplicates backend business validation.

- [ ] **Step 1: Write the complete workflow test**

```python
async def test_admin_can_import_schedule_publish_and_teacher_confirm(app_harness):
    await app_harness.login("academic-admin", "Admin Password 2026")
    await app_harness.import_fixture_bundle("tests/fixtures/demo/valid")
    activity_id = await app_harness.create_activity_from_fixture("tests/fixtures/demo/activity.json")
    job = await app_harness.start_schedule(activity_id, seed=20260918)
    await app_harness.wait_until_job_succeeds(job.id)
    plan = await app_harness.open_job_plan(job.id)
    await app_harness.publish(plan.id)
    await app_harness.logout()
    await app_harness.login("teacher-001", "Teacher Password 2026")
    assert await app_harness.my_schedule_contains(activity_id)
    await app_harness.confirm_my_schedule(activity_id)
```

- [ ] **Step 2: Run workflow tests and verify failure**

Run: `uv run pytest tests/client/test_workflows.py tests/e2e/test_admin_to_teacher_flow.py -q`

Expected: FAIL because workflow views and harness actions are absent.

- [ ] **Step 3: Implement reusable admin tables and form behavior**

The table component must expose search, filters, deterministic sort, paging, loading, empty, error, and batch-selection states. Forms bind API field errors to controls. Dirty forms use Flet route pop confirmation so browser Back, system Back, and navigation clicks cannot silently discard edits.

- [ ] **Step 4: Implement data, availability, import, and activity pages**

Master data pages share table infrastructure but use explicit field schemas. Availability presents list and calendar views. Import shows template download, upload progress, create/update/unchanged counts, row/cell issues, and a separate confirmation action. The activity wizard has five validated steps: scope, panel rules, time slots, rooms, and solver parameters.

- [ ] **Step 5: Implement scheduling, plan, approval, and audit pages**

Scheduling polls persisted jobs with exponential intervals from 1 to 5 seconds and stops on terminal state. Plan detail shows groups, objective components, diagnostics, used exceptions, and candidate lists for manual adjustment. Version comparison shows student moves, teacher changes, resource changes, and score deltas. Approval prevents the requester from seeing an enabled approve action. Audit filters by actor, action, object, and time.

- [ ] **Step 6: Implement teacher read-only portal**

Show only published arrangements involving the logged-in teacher, including group, students, date, time, room, fellow panel members, exception marker, and confirmation state. The only write action is confirmation.

- [ ] **Step 7: Pass client and end-to-end workflows**

Run: `uv run pytest tests/client/test_workflows.py tests/e2e/test_admin_to_teacher_flow.py -q`

Expected: all cases pass for system administrator, academic administrator, and teacher roles.

- [ ] **Step 8: Run quality gates and commit**

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/client tests/e2e -q
git add src/defense_grouping/client tests/client tests/e2e tests/fixtures/demo
git commit -m "feat: complete Flet academic scheduling workflows"
```

---

### Task 12: Performance, PostgreSQL Compatibility, CI, Packaging, and Operations Docs

**Files:**
- Create: `tests/performance/generate_dataset.py`
- Create: `tests/performance/test_department_scale.py`
- Create: `tests/integration/test_postgres.py`
- Create: `.github/workflows/ci.yml`
- Create: `docs/operations/local-development.md`
- Create: `docs/operations/desktop-packaging.md`
- Create: `docs/operations/server-migration.md`
- Create: `docs/operations/backup-recovery.md`
- Modify: `README.md`

**Interfaces:**
- Produces deterministic 500-student/50-teacher/20-group performance fixture.
- Produces CI evidence for lint, typing, unit, integration, PostgreSQL, and build smoke tests.
- Produces exact local startup, desktop build, server migration, and recovery instructions.

- [ ] **Step 1: Write the performance acceptance test**

```python
def run_solver_fixture(performance_input, output):
    output.put(solve(performance_input, time_limit_seconds=60))


def test_department_scale_solver_finishes_within_budget(performance_input):
    import multiprocessing
    import time
    import psutil

    output = multiprocessing.Queue()
    worker = multiprocessing.Process(target=run_solver_fixture, args=(performance_input, output))
    started = time.perf_counter()
    worker.start()
    process = psutil.Process(worker.pid)
    peak_rss = 0
    while worker.is_alive():
        peak_rss = max(peak_rss, process.memory_info().rss)
        time.sleep(0.05)
    worker.join()
    elapsed = time.perf_counter() - started
    outcome = output.get_nowait()
    assert worker.exitcode == 0
    assert outcome.status in {"feasible", "optimal"}
    assert elapsed <= 60
    assert peak_rss < 2 * 1024 * 1024 * 1024
    assert validate_solution(performance_input, outcome.solution).valid
```

- [ ] **Step 2: Build deterministic synthetic data**

Generate exactly 500 students, 50 teachers, 20 groups, 8 slots, and 24 rooms. Guarantee feasibility by constructing hidden valid assignments first, then derive availability, advisors, directions, and capacities from them. Shuffle visible input with seed `20260918`; do not feed hidden assignments to the solver.

- [ ] **Step 3: Verify PostgreSQL migrations and core flow**

Using `testcontainers.postgres.PostgresContainer`, run Alembic to head and execute login, master-data creation, import, activity creation, one small solve, publication, and export. Assert no SQLite-only SQL or type behavior is used.

- [ ] **Step 4: Add CI jobs**

Configure Linux CI on Python 3.12 and 3.14. Run `uv sync --locked`, Ruff, mypy, unit tests, SQLite integration tests, PostgreSQL integration tests, client tests, and `flet build web --yes`. Run the 500-student performance test manually and nightly, not on every pull request.

- [ ] **Step 5: Write exact operating guides**

Document:

```bash
uv sync --locked
uv run alembic upgrade head
uv run defense-grouping init-admin --username admin
uv run python scripts/dev.py
uv run pytest -q
uv run flet pack main.py --name defense-grouping-system
uv run flet build web
```

The server guide must include PostgreSQL URL format, Alembic migration, reverse-proxy HTTPS, CORS allowlist, task-executor replacement boundary, backup schedule, and rollback procedure. State that desktop artifacts must be built on each target OS because Flet/PyInstaller is not a cross-compiler.

- [ ] **Step 6: Run the full completion audit**

Run:

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/unit tests/integration tests/client tests/e2e -q
uv run pytest tests/performance/test_department_scale.py -q -m performance
uv run alembic check
uv run flet build web --yes
git status --short
```

Expected: all checks pass, the performance budget is met, the Web build succeeds, and only intentional files are modified.

- [ ] **Step 7: Commit**

```bash
git add .github README.md docs/operations tests/performance tests/integration/test_postgres.py
git commit -m "docs: complete deployment and performance acceptance"
```

---

## Completion Review

Before declaring the project complete, map every item in design section 16 to a test, command output, generated artifact, or manual smoke record. Record the final evidence in `docs/verification/first-release.md`, including exact commit, operating system, Python version, database versions, commands, timings, memory figures, desktop/Web screenshots, and any approved deviations. No checklist item may be marked complete from code inspection alone when a runnable verification is available.

## Official References Checked for This Plan

- Flet routing: <https://flet.dev/docs/cookbook/navigation-and-routing/>
- Flet packaging: <https://flet.dev/docs/publish/using-pyinstaller/>
- FastAPI OAuth2/JWT: <https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/>
- SQLAlchemy asyncio: <https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html>
- OR-Tools scheduling: <https://developers.google.com/optimization/scheduling/employee_scheduling>
