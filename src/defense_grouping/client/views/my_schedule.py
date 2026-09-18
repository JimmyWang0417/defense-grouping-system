from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient


class MyScheduleWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(self) -> list[dict[str, Any]]:
        return await self.client.request_list("GET", "/api/v1/teacher/schedule")

    async def confirm(self, panel_assignment_id: str) -> dict[str, Any]:
        return await self.client.request(
            "POST",
            f"/api/v1/teacher/assignments/{panel_assignment_id}/confirm",
        )


def my_schedule_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("我的答辩安排", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("仅显示已发布且本人参与的安排，页面只读。"),
            ft.Text("组号 / 学生 / 日期 / 时间 / 教室 / 同组教师 / 例外标记 / 确认状态"),
            ft.Button("确认所选安排", icon=ft.Icons.CHECK_CIRCLE),
            ft.Text("除“确认”外不提供任何写操作。"),
        ]
    )
