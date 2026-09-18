from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_initial_migration_creates_required_tables(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names())
    assert {
        "users",
        "role_assignments",
        "departments",
        "majors",
        "directions",
        "teachers",
        "students",
        "academic_terms",
        "course_occupancies",
        "leave_records",
        "rooms",
        "defense_activities",
        "defense_slots",
        "activity_rooms",
        "activity_rule_sets",
        "schedule_jobs",
        "schedule_plans",
        "defense_groups",
        "panel_assignments",
        "student_assignments",
        "constraint_exceptions",
        "teacher_confirmations",
        "import_batches",
        "audit_logs",
        "refresh_tokens",
    } <= tables
