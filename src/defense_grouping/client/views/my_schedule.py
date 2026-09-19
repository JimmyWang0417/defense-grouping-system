from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    set_busy,
    update_control,
)


class MyScheduleWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(self) -> list[dict[str, Any]]:
        return await self.client.request_list("GET", "/api/v1/teacher/schedule")

    async def confirm(self, panel_assignment_id: str) -> dict[str, Any]:
        return await self.client.request(
            "POST", f"/api/v1/teacher/assignments/{panel_assignment_id}/confirm"
        )


class MyScheduleView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = MyScheduleWorkflow(client)
        self.rows: list[dict[str, Any]] = []
        self.selected: dict[str, Any] | None = None
        self.feedback = ViewFeedback(key="schedule.feedback")
        self.table_host = ft.Column(key="schedule.table")
        self.refresh_button = ft.Button(
            "刷新", icon=ft.Icons.REFRESH, key="schedule.refresh", on_click=self.load
        )
        self.confirm_button = ft.Button(
            "确认所选安排",
            icon=ft.Icons.CHECK_CIRCLE,
            disabled=True,
            key="schedule.confirm",
            on_click=self.confirm,
        )
        self.root = ft.Column(
            controls=[
                ft.Text("我的答辩安排", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("这里只显示已发布且本人参与的安排；除确认外不能修改。"),
                ft.Row(controls=[self.refresh_button, self.confirm_button]),
                self.feedback.control,
                self.table_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="schedule.root",
        )
        self._render_rows()

    def _select_handler(self, row: dict[str, Any]) -> Callable[[], None]:
        return lambda: self.select(row)

    def select(self, assignment: dict[str, Any]) -> None:
        self.selected = assignment
        self.confirm_button.disabled = assignment.get("confirmation_status") != "pending"
        self.feedback.show(f"已选择答辩组：{assignment.get('group_code', '-')}")
        self._render_rows()
        update_control(self.root)

    def _render_rows(self) -> None:
        if not self.rows:
            self.table_host.controls = [ft.Text("暂无已发布的答辩安排")]
            return
        columns = (
            ("group_code", "组号"),
            ("student_ids", "学生"),
            ("date", "日期"),
            ("start_time", "开始"),
            ("end_time", "结束"),
            ("room_id", "教室"),
            ("fellow_teacher_ids", "同组教师"),
            ("exception_marker", "例外"),
            ("confirmation_status", "确认状态"),
        )
        self.table_host.controls = [
            ft.Row(
                controls=[
                    ft.DataTable(
                        columns=[ft.DataColumn(label=label) for _name, label in columns],
                        rows=[
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(self._display(row.get(name))))
                                    for name, _label in columns
                                ],
                                selected=(
                                    self.selected is not None
                                    and self.selected.get("panel_assignment_id")
                                    == row.get("panel_assignment_id")
                                ),
                                on_select_change=self._select_handler(row),
                            )
                            for row in self.rows
                        ],
                        show_checkbox_column=True,
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            )
        ]

    @staticmethod
    def _display(value: object) -> str:
        if isinstance(value, list):
            return ", ".join(map(str, value))
        if isinstance(value, bool):
            return "是" if value else "否"
        return str(value or "")

    async def load(self) -> None:
        set_busy((self.refresh_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            self.rows = await self.workflow.list()
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self.selected = None
            self.confirm_button.disabled = True
            self._render_rows()
        finally:
            set_busy((self.refresh_button,), False)
            update_control(self.root)

    async def confirm(self) -> None:
        if self.selected is None:
            return
        assignment_id = str(self.selected["panel_assignment_id"])
        set_busy((self.confirm_button,), True)
        update_control(self.root)
        try:
            result = await self.workflow.confirm(assignment_id)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self.selected["confirmation_status"] = result.get("status", "confirmed")
            self.feedback.show("已确认该答辩安排")
            self.confirm_button.disabled = True
            self._render_rows()
        update_control(self.root)


def my_schedule_view(page: ft.Page, client: ApiClient) -> ft.Control:
    view = MyScheduleView(page, client)
    page.run_task(view.load)
    return view.root
