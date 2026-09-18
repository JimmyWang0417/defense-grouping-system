import json
import sqlite3
from pathlib import Path

import pytest

from defense_grouping.governance.backup import BackupIntegrityError, create_backup, restore_backup


def create_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0001_initial_schema')")
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))


def marker(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT value FROM marker").fetchone()[0])


def test_sqlite_backup_restore_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    backups = tmp_path / "backups"
    create_database(database, "before")
    artifact = create_backup(database, backups)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE marker SET value = 'after'")

    result = restore_backup(
        database,
        artifact.database_path,
        backup_dir=backups,
        expected_revision="0001_initial_schema",
    )

    assert marker(database) == "before"
    assert result.pre_restore_backup.database_path.is_file()
    assert result.integrity_check == "ok"


def test_restore_rejects_hash_mismatch_without_touching_database(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    backups = tmp_path / "backups"
    create_database(database, "original")
    artifact = create_backup(database, backups)
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    artifact.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="SHA-256"):
        restore_backup(
            database,
            artifact.database_path,
            backup_dir=backups,
            expected_revision="0001_initial_schema",
        )

    assert marker(database) == "original"
