import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from defense_grouping.models.defense import JobStatus, ScheduleJob
from defense_grouping.models.identity import User
from defense_grouping.scheduling.domain import Diagnostic
from defense_grouping.scheduling.executor import TaskExecutor
from defense_grouping.scheduling.service import build_scheduling_input, persist_solve_outcome
from defense_grouping.scheduling.solver import solve
from tests.integration.schedule_support import wait_for_job


def exploding_worker(_payload, _time_limit_seconds):
    raise RuntimeError("injected worker failure")


@pytest.mark.asyncio
async def test_schedule_job_creates_new_ready_plan(master_harness, configured_schedule) -> None:
    headers = await master_harness.headers()
    response = await master_harness.client.post(
        f"/api/v1/activities/{configured_schedule.activity_id}/schedule-jobs",
        headers={**headers, "Idempotency-Key": "activity-1-run-1"},
        json={"seed": 20260918, "time_limit_seconds": 5},
    )

    assert response.status_code == 202, response.text
    job = await wait_for_job(master_harness.client, headers, response.json()["id"])
    assert job["status"] == "succeeded", job
    assert job["stage"] == "completed"
    assert job["progress"] == 1.0
    plan = await master_harness.client.get(f"/api/v1/plans/{job['plan_id']}", headers=headers)
    assert plan.status_code == 200
    assert plan.json()["status"] == "ready"
    assert len(plan.json()["groups"]) == 1


@pytest.mark.asyncio
async def test_job_idempotency_and_department_scope(master_harness, configured_schedule) -> None:
    headers = await master_harness.headers()
    request_headers = {**headers, "Idempotency-Key": "same-request"}
    first = await master_harness.client.post(
        f"/api/v1/activities/{configured_schedule.activity_id}/schedule-jobs",
        headers=request_headers,
        json={"seed": 20260918, "time_limit_seconds": 5},
    )
    second = await master_harness.client.post(
        f"/api/v1/activities/{configured_schedule.activity_id}/schedule-jobs",
        headers=request_headers,
        json={"seed": 7, "time_limit_seconds": 1},
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    denied = await master_harness.client.get(
        f"/api/v1/schedule-jobs/{first.json()['id']}",
        headers=await master_harness.headers("other-admin"),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "department_scope_denied"


@pytest.mark.asyncio
async def test_pending_job_can_be_cancelled(master_harness, configured_schedule) -> None:
    async with master_harness.database.session() as session:
        academic_user_id = await session.scalar(
            select(User.id).where(User.username == "academic-admin")
        )
        assert academic_user_id is not None
        job = ScheduleJob(
            activity_id=configured_schedule.activity_id,
            created_by_id=academic_user_id,
            status=JobStatus.PENDING,
            stage="pending",
            progress=0,
            input_summary={},
            random_seed=1,
            idempotency_key=f"cancel-{uuid4()}",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    response = await master_harness.client.delete(
        f"/api/v1/schedule-jobs/{job_id}",
        headers=await master_harness.headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["error_code"] == "cancelled_by_user"


@pytest.mark.asyncio
async def test_worker_exception_is_persisted_as_failed(master_harness, configured_schedule) -> None:
    async with master_harness.database.session() as session:
        academic_user_id = await session.scalar(
            select(User.id).where(User.username == "academic-admin")
        )
        assert academic_user_id is not None
        data = await build_scheduling_input(
            session,
            configured_schedule.activity_id,
            seed=20260918,
        )
        job = ScheduleJob(
            activity_id=configured_schedule.activity_id,
            created_by_id=academic_user_id,
            status=JobStatus.PENDING,
            stage="pending",
            progress=0,
            input_summary={"time_limit_seconds": 5},
            random_seed=20260918,
            idempotency_key=f"worker-failure-{uuid4()}",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    executor = TaskExecutor(master_harness.database, worker=exploding_worker)
    try:
        executor.submit(job_id, data)
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            async with master_harness.database.session() as session:
                persisted = await session.get(ScheduleJob, job_id)
                assert persisted is not None
                if persisted.status == JobStatus.FAILED:
                    break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("worker failure did not reach terminal state")
    finally:
        await executor.shutdown()

    assert persisted.error_code == "worker_failed"
    assert persisted.error_message == "injected worker failure"


@pytest.mark.asyncio
async def test_recovery_marks_interrupted_running_jobs_failed(
    master_harness,
    configured_schedule,
) -> None:
    async with master_harness.database.session() as session:
        academic_user_id = await session.scalar(
            select(User.id).where(User.username == "academic-admin")
        )
        assert academic_user_id is not None
        job = ScheduleJob(
            activity_id=configured_schedule.activity_id,
            created_by_id=academic_user_id,
            status=JobStatus.RUNNING,
            stage="solving",
            progress=0.5,
            input_summary={},
            random_seed=1,
            idempotency_key=f"interrupted-{uuid4()}",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    recovered = await master_harness.app.state.task_executor.recover_interrupted_jobs()

    async with master_harness.database.session() as session:
        persisted = await session.get(ScheduleJob, job_id)
    assert recovered == 1
    assert persisted is not None
    assert persisted.status == JobStatus.FAILED
    assert persisted.error_code == "worker_interrupted"


@pytest.mark.asyncio
async def test_timeout_with_feasible_incumbent_is_persisted(
    master_harness,
    configured_schedule,
) -> None:
    async with master_harness.database.session() as session:
        academic_user_id = await session.scalar(
            select(User.id).where(User.username == "academic-admin")
        )
        assert academic_user_id is not None
        data = await build_scheduling_input(
            session,
            configured_schedule.activity_id,
            seed=20260918,
        )
        job = ScheduleJob(
            activity_id=configured_schedule.activity_id,
            created_by_id=academic_user_id,
            status=JobStatus.RUNNING,
            stage="solving",
            progress=0.5,
            input_summary={"time_limit_seconds": 0.01},
            random_seed=20260918,
            idempotency_key=f"feasible-incumbent-{uuid4()}",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    solved = solve(data, time_limit_seconds=5)
    assert solved.solution is not None
    incumbent = replace(
        solved,
        status="feasible",
        diagnostics=(Diagnostic("solver_timeout", "达到时间上限，保留完整可行解"),),
    )
    async with master_harness.database.session() as session:
        await persist_solve_outcome(session, job_id, data, incumbent)

    async with master_harness.database.session() as session:
        persisted = await session.get(ScheduleJob, job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.SUCCEEDED
    assert persisted.result_plan_id is not None
