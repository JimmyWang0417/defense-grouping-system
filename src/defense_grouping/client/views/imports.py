from __future__ import annotations

import asyncio
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    set_busy,
    update_control,
)

IMPORT_KINDS = ("student", "teacher", "course", "leave", "room", "slot")
IMPORT_LABELS = {
    "student": "学生",
    "teacher": "教师",
    "course": "课程占用",
    "leave": "请假记录",
    "room": "教室",
    "slot": "答辩时段",
}


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


class ImportsView:
    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.workflow = ImportWorkflow(client)
        self.file_picker = ft.FilePicker()
        self.filename: str | None = None
        self.file_content: bytes | None = None
        self.batch_id: str | None = None
        self.preview: dict[str, Any] | None = None
        self.kind = ft.Dropdown(
            label="模板类型",
            value="student",
            options=[
                ft.DropdownOption(key=kind, text=IMPORT_LABELS[kind]) for kind in IMPORT_KINDS
            ],
            width=220,
            key="imports.kind",
        )
        self.department_id = ft.TextField(
            label="院系编号（课程、请假、学生、教师必填）",
            key="imports.department_id",
            width=420,
        )
        self.selected_file = ft.Text("尚未选择文件", key="imports.selected_file")
        self.summary = ft.Text("尚未预检", key="imports.summary")
        self.issue_host = ft.Column(key="imports.issues")
        self.feedback = ViewFeedback(key="imports.feedback")
        self.download_button = ft.Button(
            "下载模板",
            icon=ft.Icons.DOWNLOAD,
            key="imports.download",
            on_click=self.save_template,
        )
        self.choose_button = ft.Button(
            "选择文件并预检",
            icon=ft.Icons.UPLOAD_FILE,
            key="imports.choose",
            on_click=self.choose_and_preflight,
        )
        self.confirm_button = ft.Button(
            "确认导入",
            icon=ft.Icons.CHECK,
            disabled=True,
            key="imports.confirm",
            on_click=self.confirm,
        )
        self.root = ft.Column(
            controls=[
                ft.Text("数据导入", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("下载标准模板，上传 .xlsx 后先预检，确认后才写入。"),
                ft.ResponsiveRow(
                    controls=[
                        self.kind,
                        self.department_id,
                        self.download_button,
                        self.choose_button,
                        self.confirm_button,
                    ]
                ),
                self.selected_file,
                self.feedback.control,
                self.summary,
                self.issue_host,
            ],
            scroll=ft.ScrollMode.AUTO,
            key="imports.root",
        )

    def set_selected_file(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.file_content = content
        self.selected_file.value = f"已选择：{filename}（{len(content)} 字节）"
        self.batch_id = None
        self.preview = None
        self.confirm_button.disabled = True

    async def choose_file(self) -> bool:
        files = await self.file_picker.pick_files(
            dialog_title="选择 Excel 文件",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx"],
            allow_multiple=False,
            with_data=True,
        )
        if not files:
            return False
        selected = files[0]
        content = selected.bytes
        if not isinstance(content, bytes):
            self.feedback.show("没有读取到文件内容，请重新选择文件", error=True)
            update_control(self.root)
            return False
        self.set_selected_file(selected.name, content)
        update_control(self.root)
        return True

    async def choose_and_preflight(self) -> None:
        if await self.choose_file():
            await self.run_preflight()

    async def run_preflight(self) -> None:
        if self.filename is None or self.file_content is None:
            self.feedback.show("请先选择 .xlsx 文件", error=True)
            update_control(self.root)
            return
        set_busy((self.download_button, self.choose_button, self.confirm_button), True)
        self.feedback.clear()
        self.issue_host.controls = []
        self.summary.value = "正在预检……"
        update_control(self.root)
        try:
            result = await self.workflow.preflight(
                self.kind.value or "student",
                self.filename,
                self.file_content,
                department_id=self.department_id.value.strip() or None,
            )
            self.batch_id = str(result["id"])
            await self.poll_preview()
        except ApiError as error:
            bind_api_error(error, {"department_id": self.department_id}, self.feedback)
        finally:
            set_busy((self.download_button, self.choose_button), False)
            self.confirm_button.disabled = not self._can_confirm()
            update_control(self.root)

    async def poll_preview(self) -> None:
        if self.batch_id is None:
            return
        for _attempt in range(120):
            preview = await self.workflow.preview(self.batch_id)
            self.preview = preview
            self._render_preview()
            update_control(self.root)
            if preview.get("status") in {"ready", "failed", "confirmed"}:
                return
            await asyncio.sleep(0.25)
        self.feedback.show("预检等待超时，请稍后刷新后重试", error=True)

    def _can_confirm(self) -> bool:
        if self.preview is None or self.preview.get("status") != "ready":
            return False
        issues = self.preview.get("issues", [])
        return not any(
            isinstance(issue, dict) and issue.get("severity") == "error" for issue in issues
        )

    def _render_preview(self) -> None:
        if self.preview is None:
            return
        self.summary.value = (
            f"状态：{self.preview.get('status', '-')}；"
            f"新建 {self.preview.get('creates', 0)} / "
            f"更新 {self.preview.get('updates', 0)} / "
            f"不变 {self.preview.get('unchanged', 0)}"
        )
        issues = self.preview.get("issues", [])
        if not isinstance(issues, list) or not issues:
            self.issue_host.controls = [ft.Text("没有发现格式或数据错误")]
            return
        self.issue_host.controls = [
            ft.DataTable(
                columns=[
                    ft.DataColumn(label="工作表"),
                    ft.DataColumn(label="行"),
                    ft.DataColumn(label="字段"),
                    ft.DataColumn(label="级别"),
                    ft.DataColumn(label="说明"),
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(issue.get("sheet", "")))),
                            ft.DataCell(ft.Text(str(issue.get("row", "")))),
                            ft.DataCell(ft.Text(str(issue.get("field", "")))),
                            ft.DataCell(ft.Text(str(issue.get("severity", "")))),
                            ft.DataCell(ft.Text(str(issue.get("message", "")))),
                        ]
                    )
                    for issue in issues
                    if isinstance(issue, dict)
                ],
            )
        ]

    async def confirm(self) -> None:
        if self.batch_id is None or not self._can_confirm():
            return
        set_busy((self.download_button, self.choose_button, self.confirm_button), True)
        update_control(self.root)
        try:
            result = await self.workflow.confirm(self.batch_id)
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        else:
            self.preview = result
            self._render_preview()
            self.feedback.show("导入完成")
        finally:
            set_busy((self.download_button, self.choose_button), False)
            self.confirm_button.disabled = True
            update_control(self.root)

    async def save_template(self) -> None:
        set_busy((self.download_button,), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            kind = self.kind.value or "student"
            content = await self.workflow.download_template(kind)
            destination = await self.file_picker.save_file(
                dialog_title="保存导入模板",
                file_name=f"{IMPORT_LABELS[kind]}导入模板.xlsx",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx"],
                src_bytes=content,
            )
            if destination:
                self.feedback.show(f"模板已保存到：{destination}")
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
        finally:
            set_busy((self.download_button,), False)
            update_control(self.root)


def imports_view(page: ft.Page, client: ApiClient) -> ft.Control:
    return ImportsView(page, client).root
