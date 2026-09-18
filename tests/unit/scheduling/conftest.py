import pytest

from defense_grouping.scheduling.domain import (
    GroupSolution,
    RoomSupply,
    ScheduleSolution,
    SchedulingInput,
    SchedulingRules,
    SlotSupply,
    StudentDemand,
    TeacherSupply,
)


@pytest.fixture
def simple_input() -> SchedulingInput:
    return SchedulingInput(
        activity_id="activity-1",
        seed=20260918,
        students=(
            StudentDemand("student-1", "teacher-advisor", frozenset({"ai"}), frozenset({"slot-1"})),
            StudentDemand("student-2", "teacher-3", frozenset({"systems"}), frozenset({"slot-1"})),
        ),
        teachers=(
            TeacherSupply("teacher-1", 5, frozenset({"ai"}), frozenset({"slot-1"}), 2),
            TeacherSupply("teacher-2", 4, frozenset({"systems"}), frozenset({"slot-1"}), 2),
            TeacherSupply("teacher-advisor", 5, frozenset({"ai"}), frozenset({"slot-1"}), 2),
        ),
        slots=(SlotSupply("slot-1", 1),),
        rooms=(RoomSupply("room-1", 30, frozenset({"slot-1"})),),
        rules=SchedulingRules(
            students_per_group=2,
            teachers_per_group=2,
            chair_min_title_rank=4,
            teacher_workload_limit=2,
            balance_students_weight=100,
            balance_teacher_load_weight=50,
            direction_match_weight=30,
            compact_schedule_weight=20,
            exception_use_weight=500,
        ),
        exceptions=(),
    )


@pytest.fixture
def valid_solution() -> ScheduleSolution:
    return ScheduleSolution(
        groups=(
            GroupSolution(
                id="group-1",
                student_ids=("student-1", "student-2"),
                teacher_ids=("teacher-1", "teacher-2"),
                chair_id="teacher-1",
                slot_id="slot-1",
                room_id="room-1",
            ),
        ),
        objective_components=(),
    )
