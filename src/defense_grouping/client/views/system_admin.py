from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    set_busy,
    update_control,
)


class SystemAdminWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list_users(self) -> list[dict[str, Any]]:
        return await self.client.request_list("GET", "/api/v1/users")

    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.request("POST", "/api/v1/users", json=payload)

    async def set_status(self, user_id: str, active: bool) -> dict[str, Any]:
        return await self.client.request(
            "PATCH", f"/api/v1/users/{user_id}/status", json={"is_active": active}
        )

    async def replace_roles(self, user_id: str, roles: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.client.request(
            "PUT", f"/api/v1/users/{user_id}/roles", json={"roles": roles}
        )

    async def reset_password(
        self, user_id: str, temporary_password: str | None = None
    ) -> dict[str, Any]:
        return await self.client.request(
            "POST",
            f"/api/v1/users/{user_id}/reset-password",
            json={"temporary_password": temporary_password},
        )


class SystemAdminView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = SystemAdminWorkflow(client)
        self.rows: list[dict[str, Any]] = []
        self.selected: dict[str, Any] | None = None
        self.username = ft.TextField(label="用户名", key="system.username")
        self.temporary_password = ft.TextField(
            label="临时密码（至少 12 位；重置时可空）",
            password=True,
            can_reveal_password=True,
            key="system.password",
        )
        self.role = ft.Dropdown(
            label="角色",
            value="teacher",
            options=[
                ft.DropdownOption(key="system_admin", text="系统管理员"),
                ft.DropdownOption(key="academic_admin", text="教务管理员"),
                ft.DropdownOption(key="teacher", text="教师"),
            ],
            key="system.role",
        )
        self.department_id = ft.TextField(
            label="院系编号（系统管理员可空）", key="system.department_id"
        )
        self.can_approve = ft.Checkbox(label="可以审批例外", key="system.can_approve")
        self.feedback = ViewFeedback(key="system.feedback")
        self.table_host = ft.Column(key="system.table")
        self.refresh_button = ft.Button(
            "刷新", icon=ft.Icons.REFRESH, key="system.refresh", on_click=self.load
        )
        self.create_button = ft.Button(
            "新建账号",
            icon=ft.Icons.PERSON_ADD,
            key="system.create",
            on_click=self.create,
        )
        self.roles_button = ft.Button(
            "保存角色",
            icon=ft.Icons.MANAGE_ACCOUNTS,
            key="system.roles",
            disabled=True,
            on_click=self.save_roles,
        )
        self.reset_button = ft.Button(
            "重置密码",
            icon=ft.Icons.PASSWORD,
            key="system.reset",
            disabled=True,
            on_click=self.reset_password,
        )
        self.status_button = ft.Button(
            "停用账号",
            icon=ft.Icons.PERSON_OFF,
            key="system.status",
            disabled=True,
            on_click=self.toggle_status,
        )
        self.root = ft.Column(
            controls=[
                ft.Text("系统管理", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("新建账号、调整角色和院系范围、启停账号、重置临时密码。"),
                ft.ResponsiveRow(
                    controls=[
                        self.username,
                        self.temporary_password,
                        self.role,
                        self.department_id,
                        self.can_approve,
                    ]
                ),
                ft.Row(
                    controls=[
                        self.create_button,
                        self.roles_button,
                        self.reset_button,
                        self.status_button,
                        self.refresh_button,
                    ],
                    wrap=True,
                ),
                self.feedback.control,
                self.table_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="system.root",
        )
        self._render_rows()

    def _role_payload(self) -> list[dict[str, Any]]:
        role = self.role.value or "teacher"
        return [
            {
                "role": role,
                "department_id": (
                    None if role == "system_admin" else self.department_id.value.strip() or None
                ),
                "can_approve_exceptions": bool(self.can_approve.value),
            }
        ]

    def _select_handler(self, row: dict[str, Any]) -> Callable[[], None]:
        return lambda: self.select(row)

    def select(self, user: dict[str, Any]) -> None:
        self.selected = user
        self.username.value = str(user.get("username", ""))
        roles = user.get("roles", [])
        assignment = roles[0] if isinstance(roles, list) and roles else {}
        if isinstance(assignment, dict):
            self.role.value = str(assignment.get("role", "teacher"))
            self.department_id.value = str(assignment.get("department_id") or "")
            self.can_approve.value = bool(assignment.get("can_approve_exceptions"))
        self.roles_button.disabled = False
        self.reset_button.disabled = False
        self.status_button.disabled = False
        self.status_button.content = "停用账号" if user.get("is_active") else "启用账号"
        self.feedback.show(f"已选择账号：{user.get('username')}")
        self._render_rows()
        update_control(self.root)

    def _render_rows(self) -> None:
        if not self.rows:
            self.table_host.controls = [ft.Text("暂无账号")]
            return
        columns = (
            ("username", "用户名"),
            ("is_active", "启用"),
            ("must_change_password", "必须改密"),
            ("roles", "角色与院系范围"),
        )
        self.table_host.controls = [
            ft.Row(
                controls=[
                    ft.DataTable(
                        columns=[ft.DataColumn(label=label) for _name, label in columns],
                        rows=[
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(self._display(row.get(name))))
                                    for name, _label in columns
                                ],
                                selected=(
                                    self.selected is not None
                                    and self.selected.get("id") == row.get("id")
                                ),
                                on_select_change=self._select_handler(row),
                            )
                            for row in self.rows
                        ],
                        show_checkbox_column=True,
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            )
        ]

    @staticmethod
    def _display(value: object) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, list | dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "")

    async def load(self) -> None:
        set_busy((self.refresh_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            self.rows = await self.workflow.list_users()
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self.selected = None
            self.roles_button.disabled = True
            self.reset_button.disabled = True
            self.status_button.disabled = True
            self._render_rows()
        finally:
            set_busy((self.refresh_button,), False)
            update_control(self.root)

    async def create(self) -> None:
        payload = {
            "username": self.username.value.strip(),
            "temporary_password": self.temporary_password.value,
            "roles": self._role_payload(),
        }
        fields: dict[str, ft.TextField | ft.Dropdown] = {
            "username": self.username,
            "temporary_password": self.temporary_password,
            "roles": self.role,
            "department_id": self.department_id,
        }
        try:
            await self.workflow.create_user(payload)
        except ApiError as error:
            bind_api_error(error, fields, self.feedback)
        else:
            self.temporary_password.value = ""
            await self.load()
            self.feedback.show("账号已创建；临时密码不会保存在页面中")
        update_control(self.root)

    async def save_roles(self) -> None:
        if self.selected is None:
            return
        try:
            updated = await self.workflow.replace_roles(
                str(self.selected["id"]), self._role_payload()
            )
        except ApiError as error:
            bind_api_error(error, {"roles": self.role}, self.feedback)
        else:
            self.selected = updated
            await self.load()
            self.feedback.show("角色和院系范围已更新")
        update_control(self.root)

    async def toggle_status(self) -> None:
        if self.selected is None:
            return
        active = not bool(self.selected.get("is_active"))
        try:
            await self.workflow.set_status(str(self.selected["id"]), active)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            await self.load()
            self.feedback.show("账号已启用" if active else "账号已停用")
        update_control(self.root)

    async def reset_password(self) -> None:
        if self.selected is None:
            return
        requested = self.temporary_password.value or None
        try:
            result = await self.workflow.reset_password(str(self.selected["id"]), requested)
        except ApiError as error:
            bind_api_error(error, {"temporary_password": self.temporary_password}, self.feedback)
            update_control(self.root)
            return
        self.temporary_password.value = ""
        temporary_password = str(result["temporary_password"])
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title="临时密码（仅显示一次）",
                content=ft.Text(temporary_password, selectable=True),
                actions=[ft.Button("我已保存", on_click=self.page.pop_dialog)],
            )
        )
        await self.load()


def system_admin_view(page: ft.Page, client: ApiClient) -> ft.Control:
    view = SystemAdminView(page, client)
    page.run_task(view.load)
    return view.root
