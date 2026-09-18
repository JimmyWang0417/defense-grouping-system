from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient


class SystemAdminWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list_users(self) -> list[dict[str, Any]]:
        return await self.client.request_list("GET", "/api/v1/users")

    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.request("POST", "/api/v1/users", json=payload)

    async def set_status(self, user_id: str, active: bool) -> dict[str, Any]:
        return await self.client.request(
            "PATCH",
            f"/api/v1/users/{user_id}/status",
            json={"is_active": active},
        )

    async def replace_roles(
        self,
        user_id: str,
        roles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self.client.request(
            "PUT",
            f"/api/v1/users/{user_id}/roles",
            json={"roles": roles},
        )


def system_admin_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("系统管理", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("管理账号、角色、院系范围、例外审批权限与密码重置。"),
            ft.Row(
                controls=[
                    ft.Button("新建账号", icon=ft.Icons.PERSON_ADD),
                    ft.Button("编辑角色", icon=ft.Icons.MANAGE_ACCOUNTS),
                    ft.Button("重置密码", icon=ft.Icons.PASSWORD),
                    ft.Button("停用账号", icon=ft.Icons.PERSON_OFF),
                ],
                wrap=True,
            ),
        ]
    )
