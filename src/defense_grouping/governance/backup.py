from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


class BackupIntegrityError(RuntimeError):
    """Raised before restore when a backup cannot be trusted."""


@dataclass(frozen=True)
class BackupArtifact:
    database_path: Path
    manifest_path: Path
    sha256: str
    schema_revision: str


@dataclass(frozen=True)
class RestoreResult:
    pre_restore_backup: BackupArtifact
    integrity_check: str


def current_schema_head(config_path: Path = Path("alembic.ini")) -> str:
    configuration = Config(str(config_path))
    head = ScriptDirectory.from_config(configuration).get_current_head()
    if head is None:
        raise BackupIntegrityError("Alembic migration head 不存在")
    return head


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inspect_database(path: Path) -> tuple[str, str]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            revision_row = connection.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupIntegrityError("SQLite 备份无法读取") from exc
    if integrity != "ok":
        raise BackupIntegrityError(f"SQLite integrity_check failed: {integrity}")
    if revision_row is None:
        raise BackupIntegrityError("备份缺少 Alembic schema revision")
    return integrity, str(revision_row[0])


def _manifest_path(database_path: Path) -> Path:
    return database_path.with_suffix(".manifest.json")


def create_backup(database_path: Path, backup_dir: Path) -> BackupArtifact:
    source = database_path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    _integrity, revision = _inspect_database(source)
    destination_dir = backup_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"{source.stem}-{timestamp}.sqlite3"
    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as target:
        source_connection.backup(target)
    _inspect_database(destination)
    digest = _sha256(destination)
    manifest_path = _manifest_path(destination)
    manifest_path.write_text(
        json.dumps(
            {
                "database": destination.name,
                "sha256": digest,
                "schema_revision": revision,
                "created_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return BackupArtifact(destination, manifest_path, digest, revision)


def restore_backup(
    database_path: Path,
    backup_path: Path,
    *,
    backup_dir: Path,
    expected_revision: str,
) -> RestoreResult:
    target = database_path.resolve()
    source = backup_path.resolve()
    manifest_path = _manifest_path(source)
    if not source.is_file() or not manifest_path.is_file():
        raise BackupIntegrityError("备份文件或 manifest 不存在")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupIntegrityError("备份 manifest 无法读取") from exc
    expected_hash = manifest.get("sha256")
    if not isinstance(expected_hash, str) or _sha256(source) != expected_hash:
        raise BackupIntegrityError("备份 SHA-256 校验失败")
    integrity, revision = _inspect_database(source)
    if revision != expected_revision or manifest.get("schema_revision") != expected_revision:
        raise BackupIntegrityError("备份 schema revision 与当前程序不兼容")
    pre_restore = create_backup(target, backup_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".restore",
        dir=target.parent,
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(source) as source_connection, sqlite3.connect(temporary) as restored:
            source_connection.backup(restored)
        _inspect_database(temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    final_integrity, _final_revision = _inspect_database(target)
    return RestoreResult(pre_restore, final_integrity or integrity)
