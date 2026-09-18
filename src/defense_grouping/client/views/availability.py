from __future__ import annotations

from typing import Any, Literal

import flet as ft

from defense_grouping.client.api_client import ApiClient


class AvailabilityWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(
        self,
        kind: Literal["occupancies", "leaves"],
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            f"/api/v1/{kind}",
            params={"page": page, "page_size": page_size},
        )

    async def create(
        self,
        kind: Literal["occupancies", "leaves"],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/{kind}", json=payload)


def availability_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("可用性管理", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("按列表或冲突日历查看课程占用与请假记录。"),
            ft.Row(
                controls=[
                    ft.Button("课程占用", icon=ft.Icons.LIST),
                    ft.Button("请假记录", icon=ft.Icons.EVENT_BUSY),
                    ft.Button("冲突日历", icon=ft.Icons.CALENDAR_MONTH),
                ]
            ),
            ft.Text("可按人员、日期和状态筛选；冲突由后端统一校验。"),
        ]
    )
