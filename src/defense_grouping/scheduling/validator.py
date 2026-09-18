from collections import Counter, defaultdict

from defense_grouping.scheduling.domain import (
    ApprovedException,
    ScheduleSolution,
    SchedulingInput,
    ValidationReport,
    Violation,
)


def exception_scope_valid(exception: ApprovedException) -> bool:
    if exception.constraint_code == "advisor_conflict":
        return (
            exception.teacher_id is not None
            and exception.student_id is not None
            and exception.person_id is None
            and exception.slot_id is None
        )
    if exception.constraint_code in {"course_conflict", "leave_conflict"}:
        return (
            exception.person_id is not None
            and exception.slot_id is not None
            and exception.teacher_id is None
            and exception.student_id is None
        )
    if exception.constraint_code == "workload_limit":
        return (
            exception.teacher_id is not None
            and exception.student_id is None
            and exception.person_id is None
            and exception.slot_id is None
        )
    return False


def find_advisor_exception(
    exceptions: tuple[ApprovedException, ...],
    teacher_id: str,
    student_id: str,
) -> ApprovedException | None:
    return next(
        (
            item
            for item in exceptions
            if exception_scope_valid(item)
            and item.constraint_code == "advisor_conflict"
            and item.teacher_id == teacher_id
            and item.student_id == student_id
        ),
        None,
    )


def find_availability_exception(
    exceptions: tuple[ApprovedException, ...],
    constraint_code: str,
    person_id: str,
    slot_id: str,
) -> ApprovedException | None:
    return next(
        (
            item
            for item in exceptions
            if exception_scope_valid(item)
            and item.constraint_code == constraint_code
            and item.person_id == person_id
            and item.slot_id == slot_id
        ),
        None,
    )


def find_workload_exception(
    exceptions: tuple[ApprovedException, ...], teacher_id: str
) -> ApprovedException | None:
    return next(
        (
            item
            for item in exceptions
            if exception_scope_valid(item)
            and item.constraint_code == "workload_limit"
            and item.teacher_id == teacher_id
        ),
        None,
    )


