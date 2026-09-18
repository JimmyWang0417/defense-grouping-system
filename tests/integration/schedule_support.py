import asyncio


async def wait_for_job(client, headers, job_id: str, *, timeout: float = 15) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/schedule-jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"schedule job {job_id} did not finish within {timeout} seconds")


async def create_ready_plan(master_harness, configured_schedule) -> tuple[dict[str, str], dict[str, object]]:
    headers = await master_harness.headers()
    response = await master_harness.client.post(
        f"/api/v1/activities/{configured_schedule.activity_id}/schedule-jobs",
        headers={**headers, "Idempotency-Key": "task-8-ready-plan"},
        json={"seed": 20260918, "time_limit_seconds": 5},
    )
    assert response.status_code == 202, response.text
    job = await wait_for_job(master_harness.client, headers, response.json()["id"])
    assert job["status"] == "succeeded", job
    plan_response = await master_harness.client.get(
        f"/api/v1/plans/{job['plan_id']}",
        headers=headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    return headers, plan_response.json()
