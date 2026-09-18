from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from ortools.sat.python import cp_model

from defense_grouping.scheduling.domain import (
    ApprovedException,
    Diagnostic,
    GroupSolution,
    ScheduleSolution,
    SchedulingInput,
)
from defense_grouping.scheduling.precheck import run_prechecks
from defense_grouping.scheduling.validator import (
    exception_scope_valid,
    find_advisor_exception,
    find_availability_exception,
    find_workload_exception,
    validate_solution,
)

SolveStatus = Literal["feasible", "optimal", "infeasible", "timeout"]


@dataclass(frozen=True)
class SolverProgress:
    status: SolveStatus
    elapsed_seconds: float
    objective_value: int | None = None
    best_bound: int | None = None


ProgressCallback = Callable[[SolverProgress], None]


@dataclass(frozen=True)
class SolveOutcome:
    status: SolveStatus
    solution: ScheduleSolution | None
    diagnostics: tuple[Diagnostic, ...]
    elapsed_seconds: float


@dataclass
class _Variables:
    student_group: dict[tuple[int, int], cp_model.IntVar]
    teacher_group: dict[tuple[int, int], cp_model.IntVar]
    group_slot: dict[tuple[int, int], cp_model.IntVar]
    group_room: dict[tuple[int, int], cp_model.IntVar]
    chair_group: dict[tuple[int, int], cp_model.IntVar]
    group_loads: list[cp_model.IntVar]


@dataclass
class _Objective:
    student_balance: cp_model.IntVar
    teacher_load_balance: cp_model.IntVar
    direction_mismatch: cp_model.IntVar
    schedule_gaps: cp_model.IntVar
    approved_exception_use: cp_model.IntVar
    weighted_total: cp_model.IntVar


_FATAL_PRECHECK_CODES = {
    "no_students",
    "no_teachers",
    "invalid_group_capacity",
    "insufficient_group_capacity",
    "insufficient_chairs",
    "insufficient_panel_supply",
}

_FAMILY_DIAGNOSTICS = {
    "advisor": ("advisor_conflict", "导师回避约束无法同时满足"),
    "assignment": ("assignment_constraints", "学生唯一分组约束无法同时满足"),
    "availability": ("availability_conflict", "人员可用性或同时段占用约束无法同时满足"),
    "capacity": ("capacity_constraints", "分组、时段或教室容量约束无法同时满足"),
    "panel": ("panel_constraints", "答辩教师人数或组长资格约束无法同时满足"),
    "room": ("room_constraints", "教室可用性或同时段占用约束无法同时满足"),
    "workload": ("workload_constraints", "教师工作量上限约束无法同时满足"),
}


class _SolutionProgress(cp_model.CpSolverSolutionCallback):
    def __init__(self, started: float, callback: ProgressCallback) -> None:
        super().__init__()
        self._started = started
        self._callback = callback

    def on_solution_callback(self) -> None:
        self._callback(
            SolverProgress(
                status="feasible",
                elapsed_seconds=time.perf_counter() - self._started,
                objective_value=round(self.objective_value),
                best_bound=round(self.best_objective_bound),
            )
        )


def _and_var(
    model: cp_model.CpModel,
    left: cp_model.IntVar,
    right: cp_model.IntVar,
    name: str,
) -> cp_model.IntVar:
    result = model.new_bool_var(name)
    model.add(result <= left)
    model.add(result <= right)
    model.add(result >= left + right - 1)
    return result


def _sum_var(
    model: cp_model.CpModel,
    terms: Iterable[cp_model.LinearExprT],
    upper_bound: int,
    name: str,
) -> cp_model.IntVar:
    result = model.new_int_var(0, max(0, upper_bound), name)
    model.add(result == sum(terms, 0))
    return result


