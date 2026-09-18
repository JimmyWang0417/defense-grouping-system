import asyncio

import httpx
import pytest

from defense_grouping.client.api_client import ApiClient
from defense_grouping.client.components.task_progress import poll_schedule_job
from defense_grouping.client.session import MemoryRefreshTokenStore
from defense_grouping.client.views.my_schedule import MyScheduleWorkflow
from defense_grouping.client.views.plans import PlanWorkflow
from defense_grouping.client.views.scheduling import SchedulingWorkflow
from tests.integration.conftest import INTEGRATION_PASSWORD


@pytest.mark.asyncio
async def test_admin_can_schedule_publish_and_teacher_confirm(
    master_harness,
    configured_schedule,
) -> None:
    api = ApiClient(
        "http://testserver",
        token_store=MemoryRefreshTokenStore(),
        transport=httpx.ASGITransport(app=master_harness.app),
    )
    try:
        admin = await api.login("academic-admin", INTEGRATION_PASSWORD)
        assert admin.roles == frozenset({"academic_admin"})
        job = await SchedulingWorkflow(api).start(
            str(configured_schedule.activity_id),
            seed=20260918,
            time_limit_seconds=5,
            idempotency_key="e2e-admin-teacher-flow",
        )

        async def short_sleep(_seconds: float) -> None:
            await asyncio.sleep(0.05)

        terminal = await poll_schedule_job(
            api,
            str(job["id"]),
            sleep=short_sleep,
        )
        assert terminal["status"] == "succeeded", terminal
        plan = await PlanWorkflow(api).detail(str(terminal["plan_id"]))
        published = await PlanWorkflow(api).publish(str(plan["id"]))
        assert published["status"] == "published"

        await api.logout()
        teacher = await api.login("teacher-user", INTEGRATION_PASSWORD)
        assert teacher.roles == frozenset({"teacher"})
        teacher_portal = MyScheduleWorkflow(api)
        schedule = await teacher_portal.list()
        assert len(schedule) == 1
        assert schedule[0]["plan_id"] == plan["id"]
        confirmation = await teacher_portal.confirm(
            str(schedule[0]["panel_assignment_id"])
        )
        assert confirmation["status"] == "confirmed"
    finally:
        await api.close()
