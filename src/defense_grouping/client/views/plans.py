from __future__ import annotations

import json
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    set_busy,
    split_values,
    update_control,
)
from defense_grouping.client.session import SessionState


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
        return await self.client.request_list("GET", f"/api/v1/activities/{activity_id}/plans")

    async def detail(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("GET", f"/api/v1/plans/{plan_id}")

    async def copy(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/copy")

    async def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        return await self.client.request("GET", f"/api/v1/plans/{left_id}/compare/{right_id}")

    async def adjust_group(
        self, plan_id: str, group_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.client.request(
            "PATCH", f"/api/v1/plans/{plan_id}/groups/{group_id}", json=payload
        )

    async def validate(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/validate")

    async def publish(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/publish")

    async def withdraw(self, plan_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/plans/{plan_id}/withdraw")

    async def export(self, plan_id: str) -> bytes:
        return await self.client.request_bytes("GET", f"/api/v1/plans/{plan_id}/export")


class PlansView:
    def __init__(self, page: ft.Page, client: ApiClient, session: SessionState) -> None:
        self.page = page
        self.session = session
        self.workflow = PlanWorkflow(client)
        self.file_picker = ft.FilePicker()
        self.plans: list[dict[str, Any]] = []
        self.selected_plan: dict[str, Any] | None = None
        self.selected_group: dict[str, Any] | None = None
        self.activity_id = ft.TextField(
            label="活动编号",
            value=session.selected_activity_id or "",
            key="plans.activity_id",
            expand=True,
        )
        self.load_button = ft.Button(
            "读取方案", icon=ft.Icons.REFRESH, key="plans.load", on_click=self.load
        )
        self.plan_picker = ft.Dropdown(
            label="方案版本",
            key="plans.plan",
            width=360,
            on_select=self.select_plan_from_picker,
        )
        self.status_text = ft.Text("尚未选择方案", key="plans.status")
        self.detail_host = ft.Column(key="plans.detail")
        self.feedback = ViewFeedback(key="plans.feedback")
        self.other_plan_id = ft.TextField(label="对比方案编号", key="plans.compare_id", width=360)
        self.comparison_host = ft.Column(key="plans.comparison")
        self.copy_button = self._button(
            "复制为草稿", ft.Icons.CONTENT_COPY, "plans.copy", self.copy
        )
        self.validate_button = self._button(
            "重新校验", ft.Icons.RULE, "plans.validate", self.validate
        )
        self.publish_button = self._button(
            "发布", ft.Icons.PUBLISH, "plans.publish", self.ask_publish
        )
        self.withdraw_button = self._button(
            "撤回", ft.Icons.UNPUBLISHED, "plans.withdraw", self.ask_withdraw
        )
        self.export_button = self._button(
            "导出 Excel", ft.Icons.DOWNLOAD, "plans.export", self.export
        )
        self.compare_button = self._button(
            "版本对比", ft.Icons.COMPARE_ARROWS, "plans.compare", self.compare
        )
        self.group_picker = ft.Dropdown(
            label="要调整的答辩组",
            key="plans.group",
            width=360,
            on_select=self.select_group,
        )
        self.adjust_fields = {
            "student_ids": ft.TextField(label="学生编号（逗号分隔）", key="plans.adjust.students"),
            "teacher_ids": ft.TextField(label="教师编号（逗号分隔）", key="plans.adjust.teachers"),
            "chair_id": ft.TextField(label="组长编号", key="plans.adjust.chair"),
            "slot_id": ft.TextField(label="时段编号", key="plans.adjust.slot"),
            "room_id": ft.TextField(label="教室编号", key="plans.adjust.room"),
        }
        self.adjust_button = self._button(
            "保存人工调整", ft.Icons.SAVE, "plans.adjust", self.adjust_group
        )
        self.root = ft.Column(
            controls=[
                ft.Text("方案管理", size=28, weight=ft.FontWeight.BOLD),
                ft.Row(controls=[self.activity_id, self.load_button], wrap=True),
                self.plan_picker,
                self.feedback.control,
                self.status_text,
                ft.Row(
                    controls=[
                        self.copy_button,
                        self.validate_button,
                        self.publish_button,
                        self.withdraw_button,
                        self.export_button,
                    ],
                    wrap=True,
                ),
                self.detail_host,
                ft.Divider(),
                ft.Text("版本对比", size=20, weight=ft.FontWeight.BOLD),
                ft.Row(controls=[self.other_plan_id, self.compare_button], wrap=True),
                self.comparison_host,
                ft.Divider(),
                ft.Text("人工调整草稿方案", size=20, weight=ft.FontWeight.BOLD),
                self.group_picker,
                ft.ResponsiveRow(controls=list(self.adjust_fields.values())),
                self.adjust_button,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="plans.root",
        )
        self._sync_actions()

    @staticmethod
    def _button(label: str, icon: ft.IconData, key: str, handler: Any) -> ft.Button:
        return ft.Button(label, icon=icon, key=key, on_click=handler)

    @property
    def action_buttons(self) -> tuple[ft.Button, ...]:
        return (
            self.copy_button,
            self.validate_button,
            self.publish_button,
            self.withdraw_button,
            self.export_button,
            self.compare_button,
            self.adjust_button,
        )

    def _sync_actions(self) -> None:
        status = self.selected_plan.get("status") if self.selected_plan else None
        has_plan = self.selected_plan is not None
        self.copy_button.disabled = not has_plan
        self.validate_button.disabled = status not in {"draft", "ready"}
        self.publish_button.disabled = status != "ready"
        self.withdraw_button.disabled = status != "published"
        self.export_button.disabled = not has_plan
        self.compare_button.disabled = not has_plan
        self.adjust_button.disabled = status != "draft" or self.selected_group is None

    async def load(self) -> None:
        activity_id = self.activity_id.value.strip() or self.session.selected_activity_id
        if not activity_id:
            self.activity_id.error = "请选择或输入活动编号"
            update_control(self.root)
            return
        self.activity_id.error = None
        set_busy((self.load_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            self.plans = await self.workflow.list(activity_id)
        except ApiError as error:
            bind_api_error(error, {"activity_id": self.activity_id}, self.feedback)
        else:
            self.plan_picker.options = [
                ft.DropdownOption(
                    key=str(plan["id"]),
                    text=f"版本 {plan.get('version_number', '-')} · {plan.get('status', '-')}",
                )
                for plan in self.plans
            ]
            if self.plans:
                self.plan_picker.value = str(self.plans[0]["id"])
                await self._load_detail(str(self.plans[0]["id"]))
            else:
                self.selected_plan = None
                self.status_text.value = "该活动还没有方案"
                self.detail_host.controls = []
                self._sync_actions()
        finally:
            set_busy((self.load_button,), False)
            update_control(self.root)

    async def select_plan_from_picker(self) -> None:
        if self.plan_picker.value:
            await self._load_detail(self.plan_picker.value)

    def select_plan(self, plan: dict[str, Any]) -> None:
        self.selected_plan = plan
        self._render_detail()

    async def _load_detail(self, plan_id: str) -> None:
        try:
            plan = await self.workflow.detail(plan_id)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
            return
        self.select_plan(plan)
        update_control(self.root)

    def _render_detail(self) -> None:
        if self.selected_plan is None:
            return
        plan = self.selected_plan
        self.status_text.value = (
            f"方案 {plan.get('id')} · 版本 {plan.get('version_number')} · 状态 {plan.get('status')}"
        )
        groups = plan.get("groups", [])
        if not isinstance(groups, list):
            groups = []
        self.group_picker.options = [
            ft.DropdownOption(key=str(group["id"]), text=str(group.get("code", group["id"])))
            for group in groups
            if isinstance(group, dict) and "id" in group
        ]
        metrics = json.dumps(plan.get("quality_metrics", {}), ensure_ascii=False, indent=2)
        exceptions = json.dumps(plan.get("exception_snapshot", []), ensure_ascii=False, indent=2)
        controls: list[ft.Control] = [
            ft.Text("质量指标", weight=ft.FontWeight.BOLD),
            ft.Text(metrics, selectable=True),
            ft.Text("已用例外", weight=ft.FontWeight.BOLD),
            ft.Text(exceptions, selectable=True),
            ft.Text("答辩组", weight=ft.FontWeight.BOLD),
        ]
        controls.extend(
            ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                f"{group.get('code', '-')} · 时段 {group.get('slot_id', '-')} · "
                                f"教室 {group.get('room_id', '-')}"
                            ),
                            ft.Text("学生：" + ", ".join(map(str, group.get("student_ids", [])))),
                            ft.Text("教师：" + ", ".join(map(str, group.get("teacher_ids", [])))),
                            ft.Text(f"组长：{group.get('chair_id', '-')}"),
                        ]
                    ),
                    padding=12,
                )
            )
            for group in groups
            if isinstance(group, dict)
        )
        self.detail_host.controls = controls
        self.selected_group = None
        self.group_picker.value = None
        self._sync_actions()

    def select_group(self) -> None:
        if self.selected_plan is None or not self.group_picker.value:
            return
        groups = self.selected_plan.get("groups", [])
        self.selected_group = next(
            (
                group
                for group in groups
                if isinstance(group, dict) and str(group.get("id")) == self.group_picker.value
            ),
            None,
        )
        if self.selected_group is None:
            return
        mapping = {
            "student_ids": ", ".join(map(str, self.selected_group.get("student_ids", []))),
            "teacher_ids": ", ".join(map(str, self.selected_group.get("teacher_ids", []))),
            "chair_id": str(self.selected_group.get("chair_id", "")),
            "slot_id": str(self.selected_group.get("slot_id", "")),
            "room_id": str(self.selected_group.get("room_id", "")),
        }
        for name, value in mapping.items():
            self.adjust_fields[name].value = value
        self._sync_actions()
        update_control(self.root)

    async def copy(self) -> None:
        await self._apply_plan_action("copy", "已复制为新的草稿方案")

    async def validate(self) -> None:
        await self._apply_plan_action("validate", "校验完成")

    def ask_publish(self) -> None:
        self._show_confirmation("确认发布", "发布后教师可以看到安排。", self.publish)

    def ask_withdraw(self) -> None:
        self._show_confirmation("确认撤回", "撤回后教师将无法继续查看该版本。", self.withdraw)

    def _show_confirmation(self, title: str, message: str, handler: Any) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=title,
                content=ft.Text(message),
                actions=[
                    ft.Button("取消", on_click=self.page.pop_dialog),
                    ft.Button("确定", on_click=handler),
                ],
            )
        )

    async def publish(self, *, confirmed: bool = True) -> None:
        if confirmed:
            self.page.pop_dialog()
            await self._apply_plan_action("publish", "方案已发布")

    async def withdraw(self, *, confirmed: bool = True) -> None:
        if confirmed:
            self.page.pop_dialog()
            await self._apply_plan_action("withdraw", "方案已撤回")

    async def _apply_plan_action(self, action: str, success_message: str) -> None:
        if self.selected_plan is None:
            return
        set_busy(self.action_buttons, True)
        update_control(self.root)
        try:
            method = getattr(self.workflow, action)
            result = await method(str(self.selected_plan["id"]))
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self.select_plan(result)
            self.plan_picker.value = str(result["id"])
            self.feedback.show(success_message)
        finally:
            self._sync_actions()
            update_control(self.root)

    async def compare(self) -> None:
        if self.selected_plan is None:
            return
        other_id = self.other_plan_id.value.strip()
        if not other_id:
            self.other_plan_id.error = "请输入要对比的方案编号"
            update_control(self.root)
            return
        try:
            comparison = await self.workflow.compare(str(self.selected_plan["id"]), other_id)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
            update_control(self.root)
            return
        summary = summarize_comparison(comparison)
        self.comparison_host.controls = [
            ft.Text(f"学生移动：{summary['student_moves']}"),
            ft.Text(f"教师变化：{summary['teacher_changes']}"),
            ft.Text(f"时段/教室变化：{summary['resource_changes']}"),
            ft.Text(f"目标分变化：{summary['score_deltas']}"),
            ft.Text(f"例外使用量变化：{summary['exception_use_delta']}"),
            ft.Text(json.dumps(comparison, ensure_ascii=False, indent=2), selectable=True),
        ]
        update_control(self.root)

    async def adjust_group(self) -> None:
        if self.selected_plan is None or self.selected_group is None:
            return
        payload: dict[str, Any] = {"version": self.selected_group.get("version")}
        for name, control in self.adjust_fields.items():
            raw = control.value.strip()
            if name in {"student_ids", "teacher_ids"}:
                payload[name] = split_values(raw)
            elif raw:
                payload[name] = raw
        try:
            result = await self.workflow.adjust_group(
                str(self.selected_plan["id"]), str(self.selected_group["id"]), payload
            )
        except ApiError as error:
            bind_api_error(error, self.adjust_fields, self.feedback)
        else:
            self.select_plan(result)
            self.feedback.show("人工调整已保存，发布前请重新校验")
        update_control(self.root)

    async def export(self) -> None:
        if self.selected_plan is None:
            return
        try:
            content = await self.workflow.export(str(self.selected_plan["id"]))
            destination = await self.file_picker.save_file(
                dialog_title="导出答辩方案",
                file_name=f"答辩方案-v{self.selected_plan.get('version_number', '-')}.xlsx",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx"],
                src_bytes=content,
            )
            if destination:
                self.feedback.show(f"已导出到：{destination}")
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        update_control(self.root)


def plans_view(page: ft.Page, client: ApiClient, session: SessionState) -> ft.Control:
    view = PlansView(page, client, session)
    if session.selected_activity_id:
        page.run_task(view.load)
    return view.root
