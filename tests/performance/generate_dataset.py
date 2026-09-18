from __future__ import annotations

import random
from collections import defaultdict

from defense_grouping.scheduling.domain import (
    RoomSupply,
    SchedulingInput,
    SchedulingRules,
    SlotSupply,
    StudentDemand,
    TeacherSupply,
)

SEED = 20260918
STUDENT_COUNT = 500
TEACHER_COUNT = 50
GROUP_COUNT = 20
SLOT_COUNT = 8
ROOM_COUNT = 24


def generate_department_scale_input(seed: int = SEED) -> SchedulingInput:
    """Build a shuffled public input from a discarded, known-feasible assignment."""
    randomizer = random.Random(seed)
    slot_ids = tuple(f"slot-{index:02d}" for index in range(SLOT_COUNT))
    hidden_group_slots = {
        group_index: slot_ids[group_index % SLOT_COUNT] for group_index in range(GROUP_COUNT)
    }
    hidden_group_panels = {
        group_index: (
            f"teacher-{group_index:02d}",
            f"teacher-{group_index + 20:02d}",
            f"teacher-{(group_index + 40) % TEACHER_COUNT:02d}",
        )
        for group_index in range(GROUP_COUNT)
    }

    students = [
        StudentDemand(
            id=f"student-{group_index:02d}-{student_index:02d}",
            advisor_id=f"teacher-{(group_index + 1) % GROUP_COUNT:02d}",
            direction_ids=frozenset({f"direction-{group_index:02d}"}),
            available_slot_ids=frozenset({hidden_group_slots[group_index]}),
        )
        for group_index in range(GROUP_COUNT)
        for student_index in range(STUDENT_COUNT // GROUP_COUNT)
    ]

    teacher_groups: dict[int, list[int]] = defaultdict(list)
    for group_index, panel in hidden_group_panels.items():
        for teacher_id in panel:
            teacher_groups[int(teacher_id.rsplit("-", 1)[1])].append(group_index)
    teachers = [
        TeacherSupply(
            id=f"teacher-{teacher_index:02d}",
            title_rank=5 if teacher_index < GROUP_COUNT else 4,
            direction_ids=frozenset(
                f"direction-{group_index:02d}" for group_index in teacher_groups[teacher_index]
            ),
            available_slot_ids=frozenset(
                hidden_group_slots[group_index] for group_index in teacher_groups[teacher_index]
            ),
            workload_limit=2,
        )
        for teacher_index in range(TEACHER_COUNT)
    ]
    slots = [
        SlotSupply(
            id=slot_id,
            max_groups=3 if slot_index < 4 else 2,
            sequence=slot_index,
        )
        for slot_index, slot_id in enumerate(slot_ids)
    ]
    rooms = [
        RoomSupply(
            id=f"room-{room_index:02d}",
            capacity=25,
            available_slot_ids=(
                frozenset({hidden_group_slots[room_index]})
                if room_index < GROUP_COUNT
                else frozenset(slot_ids)
            ),
        )
        for room_index in range(ROOM_COUNT)
    ]

    randomizer.shuffle(students)
    randomizer.shuffle(teachers)
    randomizer.shuffle(slots)
    randomizer.shuffle(rooms)
    return SchedulingInput(
        activity_id="performance-department-2026",
        seed=seed,
        students=tuple(students),
        teachers=tuple(teachers),
        slots=tuple(slots),
        rooms=tuple(rooms),
        rules=SchedulingRules(
            students_per_group=25,
            teachers_per_group=3,
            chair_min_title_rank=5,
            teacher_workload_limit=2,
            # The scale gate measures construction plus first-feasible latency.
            # Objective quality is covered by the smaller deterministic solver tests.
            balance_students_weight=0,
            balance_teacher_load_weight=0,
            direction_match_weight=0,
            compact_schedule_weight=0,
            exception_use_weight=0,
        ),
        exceptions=(),
    )
