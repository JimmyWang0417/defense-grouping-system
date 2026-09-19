from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    parse_int,
    set_busy,
    update_control,
)


class AuditWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def list(
        self,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        request_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        params = {
            "actor_id": actor_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "created_from": created_from.isoformat() if created_from else None,
            "created_to": created_to.isoformat() if created_to else None,
            "request_id": request_id,
            "page": page,
            "page_size": page_size,
        }
        return await self.client.request(
            "GET",
            "/api/v1/audit-logs",
            params={key: value for key, value in params.items() if value is not None},
        )


class AuditView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = AuditWorkflow(client)
        self.fields = {
            "actor_id": ft.TextField(label="操作人编号", key="audit.actor_id"),
            "action": ft.TextField(label="动作", key="audit.action"),
            "object_type": ft.TextField(label="对象类型", key="audit.object_type"),
            "object_id": ft.TextField(label="对象编号", key="audit.object_id"),
            "created_from": ft.TextField(label="开始时间（ISO 8601）", key="audit.created_from"),
            "created_to": ft.TextField(label="结束时间（ISO 8601）", key="audit.created_to"),
            "request_id": ft.TextField(label="请求编号", key="audit.request_id"),
        }
        self.page_number = ft.TextField(label="页码", value="1", key="audit.page", width=120)
        self.feedback = ViewFeedback(key="audit.feedback")
        self.table_host = ft.Column(key="audit.table")
        self.summary = ft.Text("尚未查询", key="audit.summary")
        self.query_button = ft.Button(
            "查询", icon=ft.Icons.SEARCH, key="audit.query", on_click=self.load
        )
        self.root = ft.Column(
            controls=[
                ft.Text("审计中心", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("审计记录只读，显示操作前后摘要和请求编号。"),
                ft.ResponsiveRow(controls=[*self.fields.values(), self.page_number]),
                self.query_button,
                self.feedback.control,
                self.summary,
                self.table_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="audit.root",
        )

    def _datetime_value(self, name: str) -> datetime | None:
        control = self.fields[name]
        raw = control.value.strip()
        control.error = None
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            control.error = "请输入 ISO 8601 时间"
            raise

    async def load(self) -> None:
        page_number = parse_int(self.page_number, "页码")
        if page_number is None or page_number < 1:
            self.page_number.error = "页码必须大于等于 1"
            update_control(self.root)
            return
        try:
            created_from = self._datetime_value("created_from")
            created_to = self._datetime_value("created_to")
        except ValueError:
            update_control(self.root)
            return
        set_busy((self.query_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            result = await self.workflow.list(
                actor_id=self.fields["actor_id"].value.strip() or None,
                action=self.fields["action"].value.strip() or None,
                object_type=self.fields["object_type"].value.strip() or None,
                object_id=self.fields["object_id"].value.strip() or None,
                created_from=created_from,
                created_to=created_to,
                request_id=self.fields["request_id"].value.strip() or None,
                page=page_number,
            )
        except ApiError as error:
            bind_api_error(error, self.fields, self.feedback)
        else:
            items = result.get("items", [])
            rows = items if isinstance(items, list) else []
            self.summary.value = (
                f"第 {result.get('page', page_number)} 页，"
                f"每页 {result.get('page_size', 50)} 条，共 {result.get('total', 0)} 条"
            )
            self._render_rows(rows)
        finally:
            set_busy((self.query_button,), False)
            update_control(self.root)

    def _render_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self.table_host.controls = [ft.Text("没有符合条件的审计记录")]
            return
        columns = (
            ("created_at", "时间"),
            ("actor_id", "操作人"),
            ("action", "动作"),
            ("object_type", "对象类型"),
            ("object_id", "对象编号"),
            ("request_id", "请求编号"),
            ("before_summary", "操作前"),
            ("after_summary", "操作后"),
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
                                ]
                            )
                            for row in rows
                        ],
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            )
        ]

    @staticmethod
    def _display(value: object) -> str:
        if isinstance(value, dict | list):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "")


def audit_view(page: ft.Page, client: ApiClient) -> ft.Control:
    view = AuditView(page, client)
    page.run_task(view.load)
    return view.root
