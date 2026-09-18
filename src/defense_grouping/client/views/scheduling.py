from __future__ import annotations

from typing import Any
from uuid import uuid4

import flet as ft

from defense_grouping.client.api_client import ApiClient
from defense_grouping.client.components.task_progress import poll_schedule_job


class SchedulingWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def start(
        self,
        activity_id: str,
        *,
        seed: int,
        time_limit_seconds: float,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.request(
            "POST",
            f"/api/v1/activities/{activity_id}/schedule-jobs",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
            json={"seed": seed, "time_limit_seconds": time_limit_seconds},
        )

    async def wait(self, job_id: str) -> dict[str, Any]:
        return await poll_schedule_job(self.client, job_id)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        return await self.client.request("DELETE", f"/api/v1/schedule-jobs/{job_id}")


def scheduling_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("自动排组", size=28, weight=ft.FontWeight.BOLD),
            ft.TextField(label="活动编号"),
            ft.TextField(label="随机种子", value="20260918"),
            ft.TextField(label="求解时限（秒）", value="60"),
            ft.Row(
                controls=[
                    ft.Button("开始求解", icon=ft.Icons.PLAY_ARROW),
                    ft.Button("取消任务", icon=ft.Icons.CANCEL),
                ]
            ),
            ft.ProgressBar(value=0),
            ft.Text("任务阶段、当前最佳质量和冲突诊断将持续更新。"),
        ]
    )
