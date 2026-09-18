import flet as ft

from defense_grouping.client.api_client import ApiError


def format_api_error(error: ApiError) -> str:
    field_details = "；".join(f"{field}：{message}" for field, message in error.fields.items())
    details = f"（{field_details}）" if field_details else ""
    request = f" 请求编号：{error.request_id}" if error.request_id != "-" else ""
    return f"{error.message}{details}{request}"


def error_banner(error: ApiError) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.RED_600),
                ft.Text(format_api_error(error), selectable=True, expand=True),
            ]
        ),
        padding=12,
        bgcolor=ft.Colors.RED_50,
        border_radius=8,
    )


def status_view(code: int, title: str, message: str) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(str(code), size=56, weight=ft.FontWeight.BOLD),
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
                ft.Text(message, selectable=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
        padding=32,
    )
