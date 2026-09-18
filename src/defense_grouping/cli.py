import asyncio
import secrets
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from defense_grouping import __version__
from defense_grouping.auth.security import hash_password
from defense_grouping.auth.service import normalize_username
from defense_grouping.config import get_settings
from defense_grouping.db.base import Base
from defense_grouping.db.session import Database
from defense_grouping.governance.backup import (
    create_backup,
    current_schema_head,
    restore_backup,
)
from defense_grouping.models.identity import Role, RoleAssignment, User
from defense_grouping.models.master import Department

app = typer.Typer(
    name="defense-grouping",
    help="答辩分组系统管理命令。",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """答辩分组系统命令行入口。"""


@app.command()
def version(
    short: Annotated[bool, typer.Option("--short", help="仅输出版本号。")] = False,
) -> None:
    """显示当前程序版本。"""
    typer.echo(__version__ if short else f"defense-grouping-system {__version__}")


@app.command("init-admin")
def init_admin(
    username: Annotated[str, typer.Option(help="初始化系统管理员用户名。")] = "admin",
    password: Annotated[
        str | None,
        typer.Option(help="临时密码；省略时安全随机生成。", hide_input=True),
    ] = None,
) -> None:
    """创建首个系统管理员，已有活动管理员不会被重置。"""

    async def create() -> tuple[str, bool]:
        settings = get_settings()
        database = Database(settings.database_url)
        try:
            async with database.session() as session:
                normalized = normalize_username(username)
                existing = await session.scalar(select(User).where(User.username == normalized))
                if existing is not None:
                    system_role = await session.scalar(
                        select(RoleAssignment.id).where(
                            RoleAssignment.user_id == existing.id,
                            RoleAssignment.role == Role.SYSTEM_ADMIN,
                        )
                    )
                    if existing.is_active and system_role is not None:
                        return "管理员已存在，未修改密码。", False
                    raise typer.BadParameter("用户名已被非活动或非管理员账号占用。")

                temporary_password = password or secrets.token_urlsafe(18)
                user = User(
                    username=normalized,
                    password_hash=hash_password(temporary_password),
                    is_active=True,
                    must_change_password=True,
                )
                session.add(user)
                await session.flush()
                session.add(
                    RoleAssignment(
                        user_id=user.id,
                        role=Role.SYSTEM_ADMIN,
                        department_id=None,
                        can_approve_exceptions=False,
                    )
                )
                await session.commit()
                return temporary_password, True
        finally:
            await database.dispose()

    result, created = asyncio.run(create())
    if created:
        typer.echo(f"系统管理员已创建。临时密码（仅显示一次）：{result}")
    else:
        typer.echo(result)


def _sqlite_database_path() -> Path:
    settings = get_settings()
    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise typer.BadParameter("该命令只支持文件形式的 SQLite 数据库。")
    return Path(url.database).resolve()


@app.command("backup")
def backup_command(
    output_dir: Annotated[
        Path | None,
        typer.Option(help="备份目录；默认使用 storage/backups。"),
    ] = None,
) -> None:
    """使用 SQLite 在线备份 API 创建数据库备份和 SHA-256 manifest。"""
    settings = get_settings()
    artifact = create_backup(
        _sqlite_database_path(),
        output_dir or settings.storage_dir / "backups",
    )
    typer.echo(f"备份完成：{artifact.database_path}")
    typer.echo(f"Manifest：{artifact.manifest_path}")


@app.command("restore")
def restore_command(
    backup_path: Annotated[Path, typer.Argument(help="要恢复的 .sqlite3 备份文件。")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="确认 API 已停止并执行恢复。"),
    ] = False,
) -> None:
    """校验备份后恢复 SQLite；恢复前自动保存当前数据库。"""
    if not yes:
        raise typer.BadParameter("恢复会替换当前数据库；停止 API 后使用 --yes 明确确认。")
    settings = get_settings()
    result = restore_backup(
        _sqlite_database_path(),
        backup_path,
        backup_dir=settings.storage_dir / "backups",
        expected_revision=current_schema_head(),
    )
    typer.echo(f"恢复完成，完整性检查：{result.integrity_check}")
    typer.echo(f"恢复前备份：{result.pre_restore_backup.database_path}")


@app.command("seed-demo")
def seed_demo(
    database_path: Annotated[
        Path,
        typer.Option(help="独立演示数据库路径，不得指向正式数据库。"),
    ] = Path("data/demo/defense_grouping_demo.db"),
) -> None:
    """幂等创建与正式数据库分离的最小演示数据。"""
    target = database_path.resolve()
    if target == _sqlite_database_path():
        raise typer.BadParameter("演示数据库不能与当前正式数据库相同。")
    target.parent.mkdir(parents=True, exist_ok=True)

    async def seed() -> bool:
        database = Database(f"sqlite+aiosqlite:///{target}")
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with database.session() as session:
                existing = await session.scalar(
                    select(Department).where(Department.code == "DEMO")
                )
                if existing is not None:
                    return False
                department = Department(code="DEMO", name="演示学院", is_active=True)
                user = User(
                    username="demo-admin",
                    password_hash=hash_password("Demo Admin Password 2026"),
                    is_active=True,
                    must_change_password=True,
                )
                session.add_all([department, user])
                await session.flush()
                session.add(
                    RoleAssignment(
                        user_id=user.id,
                        role=Role.ACADEMIC_ADMIN,
                        department_id=department.id,
                        can_approve_exceptions=True,
                    )
                )
                await session.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS alembic_version "
                        "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                    )
                )
                await session.execute(text("DELETE FROM alembic_version"))
                await session.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                    {"revision": current_schema_head()},
                )
                await session.commit()
                return True
        finally:
            await database.dispose()

    created = asyncio.run(seed())
    typer.echo(f"演示数据库{'已创建' if created else '已存在'}：{target}")


if __name__ == "__main__":
    app()