def _invalid_input_diagnostics(data: SchedulingInput) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    identifier_sets = {
        "student": [item.id for item in data.students],
        "teacher": [item.id for item in data.teachers],
        "slot": [item.id for item in data.slots],
        "room": [item.id for item in data.rooms],
        "exception": [item.id for item in data.exceptions],
    }
    for kind, identifiers in identifier_sets.items():
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            diagnostics.append(
                Diagnostic(
                    "duplicate_input_id",
                    "求解输入包含重复标识",
                    tuple(duplicates),
                    {"kind": kind},
                )
            )
    if data.rules.teachers_per_group <= 0:
        diagnostics.append(Diagnostic("invalid_panel_size", "每组教师人数必须为正数"))
    if data.rules.teacher_workload_limit < 0:
        diagnostics.append(Diagnostic("invalid_workload_limit", "教师工作量上限不能为负数"))
    weights = (
        data.rules.balance_students_weight,
        data.rules.balance_teacher_load_weight,
        data.rules.direction_match_weight,
        data.rules.compact_schedule_weight,
        data.rules.exception_use_weight,
    )
    if any(weight < 0 for weight in weights):
        diagnostics.append(Diagnostic("invalid_objective_weight", "优化目标权重不能为负数"))
    for exception in data.exceptions:
        if not exception_scope_valid(exception):
            diagnostics.append(
                Diagnostic(
                    "invalid_exception_scope",
                    "例外范围不完整或约束类型不受支持",
                    (exception.id,),
                )
            )
    return tuple(diagnostics)


def _deduplicate_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    unique: dict[tuple[str, tuple[str, ...], str], Diagnostic] = {}
    for item in diagnostics:
        key = (item.code, item.affected_ids, repr(sorted(item.details.items())))
        unique.setdefault(key, item)
    return tuple(unique.values())


def _availability_exceptions(
    data: SchedulingInput,
    person_id: str,
    slot_id: str,
) -> tuple[ApprovedException, ...] | None:
    codes = sorted(
        {
            conflict.constraint_code
            for conflict in data.availability_conflicts
            if conflict.person_id == person_id and conflict.slot_id == slot_id
        }
    )
    if not codes:
        return None
    approved: list[ApprovedException] = []
    for code in codes:
        exception = find_availability_exception(data.exceptions, code, person_id, slot_id)
        if exception is None:
            return None
        approved.append(exception)
    return tuple(approved)


