from __future__ import annotations

import multiprocessing
import queue
import time

import psutil
import pytest

from defense_grouping.scheduling.domain import SchedulingInput
from defense_grouping.scheduling.solver import SolveOutcome, solve
from defense_grouping.scheduling.validator import validate_solution
from tests.performance.generate_dataset import generate_department_scale_input


def run_solver_fixture(data: SchedulingInput, output: multiprocessing.Queue) -> None:
    output.put(solve(data, time_limit_seconds=60))


@pytest.mark.performance
def test_department_scale_solver_finishes_within_budget() -> None:
    data = generate_department_scale_input()
    assert len(data.students) == 500
    assert len(data.teachers) == 50
    assert data.required_group_count == 20
    assert len(data.slots) == 8
    assert len(data.rooms) == 24

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    worker = context.Process(target=run_solver_fixture, args=(data, output))
    started = time.perf_counter()
    worker.start()
    assert worker.pid is not None
    process = psutil.Process(worker.pid)
    peak_rss = 0
    deadline = started + 65
    while worker.is_alive() and time.perf_counter() < deadline:
        try:
            peak_rss = max(peak_rss, process.memory_info().rss)
        except psutil.Error:
            pass
        time.sleep(0.05)
    if worker.is_alive():
        worker.terminate()
    worker.join(timeout=5)
    elapsed = time.perf_counter() - started

    assert worker.exitcode == 0
    try:
        outcome = output.get(timeout=5)
    except queue.Empty as exc:
        raise AssertionError("solver worker returned no outcome") from exc
    print(
        "department_scale "
        f"elapsed_seconds={elapsed:.2f} "
        f"solver_seconds={outcome.elapsed_seconds:.2f} "
        f"peak_rss_mib={peak_rss / 1024 / 1024:.1f}"
    )
    assert isinstance(outcome, SolveOutcome)
    assert outcome.status in {"feasible", "optimal"}, outcome.diagnostics
    assert outcome.solution is not None
    assert elapsed <= 65
    assert outcome.elapsed_seconds <= 60
    assert peak_rss < 2 * 1024 * 1024 * 1024
    assert validate_solution(data, outcome.solution).valid
