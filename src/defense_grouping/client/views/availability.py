from __future__ import annotations

from typing import Any, Literal, cast

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.data_table import DataTableState, render_data_table
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    parse_int,
    set_busy,
    update_control,
)

AvailabilityKind = Literal["occupancies", "leaves"]
AVAILABILITY_FIELDS: dict[AvailabilityKind, tuple[str, ...]] = {
    "occupancies": (
        "department_id",
        "person_type",
        "person_id",
        "starts_at",
        "ends_at",
        "academic_term_id",
        "teaching_week",
        "weekday",
        "start_section",
        "end_section",
    ),
    "leaves": (
        "department_id",
        "person_type",
        "person_id",
        "starts_at",
        "ends_at",
        "reason",
    ),
}
FIELD_LABELS = {
    "department_id": "院系编号",
    "person_type": "人员类型（teacher/student）",
    "person_id": "人员编号",
    "starts_at": "开始时间（含时区）",
    "ends_at": "结束时间（含时区）",
    "academic_term_id": "学期编号（可空）",
    "teaching_week": "教学周（可空）",
    "weekday": "星期（1-7，可空）",
    "start_section": "开始节次（可空）",
    "end_section": "结束节次（可空）",
    "reason": "请假原因",
}
OPTIONAL_INTEGER_FIELDS = {"teaching_week", "weekday", "start_section", "end_section"}


class AvailabilityWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(
        self,
        kind: AvailabilityKind,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        return await self.client.request(
            "GET", f"/api/v1/{kind}", params={"page": page, "page_size": page_size}
        )

    async def create(self, kind: AvailabilityKind, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/{kind}", json=payload)


class AvailabilityView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = AvailabilityWorkflow(client)
        self.kind: AvailabilityKind = "occupancies"
        self.state = DataTableState()
        self.kind_picker = ft.Dropdown(
            label="记录类型",
            value=self.kind,
            options=[
                ft.DropdownOption(key="occupancies", text="课程占用"),
                ft.DropdownOption(key="leaves", text="请假记录"),
            ],
            width=220,
            key="availability.kind",
            on_select=self.switch_kind,
        )
        self.form: dict[str, ft.TextField] = {}
        self.form_host = ft.ResponsiveRow(key="availability.form")
        self.table_host = ft.Column(key="availability.table")
        self.feedback = ViewFeedback(key="availability.feedback")
        self.refresh_button = ft.Button(
            "刷新", icon=ft.Icons.REFRESH, key="availability.refresh", on_click=self.load
        )
        self.create_button = ft.Button(
            "保存记录", icon=ft.Icons.ADD, key="availability.create", on_click=self.create
        )
        self.root = ft.Column(
            controls=[
                ft.Text("可用性管理", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("维护课程占用与请假记录；时间必须包含时区。"),
                ft.Row(controls=[self.kind_picker, self.refresh_button], wrap=True),
                self.feedback.control,
                self.form_host,
                self.create_button,
                ft.Divider(),
                self.table_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="availability.root",
        )
        self._build_form()
        self._render_rows()

    def _build_form(self) -> None:
        self.form = {
            name: ft.TextField(
                label=FIELD_LABELS[name],
                key=f"availability.field.{name}",
                col={"xs": 12, "md": 6, "lg": 4},
            )
            for name in AVAILABILITY_FIELDS[self.kind]
        }
        self.form_host.controls = list(self.form.values())

    def _payload(self) -> dict[str, Any] | None:
        payload: dict[str, Any] = {}
        valid = True
        for name, control in self.form.items():
            control.error = None
            raw = control.value.strip()
            if name in OPTIONAL_INTEGER_FIELDS:
                if not raw:
                    payload[name] = None
                    continue
                parsed = parse_int(control, FIELD_LABELS[name])
                if parsed is None:
                    valid = False
                else:
                    payload[name] = parsed
            elif name == "academic_term_id":
                payload[name] = raw or None
            else:
                payload[name] = raw
        return payload if valid else None

    def _render_rows(self) -> None:
        columns: tuple[tuple[str, str], ...] = (
            ("person_type", "人员类型"),
            ("person_id", "人员编号"),
            ("starts_at", "开始"),
            ("ends_at", "结束"),
        )
        if self.kind == "leaves":
            columns += (("reason", "原因"), ("status", "状态"))
        self.table_host.controls = [render_data_table(self.state, columns)]

    async def switch_kind(self) -> None:
        value = self.kind_picker.value
        if value not in ("occupancies", "leaves"):
            return
        self.kind = cast(AvailabilityKind, value)
        self.state = DataTableState()
        self._build_form()
        await self.load()

    async def load(self) -> None:
        self.state.loading = True
        self.state.error = None
        self._render_rows()
        update_control(self.root)
        try:
            result = await self.workflow.list(self.kind)
            items = result.get("items", [])
            self.state.rows = items if isinstance(items, list) else []
        except ApiError as error:
            self.state.error = error.message
            bind_api_error(error, self.form, self.feedback)
        finally:
            self.state.loading = False
            self._render_rows()
            update_control(self.root)

    async def create(self) -> None:
        payload = self._payload()
        if payload is None:
            update_control(self.root)
            return
        set_busy((self.create_button, self.refresh_button), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            await self.workflow.create(self.kind, payload)
        except ApiError as error:
            bind_api_error(error, self.form, self.feedback)
        else:
            for control in self.form.values():
                control.value = ""
            await self.load()
            self.feedback.show("记录已保存")
        finally:
            set_busy((self.create_button, self.refresh_button), False)
            update_control(self.root)


def availability_view(page: ft.Page, client: ApiClient) -> ft.Control:
    view = AvailabilityView(page, client)
    page.run_task(view.load)
    return view.root
