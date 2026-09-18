from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient


def summarize_comparison(comparison: dict[str, Any]) -> dict[str, int | float]:
    return {
        "student_moves": len(comparison.get("student_moves", [])),
        "teacher_changes": len(comparison.get("teacher_changes", [])),
        "resource_changes": len(comparison.get("resource_changes", [])),
        "score_deltas": len(comparison.get("objective_deltas", {})),
        "exception_use_delta": int(comparison.get("exception_use_delta", 0)),
    }


class PlanWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(self, activity_id: str) -> list[dict[str, Any]]:
        return await self.client.request_list(
            "GET", f"/api/v1/activities/{activity_id}/plans"
        )

    async def detail(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("GET", f"/api/v1/plans/{plan_id}")

    async def copy(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/copy")

    async def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            f"/api/v1/plans/{left_id}/compare/{right_id}",
        )

    async def adjust_group(
        self,
        plan_id: str,
        group_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.client.request(
            "PATCH",
            f"/api/v1/plans/{plan_id}/groups/{group_id}",
            json=payload,
        )

    async def validate(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/validate")

    async def publish(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/publish")

    async def withdraw(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/withdraw")

    async def export(self, plan_id: str) -> bytes:
        return await self.client.request_bytes("GET", f"/api/v1/plans/{plan_id}/export")


def plans_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("方案管理", size=28, weight=ft.FontWeight.BOLD),
            ft.TextField(label="活动编号"),
            ft.Row(
                controls=[
                    ft.Button("版本对比", icon=ft.Icons.COMPARE_ARROWS),
                    ft.Button("复制为草稿", icon=ft.Icons.CONTENT_COPY),
                    ft.Button("重新校验", icon=ft.Icons.RULE),
                    ft.Button("发布", icon=ft.Icons.PUBLISH),
                    ft.Button("撤回", icon=ft.Icons.UNPUBLISHED),
                    ft.Button("导出 Excel", icon=ft.Icons.DOWNLOAD),
                ],
                wrap=True,
            ),
            ft.Text("详情显示学生、教师、组长、时段、教室、目标分项、诊断与已用例外。"),
            ft.Text("人工调整通过候选列表选择，保存前由后端重新校验。"),
        ]
    )
