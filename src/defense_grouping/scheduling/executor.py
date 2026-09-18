from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from defense_grouping.db.session import Database
from defense_grouping.models.defense import JobStatus, ScheduleJob
from defense_grouping.scheduling.domain import SchedulingInput
from defense_grouping.scheduling.service import persist_solve_outcome
from defense_grouping.scheduling.solver import SolveOutcome, solve

Worker = Callable[[SchedulingInput, float], SolveOutcome]


def _time_limit(value: object) -> float:
    if isinstance(value, bool):
        return 60
    if isinstance(value, int | float):
        return float(value)
    return 60


class TaskExecutor:
    def __init__(
        self,
        database: Database,
        *,
        max_workers: int = 1,
        worker: Worker = solve,
    ) -> None:
        self._database = database
        self._pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=multiprocessing.get_context("spawn"),
        )
        self._worker = worker
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._closed = False

    async def recover_interrupted_jobs(self) -> int:
        async with self._database.session() as session:
            running_ids = list(
                await session.scalars(
                    select(ScheduleJob.id).where(ScheduleJob.status == JobStatus.RUNNING)
                )
            )
            if not running_ids:
                return 0
            now = datetime.now(UTC)
            await session.execute(
                update(ScheduleJob)
                .where(ScheduleJob.id.in_(running_ids))
                .values(
                    status=JobStatus.FAILED,
                    stage="failed",
                    progress=1,
                    error_code="worker_interrupted",
                    error_message="应用重启导致后台任务中断，请重新提交",
                    finished_at=now,
                    version=ScheduleJob.version + 1,
                )
            )
            await session.commit()
            return len(running_ids)

    def submit(self, job_id: UUID, payload: SchedulingInput) -> None:
        if self._closed:
            raise RuntimeError("task executor is closed")
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return
        self._tasks[job_id] = asyncio.create_task(
            self._execute(job_id, payload),
            name=f"schedule-job-{job_id}",
        )

    def cancel(self, job_id: UUID) -> None:
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()

    async def _execute(self, job_id: UUID, payload: SchedulingInput) -> None:
        try:
            await asyncio.sleep(0)
            async with self._database.session() as session:
                job = await session.get(ScheduleJob, job_id)
                if job is None or job.status == JobStatus.CANCELLED:
                    return
                time_limit = _time_limit(job.input_summary.get("time_limit_seconds"))
                job.status = JobStatus.RUNNING
                job.stage = "solving"
                job.progress = 0.25
                job.started_at = datetime.now(UTC)
                job.version += 1
                await session.commit()

            loop = asyncio.get_running_loop()
            outcome = await loop.run_in_executor(
                self._pool,
                self._worker,
                payload,
                time_limit,
            )
            async with self._database.session() as session:
                await persist_solve_outcome(session, job_id, payload, outcome)
        except asyncio.CancelledError:
            raise
        # The persistence boundary must turn every worker failure into terminal job state.
        except Exception as exc:  # noqa: BLE001
            await self._mark_failed(job_id, exc)
        finally:
            self._tasks.pop(job_id, None)

    async def _mark_failed(self, job_id: UUID, exc: Exception) -> None:
        async with self._database.session() as session:
            job = await session.get(ScheduleJob, job_id)
            if job is None or job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.FAILED
            job.stage = "failed"
            job.progress = 1
            job.error_code = "worker_failed"
            job.error_message = str(exc)[:2000] or type(exc).__name__
            job.finished_at = datetime.now(UTC)
            job.version += 1
            await session.commit()

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(self._pool.shutdown, wait=True, cancel_futures=True)