def _build_model(
    data: SchedulingInput,
) -> tuple[
    cp_model.CpModel,
    _Variables,
    _Objective,
    dict[int, str],
]:
    model = cp_model.CpModel()
    students = sorted(data.students, key=lambda item: item.id)
    teachers = sorted(data.teachers, key=lambda item: item.id)
    slots = sorted(data.slots, key=lambda item: (item.sequence, item.id))
    rooms = sorted(data.rooms, key=lambda item: item.id)
    group_count = data.required_group_count

    families = {name: model.new_bool_var(f"family_{name}") for name in sorted(_FAMILY_DIAGNOSTICS)}
    assumption_families: dict[int, str] = {}
    for name, literal in families.items():
        model.add_assumption(literal)
        assumption_families[literal.index] = name

    student_group = {
        (student_index, group_index): model.new_bool_var(
            f"student_{student_index}_group_{group_index}"
        )
        for student_index in range(len(students))
        for group_index in range(group_count)
    }
    teacher_group = {
        (teacher_index, group_index): model.new_bool_var(
            f"teacher_{teacher_index}_group_{group_index}"
        )
        for teacher_index in range(len(teachers))
        for group_index in range(group_count)
    }
    group_slot = {
        (group_index, slot_index): model.new_bool_var(f"group_{group_index}_slot_{slot_index}")
        for group_index in range(group_count)
        for slot_index in range(len(slots))
    }
    group_room = {
        (group_index, room_index): model.new_bool_var(f"group_{group_index}_room_{room_index}")
        for group_index in range(group_count)
        for room_index in range(len(rooms))
    }
    chair_group = {
        (teacher_index, group_index): model.new_bool_var(
            f"chair_{teacher_index}_group_{group_index}"
        )
        for teacher_index in range(len(teachers))
        for group_index in range(group_count)
    }

    # Defense groups are unlabeled. Ordering their unique (slot, room) resource
    # pair removes equivalent permutations without excluding any real schedule.
    resource_choices: list[cp_model.IntVar] = []
    for group_index in range(group_count):
        slot_choice = model.new_int_var(0, len(slots) - 1, f"group_{group_index}_slot_choice")
        room_choice = model.new_int_var(0, len(rooms) - 1, f"group_{group_index}_room_choice")
        model.add(
            slot_choice
            == sum(
                slot_index * group_slot[group_index, slot_index] for slot_index in range(len(slots))
            )
        )
        model.add(
            room_choice
            == sum(
                room_index * group_room[group_index, room_index] for room_index in range(len(rooms))
            )
        )
        resource_choice = model.new_int_var(
            0,
            len(slots) * len(rooms) - 1,
            f"group_{group_index}_resource_choice",
        )
        model.add(resource_choice == slot_choice * len(rooms) + room_choice)
        resource_choices.append(resource_choice)
    for group_index in range(group_count - 1):
        model.add(resource_choices[group_index] < resource_choices[group_index + 1])

    for student_index in range(len(students)):
        model.add_exactly_one(
            student_group[student_index, group_index] for group_index in range(group_count)
        ).only_enforce_if(families["assignment"])

    group_loads: list[cp_model.IntVar] = []
    for group_index in range(group_count):
        group_load = _sum_var(
            model,
            (student_group[student_index, group_index] for student_index in range(len(students))),
            len(students),
            f"group_{group_index}_student_load",
        )
        group_loads.append(group_load)
        model.add(group_load <= data.rules.students_per_group).only_enforce_if(families["capacity"])
        model.add(
            sum(teacher_group[teacher_index, group_index] for teacher_index in range(len(teachers)))
            == data.rules.teachers_per_group
        ).only_enforce_if(families["panel"])
        model.add(
            sum(chair_group[teacher_index, group_index] for teacher_index in range(len(teachers)))
            == 1
        ).only_enforce_if(families["panel"])
        model.add_exactly_one(
            group_slot[group_index, slot_index] for slot_index in range(len(slots))
        ).only_enforce_if(families["availability"])
        model.add_exactly_one(
            group_room[group_index, room_index] for room_index in range(len(rooms))
        ).only_enforce_if(families["room"])

        for teacher_index, teacher in enumerate(teachers):
            chair = chair_group[teacher_index, group_index]
            model.add(chair <= teacher_group[teacher_index, group_index]).only_enforce_if(
                families["panel"]
            )
            if teacher.title_rank < data.rules.chair_min_title_rank:
                model.add(chair == 0).only_enforce_if(families["panel"])

    for group_index in range(group_count - 1):
        model.add(group_loads[group_index] >= group_loads[group_index + 1])

    exception_events: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for student_index, student in enumerate(students):
        for teacher_index, teacher in enumerate(teachers):
            if student.advisor_id != teacher.id:
                continue
            exception = find_advisor_exception(data.exceptions, teacher.id, student.id)
            for group_index in range(group_count):
                if exception is None:
                    model.add(
                        student_group[student_index, group_index]
                        + teacher_group[teacher_index, group_index]
                        <= 1
                    ).only_enforce_if(families["advisor"])
                else:
                    exception_events[exception.id].append(
                        _and_var(
                            model,
                            student_group[student_index, group_index],
                            teacher_group[teacher_index, group_index],
                            f"advisor_exception_{student_index}_{teacher_index}_{group_index}",
                        )
                    )

    student_slot_events: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    teacher_slot_events: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    room_slot_events: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)

    for group_index in range(group_count):
        for slot_index, slot in enumerate(slots):
            for student_index, student in enumerate(students):
                event = _and_var(
                    model,
                    student_group[student_index, group_index],
                    group_slot[group_index, slot_index],
                    f"student_{student_index}_slot_{slot_index}_group_{group_index}",
                )
                student_slot_events[student_index, slot_index].append(event)
                if slot.id not in student.available_slot_ids:
                    exceptions = _availability_exceptions(data, student.id, slot.id)
                    if exceptions is None:
                        model.add(event == 0).only_enforce_if(families["availability"])
                    else:
                        for exception in exceptions:
                            exception_events[exception.id].append(event)

            for teacher_index, teacher in enumerate(teachers):
                event = _and_var(
                    model,
                    teacher_group[teacher_index, group_index],
                    group_slot[group_index, slot_index],
                    f"teacher_{teacher_index}_slot_{slot_index}_group_{group_index}",
                )
                teacher_slot_events[teacher_index, slot_index].append(event)
                if slot.id not in teacher.available_slot_ids:
                    exceptions = _availability_exceptions(data, teacher.id, slot.id)
                    if exceptions is None:
                        model.add(event == 0).only_enforce_if(families["availability"])
                    else:
                        for exception in exceptions:
                            exception_events[exception.id].append(event)

            for room_index, room in enumerate(rooms):
                event = _and_var(
                    model,
                    group_room[group_index, room_index],
                    group_slot[group_index, slot_index],
                    f"room_{room_index}_slot_{slot_index}_group_{group_index}",
                )
                room_slot_events[room_index, slot_index].append(event)
                if slot.id not in room.available_slot_ids:
                    model.add(event == 0).only_enforce_if(families["room"])

        for room_index, room in enumerate(rooms):
            model.add(
                group_loads[group_index]
                <= room.capacity + len(students) * (1 - group_room[group_index, room_index])
            ).only_enforce_if(families["capacity"])

    for events in student_slot_events.values():
        model.add(sum(events) <= 1).only_enforce_if(families["availability"])
    for events in teacher_slot_events.values():
        model.add(sum(events) <= 1).only_enforce_if(families["availability"])
    for events in room_slot_events.values():
        model.add(sum(events) <= 1).only_enforce_if(families["room"])
    for slot_index, slot in enumerate(slots):
        model.add(
            sum(group_slot[group_index, slot_index] for group_index in range(group_count))
            <= slot.max_groups
        ).only_enforce_if(families["capacity"])

    teacher_loads: list[cp_model.IntVar] = []
    for teacher_index, teacher in enumerate(teachers):
        load = _sum_var(
            model,
            (teacher_group[teacher_index, group_index] for group_index in range(group_count)),
            group_count,
            f"teacher_{teacher_index}_load",
        )
        teacher_loads.append(load)
        limit = min(teacher.workload_limit, data.rules.teacher_workload_limit)
        exception = find_workload_exception(data.exceptions, teacher.id)
        if exception is None:
            model.add(load <= limit).only_enforce_if(families["workload"])
        else:
            used = model.new_bool_var(f"workload_exception_{teacher_index}")
            model.add(load >= limit + 1).only_enforce_if(used)
            model.add(load <= limit).only_enforce_if(used.negated())
            exception_events[exception.id].append(used)

    max_group_load = model.new_int_var(0, len(students), "max_group_load")
    min_group_load = model.new_int_var(0, len(students), "min_group_load")
    model.add_max_equality(max_group_load, group_loads)
    model.add_min_equality(min_group_load, group_loads)
    student_balance = model.new_int_var(0, len(students), "student_balance")
    model.add(student_balance == max_group_load - min_group_load)

    total_panel_assignments = group_count * data.rules.teachers_per_group
    deviations: list[cp_model.IntVar] = []
    for teacher_index, load in enumerate(teacher_loads):
        deviation = model.new_int_var(
            0,
            max(total_panel_assignments, group_count * len(teachers)),
            f"teacher_{teacher_index}_load_deviation",
        )
        model.add_abs_equality(
            deviation,
            load * len(teachers) - total_panel_assignments,
        )
        deviations.append(deviation)
    teacher_load_balance_upper = max(1, len(teachers)) * max(1, group_count) * max(1, len(teachers))
    teacher_load_balance = _sum_var(
        model,
        deviations,
        teacher_load_balance_upper,
        "teacher_load_balance",
    )

    mismatch_terms: list[cp_model.LinearExprT] = []
    for student_index, student in enumerate(students):
        eligible_teachers = [
            teacher_index
            for teacher_index, teacher in enumerate(teachers)
            if bool(student.direction_ids & teacher.direction_ids)
        ]
        for group_index in range(group_count):
            if not eligible_teachers:
                mismatch_terms.append(student_group[student_index, group_index])
                continue
            direction_present = model.new_bool_var(
                f"student_{student_index}_direction_present_group_{group_index}"
            )
            model.add_max_equality(
                direction_present,
                [teacher_group[index, group_index] for index in eligible_teachers],
            )
            matched = _and_var(
                model,
                student_group[student_index, group_index],
                direction_present,
                f"student_{student_index}_direction_match_group_{group_index}",
            )
            mismatch_terms.append(student_group[student_index, group_index] - matched)
    direction_mismatch = _sum_var(
        model,
        mismatch_terms,
        len(students),
        "direction_mismatch",
    )

    teacher_uses_slot: dict[tuple[int, int], cp_model.IntVar] = {}
    for teacher_index in range(len(teachers)):
        for slot_index in range(len(slots)):
            used = model.new_bool_var(f"teacher_{teacher_index}_uses_slot_{slot_index}")
            model.add_max_equality(used, teacher_slot_events[teacher_index, slot_index])
            teacher_uses_slot[teacher_index, slot_index] = used
    gap_terms: list[cp_model.LinearExprT] = []
    max_gap_penalty = 0
    for teacher_index in range(len(teachers)):
        for left_index, left in enumerate(slots):
            for right_index in range(left_index + 1, len(slots)):
                right = slots[right_index]
                distance = max(0, right.sequence - left.sequence - 1)
                if distance == 0:
                    continue
                both = _and_var(
                    model,
                    teacher_uses_slot[teacher_index, left_index],
                    teacher_uses_slot[teacher_index, right_index],
                    f"teacher_{teacher_index}_gap_{left_index}_{right_index}",
                )
                gap_terms.append(distance * both)
                max_gap_penalty += distance
    schedule_gaps = _sum_var(model, gap_terms, max_gap_penalty, "schedule_gaps")

    exception_used_vars: list[cp_model.IntVar] = []
    for exception_id, events in sorted(exception_events.items()):
        used = model.new_bool_var(f"exception_{exception_id}_used")
        model.add_max_equality(used, events)
        exception_used_vars.append(used)
    approved_exception_use = _sum_var(
        model,
        exception_used_vars,
        len(exception_used_vars),
        "approved_exception_use",
    )

    raw_components = (
        (student_balance, data.rules.balance_students_weight),
        (teacher_load_balance, data.rules.balance_teacher_load_weight),
        (direction_mismatch, data.rules.direction_match_weight),
        (schedule_gaps, data.rules.compact_schedule_weight),
        (approved_exception_use, data.rules.exception_use_weight),
    )
    weighted_upper_bound = (
        len(students) * data.rules.balance_students_weight
        + teacher_load_balance_upper * data.rules.balance_teacher_load_weight
        + len(students) * data.rules.direction_match_weight
        + max_gap_penalty * data.rules.compact_schedule_weight
        + len(exception_used_vars) * data.rules.exception_use_weight
    )
    weighted_total = model.new_int_var(0, max(0, weighted_upper_bound), "weighted_total")
    model.add(weighted_total == sum(variable * weight for variable, weight in raw_components))
    model.minimize(weighted_total)

    return (
        model,
        _Variables(
            student_group=student_group,
            teacher_group=teacher_group,
            group_slot=group_slot,
            group_room=group_room,
            chair_group=chair_group,
            group_loads=group_loads,
        ),
        _Objective(
            student_balance=student_balance,
            teacher_load_balance=teacher_load_balance,
            direction_mismatch=direction_mismatch,
            schedule_gaps=schedule_gaps,
            approved_exception_use=approved_exception_use,
            weighted_total=weighted_total,
        ),
        assumption_families,
    )


