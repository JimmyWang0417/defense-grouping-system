from collections import Counter

from defense_grouping.scheduling.domain import Diagnostic, SchedulingInput


def run_prechecks(data: SchedulingInput) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    required_groups = data.required_group_count

    if not data.students:
        diagnostics.append(Diagnostic("no_students", "活动没有参与学生"))
    if not data.teachers:
        diagnostics.append(Diagnostic("no_teachers", "活动没有可用教师"))
    if data.rules.students_per_group <= 0:
        diagnostics.append(Diagnostic("invalid_group_capacity", "每组学生容量必须为正数"))

    room_by_slot = {
        slot.id: sorted(
            (
                room.capacity
                for room in data.rooms
                if slot.id in room.available_slot_ids and room.capacity > 0
            ),
            reverse=True,
        )
        for slot in data.slots
    }
    total_student_capacity = 0
    total_group_positions = 0
    for slot in data.slots:
        room_capacities = room_by_slot[slot.id][: max(0, slot.max_groups)]
        total_group_positions += len(room_capacities)
        total_student_capacity += sum(
            min(data.rules.students_per_group, room_capacity) for room_capacity in room_capacities
        )
    if total_group_positions < required_groups or total_student_capacity < len(data.students):
        diagnostics.append(
            Diagnostic(
                "insufficient_group_capacity",
                "时段、教室或容量不足以安排全部学生",
                details={
                    "required_groups": required_groups,
                    "available_group_positions": total_group_positions,
                    "required_students": len(data.students),
                    "available_student_capacity": total_student_capacity,
                },
            )
        )

    chair_candidates = [
        teacher
        for teacher in data.teachers
        if teacher.title_rank >= data.rules.chair_min_title_rank
        and teacher.available_slot_ids
        and teacher.workload_limit > 0
    ]
    if len(chair_candidates) < required_groups:
        diagnostics.append(
            Diagnostic(
                "insufficient_chairs",
                "符合职称门槛的组长人数不足",
                affected_ids=tuple(teacher.id for teacher in chair_candidates),
                details={"required": required_groups, "available": len(chair_candidates)},
            )
        )

    required_panel_assignments = required_groups * data.rules.teachers_per_group
    available_panel_assignments = sum(
        min(teacher.workload_limit, data.rules.teacher_workload_limit)
        for teacher in data.teachers
        if teacher.available_slot_ids
    )
    if available_panel_assignments < required_panel_assignments:
        diagnostics.append(
            Diagnostic(
                "insufficient_panel_supply",
                "教师总工作量不足以组成全部答辩组",
                details={
                    "required": required_panel_assignments,
                    "available": available_panel_assignments,
                },
            )
        )

    for student in sorted(data.students, key=lambda item: item.id):
        if not student.available_slot_ids:
            diagnostics.append(
                Diagnostic(
                    "student_no_available_slot",
                    "学生没有任何可用答辩时段",
                    (student.id,),
                )
            )
    for teacher in sorted(data.teachers, key=lambda item: item.id):
        if not teacher.available_slot_ids:
            diagnostics.append(
                Diagnostic(
                    "teacher_no_available_slot",
                    "教师没有任何可用答辩时段",
                    (teacher.id,),
                )
            )

    missing_directions: Counter[str] = Counter()
    affected_students: dict[str, list[str]] = {}
    for student in data.students:
        for direction_id in student.direction_ids:
            eligible = any(
                teacher.id != student.advisor_id
                and direction_id in teacher.direction_ids
                and bool(student.available_slot_ids & teacher.available_slot_ids)
                for teacher in data.teachers
            )
            if not eligible:
                missing_directions[direction_id] += 1
                affected_students.setdefault(direction_id, []).append(student.id)
    for direction_id in sorted(missing_directions):
        diagnostics.append(
            Diagnostic(
                "direction_without_eligible_teacher",
                "专业方向没有可用的非导师评审教师",
                tuple(sorted(affected_students[direction_id])),
                {"direction_id": direction_id, "student_count": missing_directions[direction_id]},
            )
        )

    return tuple(diagnostics)
