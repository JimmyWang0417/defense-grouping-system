from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient
from defense_grouping.client.components.data_table import DataTableState, render_data_table

MASTER_RESOURCES = {
    "departments": ("code", "name"),
    "majors": ("code", "name", "department_id"),
    "directions": ("code", "name", "department_id"),
    "teachers": ("employee_number", "name", "title", "workload_limit"),
    "students": ("student_number", "name", "grade", "advisor_id"),
    "terms": ("academic_year", "semester", "starts_on", "ends_on"),
    "rooms": ("campus", "building", "name", "capacity"),
}


class MasterDataWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(
        self,
        resource: str,
        *,
        search: str = "",
        page: int = 1,
        page_size: int = 25,
        sort: str = "",
    ) -> dict[str, Any]:
        if resource not in MASTER_RESOURCES:
            raise ValueError("未知基础数据资源")
        return await self.client.request(
            "GET",
            f"/api/v1/{resource}",
            params={
                "search": search,
                "page": page,
                "page_size": page_size,
                "sort": sort,
            },
        )

    async def create(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        if resource not in MASTER_RESOURCES:
            raise ValueError("未知基础数据资源")
        return await self.client.request("POST", f"/api/v1/{resource}", json=payload)

    async def update(
        self,
        resource: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.client.request(
            "PATCH",
            f"/api/v1/{resource}/{resource_id}",
            json=payload,
        )

    async def delete(self, resource: str, resource_id: str) -> None:
        await self.client.request("DELETE", f"/api/v1/{resource}/{resource_id}")


def master_data_view(_client: ApiClient) -> ft.Control:
    state = DataTableState(search_fields=("code", "name"), loading=False)
    return ft.Column(
        controls=[
            ft.Text("基础数据", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("管理院系、专业、方向、教师、学生、学期和教室。"),
            ft.TextField(label="搜索", prefix_icon=ft.Icons.SEARCH),
            ft.Row(
                controls=[
                    ft.Button("院系"),
                    ft.Button("教师"),
                    ft.Button("学生"),
                    ft.Button("教室"),
                    ft.Button("批量操作", icon=ft.Icons.CHECKLIST),
                ],
                wrap=True,
            ),
            render_data_table(state, (("code", "编号"), ("name", "名称"))),
        ]
    )
