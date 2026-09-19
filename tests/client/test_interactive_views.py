from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, cast

import flet as ft
import pytest

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ActivityContext,
    ViewFeedback,
    bind_api_error,
    control_by_key,
)
from defense_grouping.client.session import SessionState
from defense_grouping.client.views.approvals import ApprovalsView
from defense_grouping.client.views.availability import AvailabilityView
from defense_grouping.client.views.imports import ImportsView
from defense_grouping.client.views.master_data import MasterDataView
from defense_grouping.client.views.my_schedule import MyScheduleView
from defense_grouping.client.views.plans import PlansView
from defense_grouping.client.views.scheduling import SchedulingView


@dataclass
class RecordedRequest:
    method: str
    path: str
    kwargs: dict[str, Any]


class RecordingClient:
    def __init__(self) -> None:
        self.responses: deque[dict[str, Any] | list[dict[str, Any]] | ApiError] = deque()
        self.byte_responses: deque[bytes | ApiError] = deque()
        self.requests: list[RecordedRequest] = []

    def queue(self, *responses: dict[str, Any] | list[dict[str, Any]] | ApiError) -> None:
        self.responses.extend(responses)

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(RecordedRequest(method, path, kwargs))
        response = self.responses.popleft()
        if isinstance(response, ApiError):
            raise response
        assert isinstance(response, dict)
        return response

    async def request_list(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.requests.append(RecordedRequest(method, path, kwargs))
        response = self.responses.popleft()
        if isinstance(response, ApiError):
            raise response
        assert isinstance(response, list)
        return response

    async def request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        self.requests.append(RecordedRequest(method, path, kwargs))
        response = self.byte_responses.popleft()
        if isinstance(response, ApiError):
            raise response
        return response


class FakePage:
    def __init__(self) -> None:
        self.dialog: ft.Control | None = None
        self.dialog_closed = False

    def show_dialog(self, dialog: ft.Control) -> None:
        self.dialog = dialog

    def pop_dialog(self) -> None:
        self.dialog_closed = True


def client(recording: RecordingClient) -> ApiClient:
    return cast(ApiClient, recording)


def page(fake: FakePage) -> ft.Page:
    return cast(ft.Page, fake)


def academic_session() -> SessionState:
    return SessionState(
        user_id="admin-1",
        username="academic-admin",
        roles=frozenset({"academic_admin"}),
    )


def test_bind_api_error_maps_field_and_request_id() -> None:
    name = ft.TextField(key="name")
    feedback = ViewFeedback()
    error = ApiError("invalid", "请修正输入", "request-7", {"name": "名称不能为空"})

    bind_api_error(error, {"name": name}, feedback)

    assert name.error == "名称不能为空"
    assert "request-7" in feedback.message
    assert feedback.error is True


@pytest.mark.asyncio
async def test_activity_context_loads_and_selects_first_activity() -> None:
    recording = RecordingClient()
    recording.queue(
        {
            "items": [
                {"id": "activity-1", "name": "秋季答辩"},
                {"id": "activity-2", "name": "春季答辩"},
            ]
        }
    )
    session = academic_session()
    context = ActivityContext(session)

    await context.load(client(recording))
    context.select("activity-2")

    assert [option.name for option in context.options] == ["秋季答辩", "春季答辩"]
    assert session.selected_activity_id == "activity-2"


@pytest.mark.asyncio
async def test_master_data_load_renders_rows_and_has_keyed_controls() -> None:
    recording = RecordingClient()
    recording.queue(
        {
            "items": [{"id": "d1", "code": "CS", "name": "计算机", "version": 1}],
            "page": 1,
            "page_size": 25,
            "total": 1,
        }
    )
    view = MasterDataView(page(FakePage()), client(recording))

    await view.load()

    assert recording.requests[-1].path == "/api/v1/departments"
    assert view.state.rows[0]["name"] == "计算机"
    assert control_by_key(view.root, "master.table") is view.table_host


@pytest.mark.asyncio
async def test_availability_preserves_form_and_maps_api_error() -> None:
    recording = RecordingClient()
    recording.queue(ApiError("invalid", "时间冲突", "req-9", {"person_id": "人员不存在"}))
    view = AvailabilityView(page(FakePage()), client(recording))
    view.form["person_id"].value = "missing"
    view.form["department_id"].value = "department-1"
    view.form["person_type"].value = "teacher"
    view.form["starts_at"].value = "2026-09-19T08:00:00+08:00"
    view.form["ends_at"].value = "2026-09-19T10:00:00+08:00"

    await view.create()

    assert view.form["person_id"].value == "missing"
    assert view.form["person_id"].error == "人员不存在"
    assert "req-9" in view.feedback.message


@pytest.mark.asyncio
async def test_import_uses_selected_workbook_bytes_and_enables_confirm() -> None:
    recording = RecordingClient()
    recording.queue(
        {"id": "batch-1", "status": "pending"},
        {
            "id": "batch-1",
            "status": "ready",
            "creates": 3,
            "updates": 0,
            "unchanged": 0,
            "issues": [],
        },
    )
    view = ImportsView(page(FakePage()), client(recording))
    view.set_selected_file("学生信息.xlsx", b"xlsx-data")

    await view.run_preflight()

    assert recording.requests[0].path == "/api/v1/imports/student/preflight"
    assert recording.requests[0].kwargs["files"]["file"][1] == b"xlsx-data"
    assert view.confirm_button.disabled is False


@pytest.mark.asyncio
async def test_schedule_start_polls_until_plan_is_ready() -> None:
    recording = RecordingClient()
    recording.queue(
        {"id": "job-1", "status": "pending", "stage": "queued", "progress": 0},
        {"id": "job-1", "status": "running", "stage": "solving", "progress": 0.5},
        {
            "id": "job-1",
            "status": "succeeded",
            "stage": "completed",
            "progress": 1,
            "plan_id": "plan-1",
        },
    )
    session = academic_session()
    session.selected_activity_id = "activity-1"

    async def no_wait(_seconds: float) -> None:
        return None

    view = SchedulingView(page(FakePage()), client(recording), session, sleep=no_wait)

    await view.start()

    assert view.plan_id == "plan-1"
    assert view.progress.value == 1
    assert [request.path for request in recording.requests] == [
        "/api/v1/activities/activity-1/schedule-jobs",
        "/api/v1/schedule-jobs/job-1",
        "/api/v1/schedule-jobs/job-1",
    ]


@pytest.mark.asyncio
async def test_plan_publish_refreshes_selected_status() -> None:
    recording = RecordingClient()
    recording.queue({"id": "p1", "status": "published", "groups": []})
    fake_page = FakePage()
    view = PlansView(page(fake_page), client(recording), academic_session())
    view.select_plan({"id": "p1", "status": "ready", "groups": []})

    await view.publish(confirmed=True)

    assert view.selected_plan is not None
    assert view.selected_plan["status"] == "published"
    assert recording.requests[-1].path == "/api/v1/plans/p1/publish"


def test_requester_cannot_approve_own_exception() -> None:
    session = academic_session()
    view = ApprovalsView(page(FakePage()), client(RecordingClient()), session)

    view.select({"id": "e1", "requester_id": session.user_id, "status": "pending"})

    assert view.approve_button.disabled is True
    assert view.reject_button.disabled is True
    assert view.revoke_button.disabled is False


@pytest.mark.asyncio
async def test_teacher_confirmation_updates_only_selected_assignment() -> None:
    recording = RecordingClient()
    recording.queue({"status": "confirmed"})
    view = MyScheduleView(page(FakePage()), client(recording))
    assignment = {
        "panel_assignment_id": "pa1",
        "group_code": "G01",
        "confirmation_status": "pending",
    }
    view.rows = [assignment]
    view.select(assignment)

    await view.confirm()

    assert recording.requests[-1].path == "/api/v1/teacher/assignments/pa1/confirm"
    assert assignment["confirmation_status"] == "confirmed"
