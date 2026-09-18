from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import flet as ft

from defense_grouping.client.api_client import ApiClient


@dataclass
class ActivityWizardState:
    step_titles: tuple[str, ...] = ("范围", "答辩组规则", "时段", "教室", "求解参数")
    current_step: int = 0
    values: dict[str, Any] = field(
        default_factory=lambda: {
            "academic_year": "2026-2027",
            "semester": "秋",
            "students_per_group": 25,
            "teachers_per_group": 3,
            "chair_min_title_rank": 4,
            "teacher_workload_limit": 10,
            "balance_students_weight": 100,
            "balance_teacher_load_weight": 50,
            "direction_match_weight": 30,
            "compact_schedule_weight": 20,
            "exception_use_weight": 500,
            "slots": [],
            "room_ids": [],
            "seed": 20260918,
            "time_limit_seconds": 60,
        }
    )
    field_errors: dict[str, str] = field(default_factory=dict)

    def _required_for_current_step(self) -> tuple[tuple[str, str], ...]:
        return (
            (("department_id", "请选择院系"), ("name", "请输入活动名称")),
            (
                ("students_per_group", "请输入每组学生数"),
                ("teachers_per_group", "请输入每组教师数"),
                ("chair_min_title_rank", "请输入组长职称门槛"),
            ),
            (("slots", "请至少添加一个时段"),),
            (("room_ids", "请至少选择一间教室"),),
            (
                ("seed", "请输入随机种子"),
                ("time_limit_seconds", "请输入求解时限"),
            ),
        )[self.current_step]

    def validate_current_step(self) -> bool:
        self.field_errors = {
            name: message
            for name, message in self._required_for_current_step()
            if self.values.get(name) in (None, "", [], ())
        }
        return not self.field_errors

    def next_step(self) -> bool:
        if not self.validate_current_step():
            return False
        self.current_step = min(len(self.step_titles) - 1, self.current_step + 1)
        return True

    def previous_step(self) -> None:
        self.current_step = max(0, self.current_step - 1)


class ActivityWizardWorkflow:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    async def submit(self, values: dict[str, Any]) -> dict[str, Any]:
        activity = await self.client.request(
            "POST",
            "/api/v1/activities",
            json={
                key: values.get(key)
                for key in (
                    "department_id",
                    "name",
                    "academic_year",
                    "semester",
                    "academic_term_id",
                )
                if key in values
            },
        )
        activity_id = str(activity["id"])
        for slot in values.get("slots", []):
            await self.client.request(
                "POST",
                f"/api/v1/activities/{activity_id}/slots",
                json=slot,
            )
        rule_keys = (
            "students_per_group",
            "teachers_per_group",
            "chair_min_title_rank",
            "teacher_workload_limit",
            "balance_students_weight",
            "balance_teacher_load_weight",
            "direction_match_weight",
            "compact_schedule_weight",
            "exception_use_weight",
        )
        await self.client.request(
            "PUT",
            f"/api/v1/activities/{activity_id}/rules",
            json={key: values[key] for key in rule_keys},
        )
        await self.client.request(
            "PUT",
            f"/api/v1/activities/{activity_id}/rooms",
            json={"room_ids": values.get("room_ids", [])},
        )
        return activity


def activity_wizard_view(_client: ApiClient) -> ft.Control:
    state = ActivityWizardState()
    return ft.Column(
        controls=[
            ft.Text("答辩活动向导", size=28, weight=ft.FontWeight.BOLD),
            ft.Text(" → ".join(state.step_titles)),
            ft.TextField(label="活动名称"),
            ft.TextField(label="学年", value=str(state.values["academic_year"])),
            ft.TextField(label="学期", value=str(state.values["semester"])),
            ft.Row(
                controls=[
                    ft.Button("上一步", icon=ft.Icons.ARROW_BACK),
                    ft.Button("下一步", icon=ft.Icons.ARROW_FORWARD),
                    ft.Button("完成配置", icon=ft.Icons.CHECK),
                ]
            ),
            ft.Text("各步仅做必填提示，业务规则以后端校验结果为准。"),
        ]
    )
