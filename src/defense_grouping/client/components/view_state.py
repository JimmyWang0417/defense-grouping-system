from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.session import SessionState

FormControl = ft.TextField | ft.Dropdown


def set_field_error(control: FormControl, message: str | None) -> None:
    if isinstance(control, ft.TextField):
        control.error = message
    else:
        control.error_text = message


@dataclass(frozen=True)
class ActivityOption:
    id: str
    name: str


@dataclass
class ActivityContext:
    session: SessionState
    options: list[ActivityOption] = field(default_factory=list)
    loaded: bool = False
    loading: bool = False
    error: str | None = None

    async def load(self, client: ApiClient) -> None:
        if self.loading:
            return
        self.loading = True
        self.error = None
        try:
            payload = await client.request(
                "GET",
                "/api/v1/activities",
                params={"page": 1, "page_size": 100, "sort": "-created_at"},
            )
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise TypeError("活动列表格式无效")
            self.options = [
                ActivityOption(id=str(item["id"]), name=str(item["name"]))
                for item in items
                if isinstance(item, dict) and "id" in item and "name" in item
            ]
            valid_ids = {option.id for option in self.options}
            if self.session.selected_activity_id not in valid_ids:
                self.session.selected_activity_id = self.options[0].id if self.options else None
            self.loaded = True
        except (ApiError, TypeError) as error:
            self.error = error.message if isinstance(error, ApiError) else str(error)
        finally:
            self.loading = False

    def select(self, activity_id: str | None) -> None:
        self.session.selected_activity_id = activity_id or None


class ViewFeedback:
    def __init__(self, *, key: str = "feedback") -> None:
        self.text = ft.Text(selectable=True)
        self.control = ft.Container(
            content=self.text,
            visible=False,
            padding=10,
            border_radius=8,
            key=key,
        )
        self.message = ""
        self.error = False

    def clear(self) -> None:
        self.message = ""
        self.error = False
        self.text.value = ""
        self.control.visible = False

    def show(self, message: str, *, error: bool = False) -> None:
        self.message = message
        self.error = error
        self.text.value = message
        self.text.color = ft.Colors.RED_700 if error else ft.Colors.GREEN_800
        self.control.bgcolor = ft.Colors.RED_50 if error else ft.Colors.GREEN_50
        self.control.visible = True


def set_busy(buttons: Iterable[ft.Button], busy: bool) -> None:
    for button in buttons:
        button.disabled = busy


def clear_field_errors(fields: Mapping[str, FormControl]) -> None:
    for control in fields.values():
        set_field_error(control, None)


def bind_api_error(
    error: ApiError,
    fields: Mapping[str, FormControl],
    feedback: ViewFeedback,
) -> None:
    clear_field_errors(fields)
    for name, message in error.fields.items():
        control = fields.get(name)
        if control is not None:
            set_field_error(control, message)
    suffix = f"（请求编号：{error.request_id}）" if error.request_id != "-" else ""
    feedback.show(f"{error.message}{suffix}", error=True)


def parse_int(control: ft.TextField, label: str) -> int | None:
    control.error = None
    try:
        return int(control.value.strip())
    except (AttributeError, ValueError):
        control.error = f"{label}必须是整数"
        return None


def parse_float(control: ft.TextField, label: str) -> float | None:
    control.error = None
    try:
        return float(control.value.strip())
    except (AttributeError, ValueError):
        control.error = f"{label}必须是数字"
        return None


def split_values(value: str) -> list[str]:
    return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]


def update_control(control: ft.Control) -> None:
    """Update a mounted control while keeping controller tests independent of a Page."""

    try:
        control.update()
    except (RuntimeError, AssertionError):
        pass


def control_by_key(root: ft.Control, key: str) -> ft.Control:
    seen: set[int] = set()

    def visit(value: object) -> ft.Control | None:
        identity = id(value)
        if identity in seen:
            return None
        seen.add(identity)
        if isinstance(value, ft.Control):
            if str(value.key) == key:
                return value
            for attribute in (
                "controls",
                "content",
                "rows",
                "cells",
                "columns",
                "items",
                "actions",
                "options",
                "leading",
                "title",
                "subtitle",
                "trailing",
            ):
                child = getattr(value, attribute, None)
                found = visit(child)
                if found is not None:
                    return found
            return None
        if isinstance(value, (list, tuple)):
            for item in value:
                found = visit(item)
                if found is not None:
                    return found
        return None

    control = visit(root)
    if control is None:
        raise KeyError(key)
    return control
