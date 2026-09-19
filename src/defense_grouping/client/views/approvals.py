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
from defense_grouping.client.session import SessionState


def available_exception_actions(
    exception: dict[str, Any], session: SessionState
) -> tuple[str, ...]:
    status = exception.get("status")
    requester_id = exception.get("requester_id")
    if status == "pending" and requester_id != session.user_id:
        return ("approve", "reject")
    if status in {"pending", "approved"} and requester_id == session.user_id:
        return ("revoke",)
    if status == "approved":
        return ("revoke",)
    return ()


class ApprovalWorkflow:
    def __init__(self, client: ApiClient, session: SessionState) -> None:
        self.client = client
        self.session = session

    async def list(self, activity_id: str) -> list[dict[str, Any]]:
        return await self.client.request_list(
            "GET", "/api/v1/exceptions", params={"activity_id": activity_id}
        )

    async def request_exception(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.request("POST", "/api/v1/exceptions", json=payload)

    async def act(self, exception: dict[str, Any], action: str) -> dict[str, Any]:
        if action not in available_exception_actions(exception, self.session):
            raise PermissionError("当前用户不能执行此审批操作")
        return await self.client.request("POST", f"/api/v1/exceptions/{exception['id']}/{action}")


class ApprovalsView:
    def __init__(self, page: ft.Page, client: ApiClient, session: SessionState) -> None:
        self.page = page
        self.session = session
        self.workflow = ApprovalWorkflow(client, session)
        self.rows: list[dict[str, Any]] = []
        self.selected: dict[str, Any] | None = None
        self.activity_id = ft.TextField(
            label="活动编号",
            value=session.selected_activity_id or "",
            key="approvals.activity_id",
            expand=True,
        )
        self.constraint_code = ft.Dropdown(
            label="约束类型",
            options=[
                ft.DropdownOption(key="advisor_conflict", text="导师回避"),
                ft.DropdownOption(key="course_conflict", text="课程冲突"),
                ft.DropdownOption(key="leave_conflict", text="请假冲突"),
                ft.DropdownOption(key="workload_limit", text="教师工作量上限"),
            ],
            key="approvals.constraint_code",
        )
        self.subject_type = ft.Dropdown(
            label="对象范围",
            options=[
                ft.DropdownOption(key="teacher_student", text="教师与学生"),
                ft.DropdownOption(key="person_slot", text="人员与时段"),
                ft.DropdownOption(key="teacher", text="教师"),
            ],
            key="approvals.subject_type",
        )
        self.form = {
            "teacher_id": ft.TextField(label="教师编号", key="approvals.teacher_id"),
            "student_id": ft.TextField(label="学生编号", key="approvals.student_id"),
            "person_id": ft.TextField(label="人员编号", key="approvals.person_id"),
            "slot_id": ft.TextField(label="时段编号", key="approvals.slot_id"),
            "reason": ft.TextField(
                label="申请理由（至少 10 个字符）",
                multiline=True,
                key="approvals.reason",
            ),
            "expires_at": ft.TextField(
                label="失效时间（ISO 8601，含时区）", key="approvals.expires_at"
            ),
        }
        self.feedback = ViewFeedback(key="approvals.feedback")
        self.table_host = ft.Column(key="approvals.table")
        self.load_button = ft.Button(
            "查询", icon=ft.Icons.REFRESH, key="approvals.load", on_click=self.load
        )
        self.create_button = ft.Button(
            "提交申请",
            icon=ft.Icons.ADD,
            key="approvals.create",
            on_click=self.create,
        )
        self.approve_button = self._action_button("批准", "approve", ft.Icons.CHECK)
        self.reject_button = self._action_button("拒绝", "reject", ft.Icons.CLOSE)
        self.revoke_button = self._action_button("撤销", "revoke", ft.Icons.UNDO)
        self.root = ft.Column(
            controls=[
                ft.Text("例外审批", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("例外必须精确到具体约束与人员/时段，不能整体关闭规则。"),
                ft.Row(controls=[self.activity_id, self.load_button], wrap=True),
                self.feedback.control,
                ft.ResponsiveRow(
                    controls=[self.constraint_code, self.subject_type, *self.form.values()]
                ),
                self.create_button,
                ft.Divider(),
                self.table_host,
                ft.Row(
                    controls=[self.approve_button, self.reject_button, self.revoke_button],
                    wrap=True,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            key="approvals.root",
        )
        self._sync_actions()
        self._render_rows()

    def _action_button(self, label: str, action: str, icon: ft.IconData) -> ft.Button:
        async def run() -> None:
            await self.act(action)

        return ft.Button(
            label,
            icon=icon,
            disabled=True,
            key=f"approvals.{action}",
            on_click=run,
        )

    def _sync_actions(self) -> None:
        actions = available_exception_actions(self.selected, self.session) if self.selected else ()
        self.approve_button.disabled = "approve" not in actions
        self.reject_button.disabled = "reject" not in actions
        self.revoke_button.disabled = "revoke" not in actions

    def _select_handler(self, row: dict[str, Any]) -> Callable[[], None]:
        return lambda: self.select(row)

    def select(self, exception: dict[str, Any]) -> None:
        self.selected = exception
        self._sync_actions()
        self.feedback.show(f"已选择例外申请：{exception.get('id')}")
        self._render_rows()
        update_control(self.root)

    def _render_rows(self) -> None:
        if not self.rows:
            self.table_host.controls = [ft.Text("暂无例外申请")]
            return
        columns = (
            ("id", "申请编号"),
            ("constraint_code", "约束"),
            ("subject_type", "范围"),
            ("requester_id", "申请人"),
            ("reason", "理由"),
            ("expires_at", "失效时间"),
            ("status", "状态"),
        )
        self.table_host.controls = [
            ft.Row(
                controls=[
                    ft.DataTable(
                        columns=[ft.DataColumn(label=label) for _name, label in columns],
                        rows=[
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(str(row.get(name, ""))))
                                    for name, _label in columns
                                ],
                                selected=(
                                    self.selected is not None
                                    and self.selected.get("id") == row.get("id")
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

    async def load(self) -> None:
        activity_id = self.activity_id.value.strip() or self.session.selected_activity_id
        if not activity_id:
            self.activity_id.error = "请选择或输入活动编号"
            update_control(self.root)
            return
        set_busy((self.load_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            self.rows = await self.workflow.list(activity_id)
        except ApiError as error:
            bind_api_error(error, {"activity_id": self.activity_id}, self.feedback)
        else:
            self.selected = None
            self._sync_actions()
            self._render_rows()
        finally:
            set_busy((self.load_button,), False)
            update_control(self.root)

    async def create(self) -> None:
        activity_id = self.activity_id.value.strip() or self.session.selected_activity_id
        payload: dict[str, Any] = {
            "activity_id": activity_id,
            "constraint_code": self.constraint_code.value,
            "subject_type": self.subject_type.value,
            **{name: control.value.strip() or None for name, control in self.form.items()},
        }
        payload["reason"] = self.form["reason"].value.strip()
        payload["expires_at"] = self.form["expires_at"].value.strip()
        set_busy((self.create_button,), True)
        update_control(self.root)
        fields: dict[str, ft.TextField | ft.Dropdown] = {
            "activity_id": self.activity_id,
            "constraint_code": self.constraint_code,
            "subject_type": self.subject_type,
            **self.form,
        }
        try:
            await self.workflow.request_exception(payload)
        except ApiError as error:
            bind_api_error(error, fields, self.feedback)
        else:
            self.feedback.show("例外申请已提交")
            await self.load()
        finally:
            set_busy((self.create_button,), False)
            update_control(self.root)

    async def act(self, action: str) -> None:
        if self.selected is None:
            return
        try:
            await self.workflow.act(self.selected, action)
        except PermissionError as error:
            self.feedback.show(str(error), error=True)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            labels = {"approve": "批准", "reject": "拒绝", "revoke": "撤销"}
            self.feedback.show(f"已{labels[action]}该申请")
            await self.load()
        update_control(self.root)


def approvals_view(page: ft.Page, client: ApiClient, session: SessionState) -> ft.Control:
    view = ApprovalsView(page, client, session)
    if session.selected_activity_id:
        page.run_task(view.load)
    return view.root
