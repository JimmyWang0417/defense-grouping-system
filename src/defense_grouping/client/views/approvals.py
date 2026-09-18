from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient
from defense_grouping.client.session import SessionState


def available_exception_actions(
    exception: dict[str, Any],
    session: SessionState,
) -> tuple[str, ...]:
    status = exception.get("status")
    requester_id = exception.get("requester_id")
    if status == "pending" and requester_id != session.user_id:
        return ("approve", "reject")
    if status in {"pending", "approved"} and requester_id == session.user_id:
        return ("revoke",)
    if status == "approved":
        return ("revoke",)
    return ()


class ApprovalWorkflow:
    def __init__(self, client: ApiClient, session: SessionState) -> None:
        self.client = client
        self.session = session

    async def list(self, activity_id: str) -> list[dict[str, Any]]:
        return await self.client.request_list(
            "GET",
            "/api/v1/exceptions",
            params={"activity_id": activity_id},
        )

    async def request_exception(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.request("POST", "/api/v1/exceptions", json=payload)

    async def act(self, exception: dict[str, Any], action: str) -> dict[str, Any]:
        if action not in available_exception_actions(exception, self.session):
            raise PermissionError("当前用户不能执行此审批操作")
        return await self.client.request(
            "POST",
            f"/api/v1/exceptions/{exception['id']}/{action}",
        )


def approvals_view(_client: ApiClient, session: SessionState) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("例外审批", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("例外必须精确到约束类型与人员/时段，不支持整体关闭规则。"),
            ft.TextField(label="活动编号"),
            ft.Row(
                controls=[
                    ft.Button("新建申请", icon=ft.Icons.ADD),
                    ft.Button("批准", icon=ft.Icons.CHECK, disabled=True),
                    ft.Button("拒绝", icon=ft.Icons.CLOSE, disabled=True),
                    ft.Button("撤销", icon=ft.Icons.UNDO, disabled=True),
                ]
            ),
            ft.Text(f"当前账号：{session.username or '-'}；申请人不会看到可用的批准/拒绝动作。"),
        ]
    )