def validate_solution(data: SchedulingInput, solution: ScheduleSolution) -> ValidationReport:
    violations: list[Violation] = []
    used_exceptions: set[str] = set()
    students = {item.id: item for item in data.students}
    teachers = {item.id: item for item in data.teachers}
    slots = {item.id: item for item in data.slots}
    rooms = {item.id: item for item in data.rooms}
    availability_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for conflict in data.availability_conflicts:
        availability_codes[(conflict.person_id, conflict.slot_id)].add(conflict.constraint_code)

    for exception in data.exceptions:
        if not exception_scope_valid(exception):
            violations.append(
                Violation(
                    "invalid_exception_scope",
                    "例外范围不完整或约束类型不受支持",
                    (exception.id,),
                )
            )

    group_ids = [group.id for group in solution.groups]
    if len(set(group_ids)) != len(group_ids):
        violations.append(Violation("duplicate_group_id", "答辩组编号重复"))
    if len(solution.groups) != data.required_group_count:
        violations.append(
            Violation(
                "group_count_mismatch",
                "答辩组数量与学生容量推导结果不一致",
                details={"required": data.required_group_count, "actual": len(solution.groups)},
            )
        )

    student_counts: Counter[str] = Counter()
    teacher_loads: Counter[str] = Counter()
    student_slot_uses: Counter[tuple[str, str]] = Counter()
    teacher_slot_uses: Counter[tuple[str, str]] = Counter()
    room_slot_uses: Counter[tuple[str, str]] = Counter()
    slot_group_counts: Counter[str] = Counter()

    for group in solution.groups:
        slot = slots.get(group.slot_id)
        room = rooms.get(group.room_id)
        if slot is None:
            violations.append(
                Violation("unknown_slot", "答辩组使用了不存在的时段", (group.id, group.slot_id))
            )
        else:
            slot_group_counts[slot.id] += 1
        if room is None:
            violations.append(
                Violation("unknown_room", "答辩组使用了不存在的教室", (group.id, group.room_id))
            )
        elif group.slot_id not in room.available_slot_ids:
            violations.append(
                Violation(
                    "room_unavailable", "教室在该时段不可用", (group.id, room.id, group.slot_id)
                )
            )
        if room is not None and len(group.student_ids) > room.capacity:
            violations.append(
                Violation(
                    "room_capacity_exceeded",
                    "答辩组学生数超过教室容量",
                    (group.id, room.id),
                )
            )
        if len(group.student_ids) > data.rules.students_per_group:
            violations.append(
                Violation(
                    "group_capacity_exceeded",
                    "答辩组学生数超过活动规则",
                    (group.id,),
                )
            )
        if len(group.teacher_ids) != data.rules.teachers_per_group:
            violations.append(
                Violation(
                    "panel_size_mismatch",
                    "答辩组教师人数不符合活动规则",
                    (group.id,),
                    {"required": data.rules.teachers_per_group, "actual": len(group.teacher_ids)},
                )
            )
        if len(set(group.teacher_ids)) != len(group.teacher_ids):
            violations.append(
                Violation("duplicate_panel_teacher", "同一答辩组教师重复", (group.id,))
            )
        if len(set(group.student_ids)) != len(group.student_ids):
            violations.append(
                Violation("duplicate_group_student", "同一答辩组学生重复", (group.id,))
            )

        chair = teachers.get(group.chair_id)
        if group.chair_id not in group.teacher_ids or chair is None:
            violations.append(
                Violation("chair_not_on_panel", "组长必须是本组教师", (group.id, group.chair_id))
            )
        elif chair.title_rank < data.rules.chair_min_title_rank:
            violations.append(
                Violation("chair_title_insufficient", "组长职称不满足门槛", (group.id, chair.id))
            )

        room_slot_uses[(group.room_id, group.slot_id)] += 1
        for student_id in group.student_ids:
            student_counts[student_id] += 1
            student_slot_uses[(student_id, group.slot_id)] += 1
            student = students.get(student_id)
            if student is None:
                violations.append(
                    Violation("unknown_student", "答辩组包含未知学生", (group.id, student_id))
                )
                continue
            if group.slot_id not in student.available_slot_ids:
                codes = availability_codes.get(
                    (student.id, group.slot_id), {"availability_conflict"}
                )
                unresolved = []
                for code in codes:
                    approved = find_availability_exception(
                        data.exceptions, code, student.id, group.slot_id
                    )
                    if approved is None:
                        unresolved.append(code)
                    else:
                        used_exceptions.add(approved.id)
                if unresolved:
                    violations.append(
                        Violation(
                            "student_unavailable",
                            "学生在答辩时段不可用",
                            (group.id, student.id, group.slot_id),
                            {"constraints": sorted(unresolved)},
                        )
                    )
            for teacher_id in group.teacher_ids:
                if teacher_id != student.advisor_id:
                    continue
                approved = find_advisor_exception(data.exceptions, teacher_id, student.id)
                if approved is None:
                    violations.append(
                        Violation(
                            "advisor_conflict",
                            "学生导师不能担任该生所在组评审",
                            (group.id, student.id, teacher_id),
                        )
                    )
                else:
                    used_exceptions.add(approved.id)

        for teacher_id in group.teacher_ids:
            teacher_loads[teacher_id] += 1
            teacher_slot_uses[(teacher_id, group.slot_id)] += 1
            teacher = teachers.get(teacher_id)
            if teacher is None:
                violations.append(
                    Violation("unknown_teacher", "答辩组包含未知教师", (group.id, teacher_id))
                )
                continue
            if group.slot_id not in teacher.available_slot_ids:
                codes = availability_codes.get(
                    (teacher.id, group.slot_id), {"availability_conflict"}
                )
                unresolved = []
                for code in codes:
                    approved = find_availability_exception(
                        data.exceptions, code, teacher.id, group.slot_id
                    )
                    if approved is None:
                        unresolved.append(code)
                    else:
                        used_exceptions.add(approved.id)
                if unresolved:
                    violations.append(
                        Violation(
                            "teacher_unavailable",
                            "教师在答辩时段不可用",
                            (group.id, teacher.id, group.slot_id),
                            {"constraints": sorted(unresolved)},
                        )
                    )

    for student_id in sorted(students):
        count = student_counts[student_id]
        if count != 1:
            violations.append(
                Violation(
                    "student_assignment_count",
                    "每名学生必须且只能进入一个答辩组",
                    (student_id,),
                    {"count": count},
                )
            )
    for (student_id, slot_id), count in sorted(student_slot_uses.items()):
        if count > 1:
            violations.append(
                Violation("student_double_booked", "学生在同一时段重复安排", (student_id, slot_id))
            )
    for (teacher_id, slot_id), count in sorted(teacher_slot_uses.items()):
        if count > 1:
            violations.append(
                Violation("teacher_double_booked", "教师在同一时段重复安排", (teacher_id, slot_id))
            )
    for (room_id, slot_id), count in sorted(room_slot_uses.items()):
        if count > 1:
            violations.append(
                Violation("room_double_booked", "教室在同一时段重复安排", (room_id, slot_id))
            )
    for slot_id, count in sorted(slot_group_counts.items()):
        slot = slots[slot_id]
        if count > slot.max_groups:
            violations.append(
                Violation(
                    "slot_group_limit_exceeded",
                    "时段并行答辩组数超过上限",
                    (slot_id,),
                    {"limit": slot.max_groups, "actual": count},
                )
            )
    for teacher_id, load in sorted(teacher_loads.items()):
        teacher = teachers.get(teacher_id)
        if teacher is None:
            continue
        limit = min(teacher.workload_limit, data.rules.teacher_workload_limit)
        if load <= limit:
            continue
        approved = find_workload_exception(data.exceptions, teacher_id)
        if approved is None:
            violations.append(
                Violation(
                    "teacher_workload_exceeded",
                    "教师工作量超过硬性上限",
                    (teacher_id,),
                    {"limit": limit, "actual": load},
                )
            )
        else:
            used_exceptions.add(approved.id)

    return ValidationReport(tuple(violations), frozenset(used_exceptions))
