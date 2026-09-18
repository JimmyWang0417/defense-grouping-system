from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class JobClient(Protocol):
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]: ...


Sleep = Callable[[float], Awaitable[None]]
UpdateHandler = Callable[[dict[str, Any]], None]
TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled"})


async def poll_schedule_job(
    client: JobClient,
    job_id: str,
    *,
    sleep: Sleep = asyncio.sleep,
    on_update: UpdateHandler | None = None,
) -> dict[str, Any]:
    interval = 1.0
    while True:
        job = await client.request("GET", f"/api/v1/schedule-jobs/{job_id}")
        if on_update is not None:
            on_update(job)
        if job.get("status") in TERMINAL_JOB_STATES:
            return job
        await sleep(interval)
        interval = min(5.0, interval * 2)
