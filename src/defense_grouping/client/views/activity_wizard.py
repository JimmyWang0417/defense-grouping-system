from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import flet as ft

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.view_state import (
    ViewFeedback,
    bind_api_error,
    parse_float,
    parse_int,
    set_busy,
    update_control,
)
from defense_grouping.client.session import SessionState


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
            await self.client.request("POST", f"/api/v1/activities/{activity_id}/slots", json=slot)
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


class ActivityWizardView:
    RULE_FIELDS = (
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
    RULE_LABELS: ClassVar[dict[str, str]] = {
        "students_per_group": "每组学生数",
        "teachers_per_group": "每组教师数",
        "chair_min_title_rank": "组长最低职称等级",
        "teacher_workload_limit": "教师工作量上限",
        "balance_students_weight": "学生数量均衡权重",
        "balance_teacher_load_weight": "教师工作量均衡权重",
        "direction_match_weight": "研究方向匹配权重",
        "compact_schedule_weight": "紧凑排期权重",
        "exception_use_weight": "使用例外惩罚权重",
    }

    def __init__(self, page: ft.Page, client: ApiClient, session: SessionState) -> None:
        self.page = page
        self.client = client
        self.session = session
        self.workflow = ActivityWizardWorkflow(client)
        self.state = ActivityWizardState()
        self.feedback = ViewFeedback(key="activity.feedback")
        self.step_title = ft.Text(size=20, weight=ft.FontWeight.BOLD, key="activity.step")
        self.step_host = ft.Column(key="activity.step_content")
        self.department_id = ft.TextField(label="院系编号", key="activity.department_id")
        self.name = ft.TextField(label="活动名称", key="activity.name")
        self.academic_year = ft.TextField(
            label="学年", value=str(self.state.values["academic_year"]), key="activity.year"
        )
        self.semester = ft.TextField(
            label="学期", value=str(self.state.values["semester"]), key="activity.semester"
        )
        self.academic_term_id = ft.TextField(label="学期编号（可空）", key="activity.term_id")
        self.rule_fields = {
            name: ft.TextField(
                label=self.RULE_LABELS[name],
                value=str(self.state.values[name]),
                key=f"activity.rule.{name}",
            )
            for name in self.RULE_FIELDS
        }
        self.slot_date = ft.TextField(label="日期（YYYY-MM-DD）", key="activity.slot.date")
        self.slot_start = ft.TextField(label="开始时间（HH:MM）", key="activity.slot.start")
        self.slot_end = ft.TextField(label="结束时间（HH:MM）", key="activity.slot.end")
        self.slot_max_groups = ft.TextField(
            label="最多答辩组数", value="1", key="activity.slot.max_groups"
        )
        self.slot_list = ft.Column(key="activity.slot.list")
        self.room_list = ft.Column(controls=[ft.Text("正在读取教室……")], key="activity.rooms")
        self.seed = ft.TextField(
            label="随机种子", value=str(self.state.values["seed"]), key="activity.seed"
        )
        self.time_limit = ft.TextField(
            label="求解时限（秒）",
            value=str(self.state.values["time_limit_seconds"]),
            key="activity.time_limit",
        )
        self.previous_button = ft.Button(
            "上一步",
            icon=ft.Icons.ARROW_BACK,
            key="activity.previous",
            on_click=self.previous,
        )
        self.next_button = ft.Button(
            "下一步",
            icon=ft.Icons.ARROW_FORWARD,
            key="activity.next",
            on_click=self.next,
        )
        self.submit_button = ft.Button(
            "完成配置",
            icon=ft.Icons.CHECK,
            key="activity.submit",
            on_click=self.submit,
        )
        self.root = ft.Column(
            controls=[
                ft.Text("答辩活动向导", size=28, weight=ft.FontWeight.BOLD),
                ft.Text(" → ".join(self.state.step_titles)),
                self.feedback.control,
                self.step_title,
                self.step_host,
                ft.Row(
                    controls=[self.previous_button, self.next_button, self.submit_button],
                    wrap=True,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            key="activity.root",
        )
        self._render_step()

    def _render_step(self) -> None:
        step = self.state.current_step
        self.step_title.value = f"第 {step + 1} 步：{self.state.step_titles[step]}"
        if step == 0:
            controls: list[ft.Control] = [
                self.department_id,
                self.name,
                self.academic_year,
                self.semester,
                self.academic_term_id,
            ]
        elif step == 1:
            controls = list(self.rule_fields.values())
        elif step == 2:
            controls = [
                ft.ResponsiveRow(
                    controls=[
                        self.slot_date,
                        self.slot_start,
                        self.slot_end,
                        self.slot_max_groups,
                    ]
                ),
                ft.Button("添加时段", icon=ft.Icons.ADD, on_click=self.add_slot),
                self.slot_list,
            ]
        elif step == 3:
            controls = [ft.Text("勾选本次活动可使用的教室"), self.room_list]
        else:
            controls = [self.seed, self.time_limit]
        self.step_host.controls = controls
        self.previous_button.disabled = step == 0
        self.next_button.visible = step < len(self.state.step_titles) - 1
        self.submit_button.visible = step == len(self.state.step_titles) - 1

    def _sync_current_step(self) -> bool:
        step = self.state.current_step
        if step == 0:
            self.state.values.update(
                {
                    "department_id": self.department_id.value.strip(),
                    "name": self.name.value.strip(),
                    "academic_year": self.academic_year.value.strip(),
                    "semester": self.semester.value.strip(),
                    "academic_term_id": self.academic_term_id.value.strip() or None,
                }
            )
        elif step == 1:
            valid = True
            for name, control in self.rule_fields.items():
                value = parse_int(control, self.RULE_LABELS[name])
                if value is None:
                    valid = False
                else:
                    self.state.values[name] = value
            if not valid:
                return False
        elif step == 4:
            seed = parse_int(self.seed, "随机种子")
            limit = parse_float(self.time_limit, "求解时限")
            if seed is None or limit is None:
                return False
            self.state.values["seed"] = seed
            self.state.values["time_limit_seconds"] = limit
        return self.state.validate_current_step()

    def _show_state_errors(self) -> None:
        controls = {
            "department_id": self.department_id,
            "name": self.name,
            "slots": self.slot_date,
            "room_ids": self.room_list,
            "seed": self.seed,
            "time_limit_seconds": self.time_limit,
        }
        for name, message in self.state.field_errors.items():
            control = controls.get(name)
            if isinstance(control, ft.TextField):
                control.error = message
            else:
                self.feedback.show(message, error=True)

    def next(self) -> None:
        if not self._sync_current_step():
            self._show_state_errors()
            update_control(self.root)
            return
        self.state.current_step += 1
        self._render_step()
        update_control(self.root)

    def previous(self) -> None:
        self.state.previous_step()
        self._render_step()
        update_control(self.root)

    def add_slot(self) -> None:
        max_groups = parse_int(self.slot_max_groups, "最多答辩组数")
        if not all((self.slot_date.value, self.slot_start.value, self.slot_end.value)):
            self.feedback.show("请完整填写日期、开始时间和结束时间", error=True)
            update_control(self.root)
            return
        if max_groups is None:
            update_control(self.root)
            return
        slot = {
            "date": self.slot_date.value.strip(),
            "start_time": self.slot_start.value.strip(),
            "end_time": self.slot_end.value.strip(),
            "max_groups": max_groups,
        }
        slots = self.state.values["slots"]
        if isinstance(slots, list):
            slots.append(slot)
        self.slot_list.controls = [
            ft.Text(
                f"{index}. {item['date']} {item['start_time']}-{item['end_time']}，"
                f"最多 {item['max_groups']} 组"
            )
            for index, item in enumerate(slots, start=1)
        ]
        self.feedback.clear()
        update_control(self.root)

    async def load_rooms(self) -> None:
        try:
            result = await self.client.request(
                "GET", "/api/v1/rooms", params={"page": 1, "page_size": 100}
            )
            rooms = result.get("items", [])
            if not isinstance(rooms, list):
                rooms = []
        except ApiError as error:
            bind_api_error(error, {}, self.feedback)
            rooms = []
        self.room_list.controls = [
            ft.Checkbox(
                label=(
                    f"{room.get('campus', '')} {room.get('building', '')} "
                    f"{room.get('name', '')}（容量 {room.get('capacity', '-')}）"
                ),
                key=f"activity.room.{room.get('id')}",
                on_change=self._room_handler(str(room.get("id"))),
            )
            for room in rooms
            if isinstance(room, dict) and room.get("id")
        ] or [ft.Text("暂无可用教室，请先在基础数据中添加教室")]
        update_control(self.root)

    def _room_handler(self, room_id: str) -> Any:
        def select(event: ft.Event[ft.Checkbox]) -> None:
            room_ids = self.state.values["room_ids"]
            if not isinstance(room_ids, list):
                return
            if event.control.value and room_id not in room_ids:
                room_ids.append(room_id)
            elif not event.control.value and room_id in room_ids:
                room_ids.remove(room_id)

        return select

    def load_values(self, values: dict[str, Any]) -> None:
        self.state.values.update(values)
        for name, control in self.rule_fields.items():
            control.value = str(self.state.values[name])
        self.department_id.value = str(self.state.values.get("department_id", ""))
        self.name.value = str(self.state.values.get("name", ""))
        self.academic_year.value = str(self.state.values.get("academic_year", ""))
        self.semester.value = str(self.state.values.get("semester", ""))
        self.seed.value = str(self.state.values.get("seed", ""))
        self.time_limit.value = str(self.state.values.get("time_limit_seconds", ""))

    async def submit(self) -> None:
        if not self._sync_current_step():
            self._show_state_errors()
            update_control(self.root)
            return
        set_busy((self.previous_button, self.next_button, self.submit_button), True)
        self.feedback.clear()
        update_control(self.root)
        try:
            activity = await self.workflow.submit(self.state.values)
        except ApiError as error:
            fields = {
                "department_id": self.department_id,
                "name": self.name,
                **self.rule_fields,
            }
            bind_api_error(error, fields, self.feedback)
        else:
            self.session.selected_activity_id = str(activity["id"])
            self.feedback.show(f"活动“{activity.get('name', self.name.value)}”已创建并完成配置")
        finally:
            set_busy((self.previous_button, self.next_button, self.submit_button), False)
            update_control(self.root)


def activity_wizard_view(page: ft.Page, client: ApiClient, session: SessionState) -> ft.Control:
    view = ActivityWizardView(page, client, session)
    page.run_task(view.load_rooms)
    return view.root
