from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.task_progress import poll_schedule_job
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    parse_float,
    parse_int,
    set_busy,
    update_control,
)
from defense_grouping.client.session import SessionState

Sleep = Callable[[float], Awaitable[None]]


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

    async def wait(
        self,
        job_id: str,
        *,
        sleep: Sleep = asyncio.sleep,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await poll_schedule_job(self.client, job_id, sleep=sleep, on_update=on_update)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        return await self.client.request("DELETE", f"/api/v1/schedule-jobs/{job_id}")


class SchedulingView:
    def __init__(
        self,
        page: ft.Page,
        client: ApiClient,
        session: SessionState,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.page = page
        self.session = session
        self.workflow = SchedulingWorkflow(client)
        self.sleep = sleep
        self.job_id: str | None = None
        self.plan_id: str | None = None
        self.activity_id = ft.TextField(
            label="活动编号",
            value=session.selected_activity_id or "",
            key="scheduling.activity_id",
        )
        self.seed = ft.TextField(label="随机种子", value="20260918", key="scheduling.seed")
        self.time_limit = ft.TextField(
            label="求解时限（秒）", value="60", key="scheduling.time_limit"
        )
        self.start_button = ft.Button(
            "开始求解",
            icon=ft.Icons.PLAY_ARROW,
            key="scheduling.start",
            on_click=self.start,
        )
        self.cancel_button = ft.Button(
            "取消任务",
            icon=ft.Icons.CANCEL,
            disabled=True,
            key="scheduling.cancel",
            on_click=self.cancel,
        )
        self.progress = ft.ProgressBar(value=0, key="scheduling.progress")
        self.stage = ft.Text("尚未开始", key="scheduling.stage")
        self.diagnostics = ft.Column(key="scheduling.diagnostics")
        self.feedback = ViewFeedback(key="scheduling.feedback")
        self.root = ft.Column(
            controls=[
                ft.Text("自动排组", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("选择活动并启动求解；进度和失败原因会持续显示。"),
                ft.ResponsiveRow(controls=[self.activity_id, self.seed, self.time_limit]),
                ft.Row(controls=[self.start_button, self.cancel_button], wrap=True),
                self.feedback.control,
                self.progress,
                self.stage,
                self.diagnostics,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="scheduling.root",
        )

    def _apply_job(self, job: dict[str, Any]) -> None:
        progress = job.get("progress", 0)
        self.progress.value = float(progress) if isinstance(progress, int | float) else 0
        status = str(job.get("status", "unknown"))
        stage = str(job.get("stage", ""))
        self.stage.value = f"状态：{status}；阶段：{stage or '-'}"
        raw_plan_id = job.get("plan_id")
        if raw_plan_id:
            self.plan_id = str(raw_plan_id)
        details: list[ft.Control] = []
        if job.get("error_code") or job.get("error_message"):
            details.append(
                ft.Text(
                    f"{job.get('error_code', '')}：{job.get('error_message', '')}",
                    color=ft.Colors.RED_700,
                    selectable=True,
                )
            )
        if self.plan_id:
            details.append(ft.Text(f"生成方案：{self.plan_id}", selectable=True))
        self.diagnostics.controls = details
        self.cancel_button.disabled = status not in {"pending", "running"}
        update_control(self.root)

    async def start(self) -> None:
        activity_id = self.activity_id.value.strip() or self.session.selected_activity_id
        if not activity_id:
            self.activity_id.error = "请选择或输入活动编号"
            update_control(self.root)
            return
        seed = parse_int(self.seed, "随机种子")
        time_limit = parse_float(self.time_limit, "求解时限")
        if seed is None or time_limit is None:
            update_control(self.root)
            return
        self.activity_id.error = None
        self.feedback.clear()
        self.plan_id = None
        set_busy((self.start_button,), True)
        self.cancel_button.disabled = False
        update_control(self.root)
        try:
            job = await self.workflow.start(
                activity_id,
                seed=seed,
                time_limit_seconds=time_limit,
                idempotency_key=str(uuid4()),
            )
            self.job_id = str(job["id"])
            self._apply_job(job)
            terminal = await self.workflow.wait(
                self.job_id, sleep=self.sleep, on_update=self._apply_job
            )
            self._apply_job(terminal)
            if terminal.get("status") == "succeeded":
                self.feedback.show(f"求解完成，方案编号：{self.plan_id or '-'}")
            elif terminal.get("status") == "cancelled":
                self.feedback.show("任务已取消")
            else:
                self.feedback.show(
                    str(terminal.get("error_message") or "求解失败，请检查诊断信息"),
                    error=True,
                )
        except ApiError as error:
            bind_api_error(
                error,
                {
                    "activity_id": self.activity_id,
                    "seed": self.seed,
                    "time_limit_seconds": self.time_limit,
                },
                self.feedback,
            )
        finally:
            set_busy((self.start_button,), False)
            self.cancel_button.disabled = True
            update_control(self.root)

    async def cancel(self) -> None:
        if self.job_id is None:
            return
        self.cancel_button.disabled = True
        update_control(self.root)
        try:
            job = await self.workflow.cancel(self.job_id)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self._apply_job(job)
            self.feedback.show("已提交取消请求")
        update_control(self.root)


def scheduling_view(page: ft.Page, client: ApiClient, session: SessionState) -> ft.Control:
    return SchedulingView(page, client, session).root