def _solution_from_solver(
    data: SchedulingInput,
    solver: cp_model.CpSolver,
    variables: _Variables,
    objective: _Objective,
) -> ScheduleSolution:
    students = sorted(data.students, key=lambda item: item.id)
    teachers = sorted(data.teachers, key=lambda item: item.id)
    slots = sorted(data.slots, key=lambda item: (item.sequence, item.id))
    rooms = sorted(data.rooms, key=lambda item: item.id)
    groups: list[GroupSolution] = []
    for group_index in range(data.required_group_count):
        student_ids = tuple(
            student.id
            for student_index, student in enumerate(students)
            if solver.boolean_value(variables.student_group[student_index, group_index])
        )
        teacher_ids = tuple(
            teacher.id
            for teacher_index, teacher in enumerate(teachers)
            if solver.boolean_value(variables.teacher_group[teacher_index, group_index])
        )
        chair_id = next(
            teacher.id
            for teacher_index, teacher in enumerate(teachers)
            if solver.boolean_value(variables.chair_group[teacher_index, group_index])
        )
        slot_id = next(
            slot.id
            for slot_index, slot in enumerate(slots)
            if solver.boolean_value(variables.group_slot[group_index, slot_index])
        )
        room_id = next(
            room.id
            for room_index, room in enumerate(rooms)
            if solver.boolean_value(variables.group_room[group_index, room_index])
        )
        groups.append(
            GroupSolution(
                id=f"group-{group_index + 1}",
                student_ids=student_ids,
                teacher_ids=teacher_ids,
                chair_id=chair_id,
                slot_id=slot_id,
                room_id=room_id,
            )
        )
    components = tuple(
        sorted(
            {
                "student_balance": solver.value(objective.student_balance),
                "teacher_load_balance": solver.value(objective.teacher_load_balance),
                "direction_mismatch": solver.value(objective.direction_mismatch),
                "schedule_gaps": solver.value(objective.schedule_gaps),
                "approved_exception_use": solver.value(objective.approved_exception_use),
                "weighted_total": solver.value(objective.weighted_total),
            }.items()
        )
    )
    return ScheduleSolution(groups=tuple(groups), objective_components=components)


