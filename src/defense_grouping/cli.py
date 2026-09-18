import asyncio
import secrets
from typing import Annotated

import typer
from sqlalchemy import select

from defense_grouping import __version__
from defense_grouping.auth.security import hash_password
from defense_grouping.auth.service import normalize_username
from defense_grouping.config import get_settings
from defense_grouping.db.session import Database
from defense_grouping.models.identity import Role, RoleAssignment, User

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


if __name__ == "__main__":
    app()
