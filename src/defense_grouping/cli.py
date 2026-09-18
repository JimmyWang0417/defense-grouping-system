from typing import Annotated

import typer

from defense_grouping import __version__

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


if __name__ == "__main__":
    app()
