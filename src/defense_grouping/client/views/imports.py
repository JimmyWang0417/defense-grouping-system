from __future__ import annotations

from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient

IMPORT_KINDS = ("teachers", "students", "occupancies", "leaves", "rooms", "slots")


class ImportWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def download_template(self, kind: str) -> bytes:
        if kind not in IMPORT_KINDS:
            raise ValueError("未知导入模板")
        return await self.client.request_bytes("GET", f"/api/v1/imports/templates/{kind}")

    async def preflight(
        self,
        kind: str,
        filename: str,
        content: bytes,
        *,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.request(
            "POST",
            f"/api/v1/imports/{kind}/preflight",
            params={"department_id": department_id} if department_id else {},
            files={
                "file": (
                    filename,
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    async def preview(self, batch_id: str) -> dict[str, Any]:
        return await self.client.request("GET", f"/api/v1/imports/{batch_id}")

    async def confirm(self, batch_id: str) -> dict[str, Any]:
        return await self.client.request("POST", f"/api/v1/imports/{batch_id}/confirm")


def imports_view(_client: ApiClient) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("数据导入", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("下载标准模板，上传 .xlsx 后先预检，确认后才写入。"),
            ft.Dropdown(
                label="模板类型",
                options=[ft.DropdownOption(key=kind, text=kind) for kind in IMPORT_KINDS],
                width=300,
            ),
            ft.Row(
                controls=[
                    ft.Button("下载模板", icon=ft.Icons.DOWNLOAD),
                    ft.Button("选择文件并预检", icon=ft.Icons.UPLOAD_FILE),
                    ft.Button("确认导入", icon=ft.Icons.CHECK, disabled=True),
                ],
                wrap=True,
            ),
            ft.Text("预检结果：新建 0 / 更新 0 / 不变 0；行、列、单元格错误将在此定位。"),
        ]
    )
