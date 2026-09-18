from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

from defense_grouping.client.router import navigation_for
from defense_grouping.client.session import SessionState

LogoutHandler = Callable[[], Awaitable[None]]


def app_shell(
    page: ft.Page,
    session: SessionState,
    content: ft.Control,
    *,
    on_logout: LogoutHandler,
    task_running: bool = False,
) -> ft.Control:
    def navigation_handler(route: str) -> Callable[[], Awaitable[None]]:
        async def navigate() -> None:
            await page.push_route(route)

        return navigate

    navigation = ft.Column(
        controls=[
            ft.Text("答辩分组系统", size=20, weight=ft.FontWeight.BOLD),
            *[
                ft.Button(
                    item.label,
                    icon=item.icon,
                    on_click=navigation_handler(item.route),
                    width=210,
                )
                for item in navigation_for(session.roles)
            ],
        ],
        spacing=6,
    )
    task_indicator = ft.Row(
        controls=[
            ft.ProgressRing(width=18, height=18, stroke_width=2),
            ft.Text("任务运行中"),
        ],
        visible=task_running,
        tight=True,
    )
    account_menu = ft.PopupMenuButton(
        content=ft.Row(
            controls=[ft.Icon(ft.Icons.ACCOUNT_CIRCLE), ft.Text(session.username or "用户")],
            tight=True,
        ),
        items=[
            ft.PopupMenuItem(content="退出登录", icon=ft.Icons.LOGOUT, on_click=on_logout),
        ],
    )
    header = ft.Row(
        controls=[
            ft.Dropdown(
                label="当前活动",
                hint_text="未选择活动",
                width=280,
                disabled=True,
            ),
            task_indicator,
            account_menu,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    return ft.ResponsiveRow(
        controls=[
            ft.Container(
                content=navigation,
                padding=16,
                bgcolor=ft.Colors.BLUE_GREY_50,
                col={"xs": 12, "md": 3, "lg": 2},
            ),
            ft.Container(
                content=ft.Column(controls=[header, ft.Divider(), content], expand=True),
                padding=20,
                col={"xs": 12, "md": 9, "lg": 10},
            ),
        ],
        expand=True,
    )
