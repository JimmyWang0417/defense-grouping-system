from __future__ import annotations

from collections.abc import Callable

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.feedback import error_banner
from defense_grouping.client.session import SessionState

Rerender = Callable[[], None]


def replace_session(target: SessionState, source: SessionState) -> None:
    target.user_id = source.user_id
    target.username = source.username
    target.roles = source.roles
    target.department_ids = source.department_ids
    target.must_change_password = source.must_change_password
    target.selected_activity_id = source.selected_activity_id


def login_view(
    page: ft.Page,
    client: ApiClient,
    session: SessionState,
    rerender: Rerender,
) -> ft.Control:
    username = ft.TextField(label="用户名", autofocus=True, width=360)
    password = ft.TextField(
        label="密码",
        password=True,
        can_reveal_password=True,
        width=360,
    )
    feedback = ft.Column()

    async def submit() -> None:
        username.error = None
        password.error = None
        feedback.controls.clear()
        submitted_username = username.value.strip() if isinstance(username.value, str) else ""
        submitted_password = password.value if isinstance(password.value, str) else ""
        if not submitted_username:
            username.error = "请输入用户名"
        if not submitted_password:
            password.error = "请输入密码"
        if username.error is not None or password.error is not None:
            page.update(username, password, feedback)
            return
        try:
            authenticated = await client.login(submitted_username, submitted_password)
        except ApiError as error:
            username.error = error.fields.get("username")
            password.error = error.fields.get("password")
            feedback.controls.append(error_banner(error))
            page.update(username, password, feedback)
            return
        replace_session(session, authenticated)
        destination = "/change-password" if session.must_change_password else "/dashboard"
        page.navigate(destination)

    password.on_submit = submit
    return ft.Container(
        content=ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("答辩分组系统", size=30, weight=ft.FontWeight.BOLD),
                        ft.Text("使用学校分配的账号登录"),
                        username,
                        password,
                        feedback,
                        ft.Button("登录", icon=ft.Icons.LOGIN, on_click=submit, width=360),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=32,
            ),
            width=440,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
        padding=24,
    )


def change_password_view(
    page: ft.Page,
    client: ApiClient,
    session: SessionState,
    rerender: Rerender,
) -> ft.Control:
    current_password = ft.TextField(label="当前临时密码", password=True, width=400)
    new_password = ft.TextField(
        label="新密码（至少 12 位）",
        password=True,
        can_reveal_password=True,
        width=400,
    )
    confirmation = ft.TextField(label="确认新密码", password=True, width=400)
    feedback = ft.Column()

    async def submit() -> None:
        feedback.controls.clear()
        confirmation.error = None
        submitted_current = (
            current_password.value if isinstance(current_password.value, str) else ""
        )
        submitted_new = new_password.value if isinstance(new_password.value, str) else ""
        submitted_confirmation = confirmation.value if isinstance(confirmation.value, str) else ""
        if submitted_new != submitted_confirmation:
            confirmation.error = "两次输入的新密码不一致"
            page.update(current_password, new_password, confirmation, feedback)
            return
        try:
            authenticated = await client.change_password(
                submitted_current,
                submitted_new,
            )
        except ApiError as error:
            feedback.controls.append(error_banner(error))
            page.update(current_password, new_password, confirmation, feedback)
            return
        replace_session(session, authenticated)
        page.navigate("/dashboard")

    return ft.Container(
        content=ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("首次登录必须修改密码", size=26, weight=ft.FontWeight.BOLD),
                        ft.Text("修改成功后，旧的登录令牌会立即失效。"),
                        current_password,
                        new_password,
                        confirmation,
                        feedback,
                        ft.Button("保存新密码", icon=ft.Icons.PASSWORD, on_click=submit),
                    ]
                ),
                padding=32,
            ),
            width=480,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
        padding=24,
    )
