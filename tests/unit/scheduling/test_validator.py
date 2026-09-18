import pickle
from dataclasses import replace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from defense_grouping.scheduling.domain import (
    ApprovedException,
    StudentDemand,
)
from defense_grouping.scheduling.validator import validate_solution


def violation_codes(data, solution) -> set[str]:
    return {item.code for item in validate_solution(data, solution).violations}


def test_validator_accepts_complete_valid_solution(simple_input, valid_solution) -> None:
    assert validate_solution(simple_input, valid_solution).valid


def test_process_boundary_objects_are_pickle_serializable(simple_input, valid_solution) -> None:
    restored_input = pickle.loads(pickle.dumps(simple_input))
    restored_solution = pickle.loads(pickle.dumps(valid_solution))

    assert restored_input == simple_input
    assert restored_solution == valid_solution
    assert isinstance(restored_solution.objective_components, tuple)


def test_validator_rejects_student_with_advisor_on_panel(simple_input, valid_solution) -> None:
    group = replace(
        valid_solution.groups[0],
        teacher_ids=("teacher-advisor", "teacher-2"),
        chair_id="teacher-advisor",
    )

    assert "advisor_conflict" in violation_codes(simple_input, replace(valid_solution, groups=(group,)))


def test_exact_approved_exception_relaxes_only_its_conflict(simple_input, valid_solution) -> None:
    group = replace(
        valid_solution.groups[0],
        teacher_ids=("teacher-advisor", "teacher-2"),
        chair_id="teacher-advisor",
    )
    exception = ApprovedException(
        id="exception-1",
        constraint_code="advisor_conflict",
        teacher_id="teacher-advisor",
        student_id="student-1",
    )
    scoped = replace(simple_input, exceptions=(exception,))

    report = validate_solution(scoped, replace(valid_solution, groups=(group,)))

    assert report.valid
    assert report.used_exception_ids == frozenset({"exception-1"})


def test_unscoped_exception_is_rejected(simple_input, valid_solution) -> None:
    exception = ApprovedException(id="broad", constraint_code="advisor_conflict")
    report = validate_solution(replace(simple_input, exceptions=(exception,)), valid_solution)

    assert "invalid_exception_scope" in {item.code for item in report.violations}


@given(st.sampled_from(["duplicate_student", "room_overlap", "teacher_overlap", "capacity"]))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_mutations_of_valid_assignments_are_detected(
    simple_input,
    valid_solution,
    mutation,
) -> None:
    first = valid_solution.groups[0]
    if mutation == "duplicate_student":
        groups = (first, replace(first, id="group-2", teacher_ids=(), student_ids=("student-1",)))
        expected = "student_assignment_count"
    elif mutation == "room_overlap":
        groups = (first, replace(first, id="group-2", student_ids=(), teacher_ids=()))
        expected = "room_double_booked"
    elif mutation == "teacher_overlap":
        groups = (
            first,
            replace(first, id="group-2", student_ids=(), room_id="room-2"),
        )
        data = replace(
            simple_input,
            rooms=simple_input.rooms
            + (replace(simple_input.rooms[0], id="room-2"),),
        )
        assert expected_code(data, replace(valid_solution, groups=groups), "teacher_double_booked")
        return
    else:
        third_student = StudentDemand(
            id="student-3",
            advisor_id="teacher-advisor",
            direction_ids=frozenset({"direction-1"}),
            available_slot_ids=frozenset({"slot-1"}),
        )
        data = replace(
            simple_input,
            students=simple_input.students + (third_student,),
            slots=(replace(simple_input.slots[0], max_groups=2),),
            rooms=simple_input.rooms + (replace(simple_input.rooms[0], id="room-2"),),
        )
        groups = (replace(first, student_ids=("student-1", "student-2", "student-3")),)
        groups += (replace(first, id="group-2", room_id="room-2", student_ids=(), teacher_ids=()),)
        assert expected_code(data, replace(valid_solution, groups=groups), "group_capacity_exceeded")
        return
    assert expected_code(simple_input, replace(valid_solution, groups=groups), expected)


def expected_code(data, solution, code: str) -> bool:
    return code in violation_codes(data, solution)
