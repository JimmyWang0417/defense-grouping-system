from __future__ import annotations

from datetime import datetime
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient


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


def audit_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("审计中心", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("审计记录只读且不可篡改。"),
            ft.ResponsiveRow(
                controls=[
                    ft.TextField(label="操作人", col={"xs": 12, "md": 4}),
                    ft.TextField(label="动作", col={"xs": 12, "md": 4}),
                    ft.TextField(label="对象类型/编号", col={"xs": 12, "md": 4}),
                    ft.TextField(label="时间范围", col={"xs": 12, "md": 4}),
                    ft.TextField(label="请求编号", col={"xs": 12, "md": 4}),
                ]
            ),
            ft.Button("查询", icon=ft.Icons.SEARCH),
        ]
    )
