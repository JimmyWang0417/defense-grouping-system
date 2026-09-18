import json
from dataclasses import replace
from pathlib import Path

import pytest

from defense_grouping.scheduling.domain import (
    ApprovedException,
    AvailabilityConflict,
    RoomSupply,
    SchedulingInput,
    SchedulingRules,
    SlotSupply,
    StudentDemand,
    TeacherSupply,
)
from defense_grouping.scheduling.solver import SolverProgress, solve
from defense_grouping.scheduling.validator import validate_solution

FIXTURES = Path(__file__).parents[2] / "fixtures" / "scheduling"


def load_input(name: str) -> SchedulingInput:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return SchedulingInput(
        activity_id=payload["activity_id"],
        seed=payload["seed"],
        students=tuple(
            StudentDemand(
                item["id"],
                item["advisor_id"],
                frozenset(item["direction_ids"]),
                frozenset(item["available_slot_ids"]),
            )
            for item in payload["students"]
        ),
        teachers=tuple(
            TeacherSupply(
                item["id"],
                item["title_rank"],
                frozenset(item["direction_ids"]),
                frozenset(item["available_slot_ids"]),
                item["workload_limit"],
            )
            for item in payload["teachers"]
        ),
        slots=tuple(SlotSupply(**item) for item in payload["slots"]),
        rooms=tuple(
            RoomSupply(item["id"], item["capacity"], frozenset(item["available_slot_ids"]))
            for item in payload["rooms"]
        ),
        rules=SchedulingRules(**payload["rules"]),
        exceptions=(),
    )


def test_solver_returns_reproducible_valid_solution() -> None:
    data = load_input("feasible_small.json")

    first = solve(data, time_limit_seconds=5)
    second = solve(data, time_limit_seconds=5)

    assert first.status in {"feasible", "optimal"}
    assert first.solution == second.solution
    assert first.solution is not None
    assert validate_solution(data, first.solution).valid
    assert dict(first.solution.objective_components).keys() == {
        "approved_exception_use",
        "direction_mismatch",
        "schedule_gaps",
        "student_balance",
        "teacher_load_balance",
        "weighted_total",
    }


def test_solver_never_uses_unapproved_advisor_exception(simple_input) -> None:
    forced = replace(
        simple_input,
        teachers=(simple_input.teachers[1], simple_input.teachers[2]),
    )

    outcome = solve(forced, time_limit_seconds=5)

    assert outcome.status == "infeasible"
    assert "advisor_conflict" in {item.code for item in outcome.diagnostics}


def test_solver_uses_only_exact_approved_advisor_exception(simple_input) -> None:
    exception = ApprovedException(
        id="advisor-exception",
        constraint_code="advisor_conflict",
        teacher_id="teacher-advisor",
        student_id="student-1",
    )
    forced = replace(
        simple_input,
        teachers=(simple_input.teachers[0], simple_input.teachers[2]),
        exceptions=(exception,),
    )

    outcome = solve(forced, time_limit_seconds=5)

    assert outcome.solution is not None
    report = validate_solution(forced, outcome.solution)
    assert report.valid
    assert report.used_exception_ids == frozenset({"advisor-exception"})
    assert dict(outcome.solution.objective_components)["approved_exception_use"] == 1


def test_solver_uses_only_exact_approved_availability_exception(simple_input) -> None:
    unavailable_student = replace(simple_input.students[0], available_slot_ids=frozenset())
    exception = ApprovedException(
        id="course-exception",
        constraint_code="course_conflict",
        person_id=unavailable_student.id,
        slot_id="slot-1",
    )
    data = replace(
        simple_input,
        students=(unavailable_student, simple_input.students[1]),
        exceptions=(exception,),
        availability_conflicts=(
            AvailabilityConflict(unavailable_student.id, "slot-1", "course_conflict"),
        ),
    )

    outcome = solve(data, time_limit_seconds=5)

    assert outcome.solution is not None
    report = validate_solution(data, outcome.solution)
    assert report.valid
    assert report.used_exception_ids == frozenset({"course-exception"})
    assert dict(outcome.solution.objective_components)["approved_exception_use"] == 1


def test_infeasible_fixture_explains_chair_supply() -> None:
    outcome = solve(load_input("infeasible_chair.json"), time_limit_seconds=5)

    assert outcome.status == "infeasible"
    diagnostic = next(item for item in outcome.diagnostics if item.code == "insufficient_chairs")
    assert diagnostic.details == {"required": 2, "available": 0}


def test_success_reports_progress(simple_input) -> None:
    progress: list[SolverProgress] = []

    outcome = solve(simple_input, time_limit_seconds=5, on_progress=progress.append)

    assert outcome.status in {"feasible", "optimal"}
    assert progress
    assert progress[-1].status == outcome.status
    assert progress[-1].objective_value is not None


def test_negative_time_limit_is_rejected(simple_input) -> None:
    with pytest.raises(ValueError, match="time_limit_seconds"):
        solve(simple_input, time_limit_seconds=-1)


def test_zero_time_limit_returns_timeout_without_partial_solution(simple_input) -> None:
    outcome = solve(simple_input, time_limit_seconds=0)

    assert outcome.status == "timeout"
    assert outcome.solution is None
    assert "solver_timeout" in {item.code for item in outcome.diagnostics}