def _core_diagnostics(
    solver: cp_model.CpSolver,
    assumption_families: dict[int, str],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for literal_index in solver.sufficient_assumptions_for_infeasibility():
        family = assumption_families.get(literal_index)
        if family is None:
            continue
        code, message = _FAMILY_DIAGNOSTICS[family]
        diagnostics.append(Diagnostic(code, message, details={"constraint_family": family}))
    return tuple(diagnostics)


def _emit_final_progress(
    callback: ProgressCallback | None,
    outcome: SolveOutcome,
    objective_value: int | None = None,
    best_bound: int | None = None,
) -> None:
    if callback is not None:
        callback(
            SolverProgress(
                status=outcome.status,
                elapsed_seconds=outcome.elapsed_seconds,
                objective_value=objective_value,
                best_bound=best_bound,
            )
        )


def solve(
    data: SchedulingInput,
    time_limit_seconds: float,
    on_progress: ProgressCallback | None = None,
) -> SolveOutcome:
    if not math.isfinite(time_limit_seconds) or time_limit_seconds < 0:
        raise ValueError("time_limit_seconds must be a finite non-negative number")

    started = time.perf_counter()
    invalid_diagnostics = _invalid_input_diagnostics(data)
    precheck_diagnostics = run_prechecks(data)
    fatal_prechecks = tuple(
        item for item in precheck_diagnostics if item.code in _FATAL_PRECHECK_CODES
    )
    if invalid_diagnostics or fatal_prechecks:
        outcome = SolveOutcome(
            status="infeasible",
            solution=None,
            diagnostics=_deduplicate_diagnostics((*invalid_diagnostics, *precheck_diagnostics)),
            elapsed_seconds=time.perf_counter() - started,
        )
        _emit_final_progress(on_progress, outcome)
        return outcome

    model, variables, objective, assumption_families = _build_model(data)
    solver = cp_model.CpSolver()
    remaining_seconds = max(0.0, time_limit_seconds - (time.perf_counter() - started))
    if remaining_seconds == 0:
        outcome = SolveOutcome(
            "timeout",
            None,
            _deduplicate_diagnostics(
                (
                    *precheck_diagnostics,
                    Diagnostic("solver_timeout", "建模达到时间上限，未启动搜索"),
                )
            ),
            time.perf_counter() - started,
        )
        _emit_final_progress(on_progress, outcome)
        return outcome
    solver.parameters.max_time_in_seconds = remaining_seconds
    solver.parameters.random_seed = data.seed
    solver.parameters.num_search_workers = 1
    progress_callback = _SolutionProgress(started, on_progress) if on_progress is not None else None
    status = solver.solve(model, progress_callback)
    elapsed = time.perf_counter() - started

    if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        solution = _solution_from_solver(data, solver, variables, objective)
        report = validate_solution(data, solution)
        if not report.valid:
            codes = ", ".join(item.code for item in report.violations)
            raise RuntimeError(f"solver returned an invalid solution: {codes}")
        solve_status: SolveStatus = "optimal" if status == cp_model.OPTIMAL else "feasible"
        outcome = SolveOutcome(solve_status, solution, precheck_diagnostics, elapsed)
        _emit_final_progress(
            on_progress,
            outcome,
            solver.value(objective.weighted_total),
            round(solver.best_objective_bound),
        )
        return outcome

    if status == cp_model.INFEASIBLE:
        remaining_seconds = max(0.0, time_limit_seconds - elapsed)
        core_diagnostics: tuple[Diagnostic, ...] = ()
        if remaining_seconds > 0:
            # OR-Tools 9.15 exposes this method without a type annotation.
            model.clear_objective()  # type: ignore[no-untyped-call]
            core_solver = cp_model.CpSolver()
            core_solver.parameters.max_time_in_seconds = remaining_seconds
            core_solver.parameters.random_seed = data.seed
            core_solver.parameters.num_search_workers = 1
            core_status = core_solver.solve(model)
            if core_status == cp_model.INFEASIBLE:
                core_diagnostics = _core_diagnostics(core_solver, assumption_families)
        diagnostics = _deduplicate_diagnostics((*precheck_diagnostics, *core_diagnostics))
        if not diagnostics:
            diagnostics = (Diagnostic("infeasible", "当前输入与规则不存在可行方案"),)
        outcome = SolveOutcome(
            "infeasible",
            None,
            diagnostics,
            time.perf_counter() - started,
        )
        _emit_final_progress(on_progress, outcome)
        return outcome

    if status == cp_model.MODEL_INVALID:
        raise RuntimeError(f"invalid CP-SAT model: {solver.response_stats()}")

    outcome = SolveOutcome(
        "timeout",
        None,
        _deduplicate_diagnostics(
            (
                *precheck_diagnostics,
                Diagnostic("solver_timeout", "求解器在找到完整可行方案前达到时间上限"),
            )
        ),
        elapsed,
    )
    _emit_final_progress(on_progress, outcome)
    return outcome
