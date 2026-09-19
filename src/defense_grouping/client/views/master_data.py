from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.data_table import DataTableState
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    clear_field_errors,
    parse_int,
    set_busy,
    split_values,
    update_control,
)

MASTER_RESOURCES: dict[str, tuple[str, ...]] = {
    "departments": ("code", "name"),
    "majors": ("department_id", "code", "name"),
    "directions": ("department_id", "code", "name"),
    "teachers": (
        "employee_number",
        "name",
        "department_id",
        "title",
        "title_rank",
        "direction_ids",
        "workload_limit",
    ),
    "students": (
        "student_number",
        "name",
        "department_id",
        "major_id",
        "grade",
        "direction_ids",
        "advisor_id",
    ),
    "terms": (
        "department_id",
        "code",
        "name",
        "start_date",
        "end_date",
        "section_timetable",
    ),
    "rooms": ("department_id", "campus", "building", "name", "capacity"),
}

RESOURCE_LABELS = {
    "departments": "院系",
    "majors": "专业",
    "directions": "方向",
    "teachers": "教师",
    "students": "学生",
    "terms": "学期",
    "rooms": "教室",
}

FIELD_LABELS = {
    "id": "记录编号",
    "code": "编号",
    "name": "名称",
    "department_id": "院系编号",
    "employee_number": "工号",
    "title": "职称",
    "title_rank": "职称等级",
    "direction_ids": "方向编号（逗号分隔）",
    "workload_limit": "工作量上限",
    "student_number": "学号",
    "major_id": "专业编号",
    "grade": "年级",
    "advisor_id": "导师编号",
    "start_date": "开始日期（YYYY-MM-DD）",
    "end_date": "结束日期（YYYY-MM-DD）",
    "section_timetable": "节次表（JSON）",
    "campus": "校区",
    "building": "楼宇",
    "capacity": "容量",
}

