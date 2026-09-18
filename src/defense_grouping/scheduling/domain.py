from dataclasses import dataclass, field
from math import ceil


@dataclass(frozen=True)
class StudentDemand:
    id: str
    advisor_id: str
    direction_ids: frozenset[str]
    available_slot_ids: frozenset[str]


@dataclass(frozen=True)
class TeacherSupply:
    id: str
    title_rank: int
    direction_ids: frozenset[str]
    available_slot_ids: frozenset[str]
    workload_limit: int


@dataclass(frozen=True)
class SlotSupply:
    id: str
    max_groups: int
    sequence: int = 0


@dataclass(frozen=True)
class RoomSupply:
    id: str
    capacity: int
    available_slot_ids: frozenset[str]


@dataclass(frozen=True)
class SchedulingRules:
    students_per_group: int
    teachers_per_group: int
    chair_min_title_rank: int
    teacher_workload_limit: int
    balance_students_weight: int
    balance_teacher_load_weight: int
    direction_match_weight: int
    compact_schedule_weight: int
    exception_use_weight: int


@dataclass(frozen=True)
class ApprovedException:
    id: str
    constraint_code: str
    teacher_id: str | None = None
    student_id: str | None = None
    person_id: str | None = None
    slot_id: str | None = None


@dataclass(frozen=True)
class AvailabilityConflict:
    person_id: str
    slot_id: str
    constraint_code: str


@dataclass(frozen=True)
class SchedulingInput:
    activity_id: str
    seed: int
    students: tuple[StudentDemand, ...]
    teachers: tuple[TeacherSupply, ...]
    slots: tuple[SlotSupply, ...]
    rooms: tuple[RoomSupply, ...]
    rules: SchedulingRules
    exceptions: tuple[ApprovedException, ...]
    availability_conflicts: tuple[AvailabilityConflict, ...] = ()

    @property
    def required_group_count(self) -> int:
        if not self.students or self.rules.students_per_group <= 0:
            return 0
        return ceil(len(self.students) / self.rules.students_per_group)


@dataclass(frozen=True)
class GroupSolution:
    id: str
    student_ids: tuple[str, ...]
    teacher_ids: tuple[str, ...]
    chair_id: str
    slot_id: str
    room_id: str


@dataclass(frozen=True)
class ScheduleSolution:
    groups: tuple[GroupSolution, ...]
    objective_components: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    affected_ids: tuple[str, ...] = ()
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    violations: tuple[Violation, ...]
    used_exception_ids: frozenset[str] = frozenset()

    @property
    def valid(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    affected_ids: tuple[str, ...] = ()
    details: dict[str, object] = field(default_factory=dict)
