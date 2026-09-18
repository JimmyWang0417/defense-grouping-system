from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import flet as ft


@dataclass
class DataTableState:
    rows: list[dict[str, Any]] = field(default_factory=list)
    search_fields: tuple[str, ...] = ()
    search: str = ""
    filters: dict[str, object] = field(default_factory=dict)
    sort_key: str = "id"
    descending: bool = False
    page: int = 1
    page_size: int = 25
    selected_ids: set[str] = field(default_factory=set)
    loading: bool = False
    error: str | None = None

    def _filtered_rows(self) -> list[dict[str, Any]]:
        query = self.search.casefold().strip()
        rows = [
            row
            for row in self.rows
            if not query
            or any(
                query in str(row.get(field_name, "")).casefold()
                for field_name in self.search_fields
            )
        ]
        rows = [
            row
            for row in rows
            if all(row.get(field_name) == value for field_name, value in self.filters.items())
        ]

        def key(row: dict[str, Any]) -> tuple[str, str]:
            return (
                str(row.get(self.sort_key, "")).casefold(),
                str(row.get("id", "")).casefold(),
            )

        return sorted(rows, key=key, reverse=self.descending)

    @property
    def total_filtered(self) -> int:
        return len(self._filtered_rows())

    @property
    def total_pages(self) -> int:
        return max(1, (self.total_filtered + self.page_size - 1) // self.page_size)

    @property
    def view_state(self) -> str:
        if self.loading:
            return "loading"
        if self.error is not None:
            return "error"
        if not self.rows:
            return "empty"
        return "data"

    def visible_rows(self) -> list[dict[str, Any]]:
        rows = self._filtered_rows()
        active_page = min(max(self.page, 1), self.total_pages)
        start = (active_page - 1) * self.page_size
        return rows[start : start + self.page_size]

    def toggle_selected(self, row_id: str) -> None:
        if row_id in self.selected_ids:
            self.selected_ids.remove(row_id)
        else:
            self.selected_ids.add(row_id)


@dataclass
class DirtyFormState:
    initial: dict[str, object]
    values: dict[str, object] = field(init=False)
    field_errors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = dict(self.initial)

    @property
    def dirty(self) -> bool:
        return self.values != self.initial

    @property
    def can_leave(self) -> bool:
        return not self.dirty

    def set_value(self, field_name: str, value: object) -> None:
        self.values[field_name] = value
        self.field_errors.pop(field_name, None)

    def bind_api_errors(self, errors: dict[str, str]) -> None:
        self.field_errors = dict(errors)

    def mark_saved(self) -> None:
        self.initial = dict(self.values)
        self.field_errors.clear()

    def discard_changes(self) -> None:
        self.values = dict(self.initial)
        self.field_errors.clear()


def render_data_table(
    state: DataTableState,
    columns: tuple[tuple[str, str], ...],
) -> ft.Control:
    if state.loading:
        return ft.Column(controls=[ft.ProgressRing(), ft.Text("正在加载……")])
    if state.error is not None:
        return ft.Text(f"加载失败：{state.error}", color=ft.Colors.RED_600, selectable=True)
    rows = state.visible_rows()
    if not rows:
        return ft.Text("暂无数据")
    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Text(label, weight=ft.FontWeight.BOLD, expand=True)
                    for _key, label in columns
                ]
            ),
            *[
                ft.Row(
                    controls=[
                        ft.Text(str(row.get(key, "")), expand=True, selectable=True)
                        for key, _label in columns
                    ]
                )
                for row in rows
            ],
            ft.Text(f"第 {state.page}/{state.total_pages} 页，共 {state.total_filtered} 条"),
        ]
    )


class DirtyFormRouteGuard:
    """Intercept Flet view-pop events until a dirty form is explicitly discarded."""

    def __init__(self, page: ft.Page, form: DirtyFormState) -> None:
        self.page = page
        self.form = form
        self._previous = page.on_view_pop
        self._pending_route: str | None = None

    def install(self) -> None:
        self.page.on_view_pop = self._on_view_pop

    def uninstall(self) -> None:
        self.page.on_view_pop = self._previous

    def _on_view_pop(self, event: ft.ViewPopEvent) -> None:
        if self.form.can_leave:
            self._continue(event.route)
            return
        self._pending_route = event.route
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title="放弃未保存更改？",
                content=ft.Text("当前表单尚未保存，离开后将无法恢复。"),
                actions=[
                    ft.Button("继续编辑", on_click=self._cancel),
                    ft.Button("放弃并离开", on_click=self._discard),
                ],
            )
        )

    def _cancel(self) -> None:
        self._pending_route = None
        self.page.pop_dialog()

    def _discard(self) -> None:
        route = self._pending_route
        self._pending_route = None
        self.form.discard_changes()
        self.page.pop_dialog()
        if route is not None:
            self._continue(route)

    def _continue(self, route: str) -> None:
        self.page.navigate(route)
