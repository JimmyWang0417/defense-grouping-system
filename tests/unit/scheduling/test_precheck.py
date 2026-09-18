from dataclasses import replace

from defense_grouping.scheduling.domain import StudentDemand
from defense_grouping.scheduling.precheck import run_prechecks


def diagnostic_codes(data) -> set[str]:
    return {item.code for item in run_prechecks(data)}


def test_precheck_reports_insufficient_chairs(simple_input) -> None:
    students = tuple(
        StudentDemand(f"student-{index}", "none", frozenset({"ai"}), frozenset({"slot-1"}))
        for index in range(5)
    )
    data = replace(
        simple_input,
        students=students,
        teachers=tuple(teacher for teacher in simple_input.teachers if teacher.title_rank >= 4)[:2],
        slots=(replace(simple_input.slots[0], max_groups=3),),
        rooms=tuple(replace(simple_input.rooms[0], id=f"room-{index}") for index in range(1, 4)),
    )

    diagnostics = run_prechecks(data)
    item = next(item for item in diagnostics if item.code == "insufficient_chairs")
    assert item.details == {"required": 3, "available": 2}


def test_precheck_reports_empty_domains_and_capacity(simple_input) -> None:
    unavailable = replace(simple_input.students[0], available_slot_ids=frozenset())
    data = replace(
        simple_input,
        students=(unavailable, simple_input.students[1]),
        slots=(replace(simple_input.slots[0], max_groups=0),),
    )

    codes = diagnostic_codes(data)
    assert "student_no_available_slot" in codes
    assert "insufficient_group_capacity" in codes


def test_precheck_reports_direction_without_non_advisor_teacher(simple_input) -> None:
    students = (
        replace(simple_input.students[0], direction_ids=frozenset({"rare"})),
        simple_input.students[1],
    )
    data = replace(simple_input, students=students)

    assert "direction_without_eligible_teacher" in diagnostic_codes(data)
