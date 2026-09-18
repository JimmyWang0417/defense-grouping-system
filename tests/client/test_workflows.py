from __future__ import annotations

from typing import Any

import pytest

from defense_grouping.client.components.data_table import DataTableState, DirtyFormState
from defense_grouping.client.components.task_progress import poll_schedule_job
from defense_grouping.client.session import SessionState
from defense_grouping.client.views.activity_wizard import ActivityWizardState
from defense_grouping.client.views.approvals import available_exception_actions
from defense_grouping.client.views.plans import summarize_comparison


def test_data_table_exposes_search_filter_sort_page_and_selection() -> None:
    state = DataTableState(
        rows=[
            {"id": "3", "name": "Charlie", "status": "active"},
            {"id": "1", "name": "Alice", "status": "active"},
            {"id": "2", "name": "Bob", "status": "inactive"},
        ],
        search_fields=("name",),
        page_size=1,
    )
    state.search = "a"
    state.filters["status"] = "active"
    state.sort_key = "name"
    state.page = 2

    assert state.visible_rows() == [{"id": "3", "name": "Charlie", "status": "active"}]
    assert state.total_filtered == 2
    state.toggle_selected("3")
    assert state.selected_ids == {"3"}
    state.loading = True
    assert state.view_state == "loading"
    state.loading = False
    state.error = "network"
    assert state.view_state == "error"


def test_dirty_form_requires_explicit_discard_before_navigation() -> None:
    form = DirtyFormState(initial={"name": "原活动"})
    assert form.can_leave is True
    form.set_value("name", "修改后活动")
    assert form.dirty is True
    assert form.can_leave is False
    form.field_errors = {"name": "名称已存在"}
    form.discard_changes()
    assert form.values == {"name": "原活动"}
    assert form.field_errors == {}
    assert form.can_leave is True


def test_activity_wizard_has_five_ordered_steps_and_presence_validation() -> None:
    wizard = ActivityWizardState()
    assert wizard.step_titles == ("范围", "答辩组规则", "时段", "教室", "求解参数")
    assert wizard.current_step == 0
    assert wizard.next_step() is False
    assert wizard.field_errors == {"department_id": "请选择院系", "name": "请输入活动名称"}
    wizard.values.update({"department_id": "dep-1", "name": "2026 秋季答辩"})
    assert wizard.next_step() is True
    assert wizard.current_step == 1


@pytest.mark.asyncio
async def test_schedule_polling_uses_bounded_exponential_intervals() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.index = 0

        async def request(self, _method: str, _path: str, **_kwargs: Any) -> dict[str, Any]:
            statuses = ["pending", "running", "running", "running", "succeeded"]
            status = statuses[self.index]
            self.index += 1
            return {"id": "job-1", "status": status, "progress": self.index / 5}

    intervals: list[float] = []

    async def record_sleep(seconds: float) -> None:
        intervals.append(seconds)

    updates: list[str] = []
    result = await poll_schedule_job(
        FakeClient(),
        "job-1",
        sleep=record_sleep,
        on_update=lambda job: updates.append(str(job["status"])),
    )

    assert result["status"] == "succeeded"
    assert intervals == [1, 2, 4, 5]
    assert updates == ["pending", "running", "running", "running", "succeeded"]


def test_requester_never_gets_approve_or_reject_actions() -> None:
    session = SessionState(
        user_id="user-1",
        username="requester",
        roles=frozenset({"academic_admin"}),
    )
    exception = {"id": "exception-1", "requester_id": "user-1", "status": "pending"}
    assert available_exception_actions(exception, session) == ("revoke",)


def test_plan_comparison_summary_includes_all_change_categories() -> None:
    summary = summarize_comparison(
        {
            "student_moves": [{"student_id": "s1"}],
            "teacher_changes": [{"teacher_id": "t1"}, {"teacher_id": "t2"}],
            "resource_changes": [{"room_changed": True}],
            "objective_deltas": {"balance_students": -10},
            "exception_use_delta": 1,
        }
    )
    assert summary == {
        "student_moves": 1,
        "teacher_changes": 2,
        "resource_changes": 1,
        "score_deltas": 1,
        "exception_use_delta": 1,
    }
