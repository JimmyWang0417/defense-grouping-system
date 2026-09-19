from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import flet as ft
import httpx
import pytest

from defense_grouping.client.api_client import ApiClient
from defense_grouping.client.session import MemoryRefreshTokenStore
from defense_grouping.client.views.my_schedule import MyScheduleView
from defense_grouping.client.views.plans import PlansView
from defense_grouping.client.views.scheduling import SchedulingView
from tests.integration.conftest import INTEGRATION_PASSWORD


class FakePage:
    def __init__(self) -> None:
        self.dialog: ft.AlertDialog | None = None

    def show_dialog(self, dialog: ft.AlertDialog) -> None:
        self.dialog = dialog

    def pop_dialog(self) -> None:
        self.dialog = None


class SavingFilePicker:
    def __init__(self, destination: Path) -> None:
        self.destination = destination

    async def save_file(self, **kwargs: Any) -> str:
        content = kwargs.get("src_bytes")
        assert isinstance(content, bytes)
        self.destination.write_bytes(content)
        return str(self.destination)


async def invoke(handler: Callable[..., Any] | None) -> None:
    assert handler is not None
    result = handler()
    if inspect.isawaitable(result):
        await result


@pytest.mark.asyncio
async def test_real_view_handlers_complete_admin_to_teacher_flow(
    master_harness,
    configured_schedule,
    tmp_path: Path,
) -> None:
    api = ApiClient(
        "http://testserver",
        token_store=MemoryRefreshTokenStore(),
        transport=httpx.ASGITransport(app=master_harness.app),
    )
    page = cast(ft.Page, FakePage())
    try:
        admin = await api.login("academic-admin", INTEGRATION_PASSWORD)
        admin.selected_activity_id = str(configured_schedule.activity_id)

        async def short_sleep(_seconds: float) -> None:
            await asyncio.sleep(0.05)

        scheduling = SchedulingView(page, api, admin, sleep=short_sleep)
        scheduling.time_limit.value = "5"
        await invoke(scheduling.start_button.on_click)
        assert scheduling.plan_id is not None
        assert scheduling.progress.value == 1

        plans = PlansView(page, api, admin)
        await invoke(plans.load_button.on_click)
        assert plans.selected_plan is not None
        assert plans.selected_plan["id"] == scheduling.plan_id
        await invoke(plans.publish_button.on_click)
        fake_page = cast(FakePage, page)
        assert fake_page.dialog is not None
        confirm = cast(ft.Button, fake_page.dialog.actions[1])
        await invoke(confirm.on_click)
        assert plans.selected_plan is not None
        assert plans.selected_plan["status"] == "published"

        exported = tmp_path / "published-plan.xlsx"
        plans.file_picker = cast(ft.FilePicker, SavingFilePicker(exported))
        await invoke(plans.export_button.on_click)
        assert exported.exists()
        assert exported.stat().st_size > 0

        await api.logout()
        teacher = await api.login("teacher-user", INTEGRATION_PASSWORD)
        schedule = MyScheduleView(page, api)
        await invoke(schedule.refresh_button.on_click)
        assert len(schedule.rows) == 1
        schedule.select(schedule.rows[0])
        await invoke(schedule.confirm_button.on_click)
        assert schedule.rows[0]["confirmation_status"] == "confirmed"
        assert teacher.roles == frozenset({"teacher"})
    finally:
        await api.close()