INTEGER_FIELDS = {"title_rank", "workload_limit", "capacity"}
IMMUTABLE_ON_UPDATE = {
    "departments": {"code"},
    "majors": {"department_id", "code"},
    "directions": {"department_id", "code"},
    "teachers": {"employee_number", "department_id"},
    "students": {"student_number", "department_id"},
    "terms": {"department_id", "code"},
    "rooms": {"department_id"},
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
            params={"search": search, "page": page, "page_size": page_size, "sort": sort},
        )

    async def create(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        if resource not in MASTER_RESOURCES:
            raise ValueError("未知基础数据资源")
        return await self.client.request("POST", f"/api/v1/{resource}", json=payload)

    async def update(
        self, resource: str, resource_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.client.request("PATCH", f"/api/v1/{resource}/{resource_id}", json=payload)

    async def delete(self, resource: str, resource_id: str) -> None:
        await self.client.request("DELETE", f"/api/v1/{resource}/{resource_id}")


class MasterDataView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = MasterDataWorkflow(client)
        self.resource = "departments"
        self.state = DataTableState(search_fields=("code", "name"))
        self.selected: dict[str, Any] | None = None
        self.resource_picker = ft.Dropdown(
            label="数据类型",
            value=self.resource,
            options=[
                ft.DropdownOption(key=key, text=label) for key, label in RESOURCE_LABELS.items()
            ],
            width=220,
            key="master.resource",
            on_select=self.switch_resource,
        )
        self.search = ft.TextField(
            label="搜索",
            prefix_icon=ft.Icons.SEARCH,
            key="master.search",
            on_submit=self.load,
            expand=True,
        )
        self.form: dict[str, ft.TextField] = {}
        self.form_host = ft.ResponsiveRow(key="master.form")
        self.table_host = ft.Column(key="master.table")
        self.feedback = ViewFeedback(key="master.feedback")
        self.refresh_button = ft.Button(
            "查询", icon=ft.Icons.REFRESH, key="master.refresh", on_click=self.load
        )
        self.create_button = ft.Button(
            "新增", icon=ft.Icons.ADD, key="master.create", on_click=self.create
        )
        self.update_button = ft.Button(
            "保存修改",
            icon=ft.Icons.SAVE,
            disabled=True,
            key="master.update",
            on_click=self.update,
        )
        self.delete_button = ft.Button(
            "删除所选",
            icon=ft.Icons.DELETE_OUTLINE,
            disabled=True,
            key="master.delete",
            on_click=self.ask_delete,
        )
        self.root = ft.Column(
            controls=[
                ft.Text("基础数据", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("管理院系、专业、方向、教师、学生、学期和教室。"),
                ft.Row(
                    controls=[self.resource_picker, self.search, self.refresh_button], wrap=True
                ),
                self.feedback.control,
                self.form_host,
                ft.Row(
                    controls=[self.create_button, self.update_button, self.delete_button],
                    wrap=True,
                ),
                ft.Divider(),
                self.table_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="master.root",
        )
        self._build_form()
        self._render_rows()

    def _build_form(self) -> None:
        self.form = {
            name: ft.TextField(
                label=FIELD_LABELS.get(name, name),
                key=f"master.field.{name}",
                col={"xs": 12, "md": 6, "lg": 4},
            )
            for name in MASTER_RESOURCES[self.resource]
        }
        self.form_host.controls = list(self.form.values())

    def _payload(self, *, updating: bool = False) -> dict[str, Any] | None:
        payload: dict[str, Any] = {}
        valid = True
        for name, control in self.form.items():
            if updating and name in IMMUTABLE_ON_UPDATE[self.resource]:
                continue
            control.error = None
            raw = control.value.strip()
            if name in INTEGER_FIELDS:
                parsed = parse_int(control, FIELD_LABELS.get(name, name))
                if parsed is None:
                    valid = False
                else:
                    payload[name] = parsed
            elif name == "direction_ids":
                payload[name] = split_values(raw)
            elif name == "section_timetable":
                try:
                    timetable = json.loads(raw or "{}")
                    if not isinstance(timetable, dict):
                        raise TypeError
                    payload[name] = timetable
                except (TypeError, ValueError):
                    control.error = "请输入 JSON 对象"
                    valid = False
            else:
                payload[name] = raw
        if updating and self.selected is not None:
            payload["version"] = self.selected.get("version")
        return payload if valid else None

    def _select(self, row: dict[str, Any]) -> None:
        self.selected = row
        for name, control in self.form.items():
            value = row.get(name, "")
            if isinstance(value, list):
                control.value = ", ".join(str(item) for item in value)
            elif isinstance(value, dict):
                control.value = json.dumps(value, ensure_ascii=False)
            else:
                control.value = str(value)
        self.update_button.disabled = False
        self.delete_button.disabled = False
        self.feedback.show(f"已选择：{row.get('name') or row.get('code') or row.get('id')}")
        self._render_rows()
        update_control(self.root)

    def _select_handler(self, row: dict[str, Any]) -> Callable[[], None]:
        return lambda: self._select(row)

    def _render_rows(self) -> None:
        if self.state.loading:
            self.table_host.controls = [ft.ProgressRing(), ft.Text("正在加载……")]
            return
        if self.state.error:
            self.table_host.controls = [
                ft.Text(f"加载失败：{self.state.error}", color=ft.Colors.RED_700)
            ]
            return
        if not self.state.rows:
            self.table_host.controls = [ft.Text("暂无数据")]
            return
        columns = ("id", *MASTER_RESOURCES[self.resource])
        self.table_host.controls = [
            ft.Row(
                controls=[
                    ft.DataTable(
                        columns=[
                            ft.DataColumn(label=ft.Text(FIELD_LABELS.get(name, name)))
                            for name in columns
                        ],
                        rows=[
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(str(row.get(name, "")))) for name in columns
                                ],
                                on_select_change=self._select_handler(row),
                                selected=(
                                    self.selected is not None
                                    and row.get("id") == self.selected.get("id")
                                ),
                            )
                            for row in self.state.rows
                        ],
                        show_checkbox_column=True,
                        key="master.data",
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            ft.Text(f"当前页 {len(self.state.rows)} 条"),
        ]

    async def switch_resource(self) -> None:
        selected = self.resource_picker.value
        if selected not in MASTER_RESOURCES:
            return
        self.resource = selected
        self.selected = None
        self.state = DataTableState(search_fields=("code", "name"))
        self.update_button.disabled = True
        self.delete_button.disabled = True
        self._build_form()
        await self.load()

    async def load(self) -> None:
        self.feedback.clear()
        self.state.loading = True
        self.state.error = None
        self._render_rows()
        update_control(self.root)
        try:
            result = await self.workflow.list(self.resource, search=self.search.value.strip())
            items = result.get("items", [])
            self.state.rows = items if isinstance(items, list) else []
        except ApiError as error:
            self.state.error = error.message
            bind_api_error(error, {}, self.feedback)
        finally:
            self.state.loading = False
            self._render_rows()
            update_control(self.root)

    async def create(self) -> None:
        payload = self._payload()
        if payload is None:
            update_control(self.root)
            return
        await self._save(lambda: self.workflow.create(self.resource, payload), "新增成功")

    async def update(self) -> None:
        if self.selected is None:
            return
        payload = self._payload(updating=True)
        if payload is None:
            update_control(self.root)
            return
        resource_id = str(self.selected["id"])
        await self._save(
            lambda: self.workflow.update(self.resource, resource_id, payload), "修改成功"
        )

    async def _save(
        self,
        operation: Callable[[], Awaitable[dict[str, Any]]],
        success_message: str,
    ) -> None:
        buttons = (self.create_button, self.update_button, self.delete_button)
        set_busy(buttons, True)
        self.feedback.clear()
        clear_field_errors(self.form)
        update_control(self.root)
        try:
            await operation()
        except ApiError as error:
            bind_api_error(error, self.form, self.feedback)
        else:
            for control in self.form.values():
                control.value = ""
            self.selected = None
            await self.load()
            self.feedback.show(success_message)
        finally:
            set_busy(buttons, False)
            self.update_button.disabled = self.selected is None
            self.delete_button.disabled = self.selected is None
            update_control(self.root)

    def ask_delete(self) -> None:
        if self.selected is None:
            return
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title="确认删除",
                content=ft.Text("删除后无法从页面恢复，确定继续吗？"),
                actions=[
                    ft.Button("取消", on_click=self.page.pop_dialog),
                    ft.Button("删除", icon=ft.Icons.DELETE, on_click=self.delete),
                ],
            )
        )

    async def delete(self) -> None:
        if self.selected is None:
            return
        self.page.pop_dialog()
        try:
            await self.workflow.delete(self.resource, str(self.selected["id"]))
        except ApiError as error:
            bind_api_error(error, self.form, self.feedback)
        else:
            self.selected = None
            await self.load()
            self.feedback.show("删除成功")
        update_control(self.root)


def master_data_view(page: ft.Page, client: ApiClient) -> ft.Control:
    view = MasterDataView(page, client)
    page.run_task(view.load)
    return view.root
