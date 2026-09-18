from uuid import UUID

import pytest

from defense_grouping.models.master import Student
from tests.integration.schedule_support import create_ready_plan


@pytest.mark.asyncio
async def test_copy_adjust_compare_and_optimistic_lock(master_harness, configured_schedule) -> None:
    headers, original = await create_ready_plan(master_harness, configured_schedule)
    copied = await master_harness.client.post(
        f"/api/v1/plans/{original['id']}/copy",
        headers=headers,
    )
    assert copied.status_code == 201, copied.text
    draft = copied.json()
    assert draft["status"] == "draft"
    assert draft["source_plan_id"] == original["id"]
    assert draft["version_number"] == original["version_number"] + 1

    group = draft["groups"][0]
    other_room = next(
        str(room_id) for room_id in configured_schedule.room_ids if str(room_id) != group["room_id"]
    )
    conflict = await master_harness.client.patch(
        f"/api/v1/plans/{draft['id']}/groups/{group['id']}",
        headers=headers,
        json={"room_id": other_room, "version": draft["version"] + 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "optimistic_lock_conflict"

    adjusted = await master_harness.client.patch(
        f"/api/v1/plans/{draft['id']}/groups/{group['id']}",
        headers=headers,
        json={"room_id": other_room, "version": draft["version"]},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["groups"][0]["room_id"] == other_room

    comparison = await master_harness.client.get(
        f"/api/v1/plans/{original['id']}/compare/{draft['id']}",
        headers=headers,
    )
    assert comparison.status_code == 200
    assert comparison.json()["resource_changes"][0]["room_changed"] is True


@pytest.mark.asyncio
async def test_publish_is_immutable_and_teacher_confirmation_is_isolated(
    master_harness,
    configured_schedule,
) -> None:
    headers, ready = await create_ready_plan(master_harness, configured_schedule)
    published = await master_harness.client.post(
        f"/api/v1/plans/{ready['id']}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    group = published.json()["groups"][0]
    immutable = await master_harness.client.patch(
        f"/api/v1/plans/{ready['id']}/groups/{group['id']}",
        headers=headers,
        json={
            "room_id": str(configured_schedule.room_ids[0]),
            "version": published.json()["version"],
        },
    )
    assert immutable.status_code == 409
    assert immutable.json()["error"]["code"] == "published_plan_immutable"

    teacher_headers = await master_harness.headers("teacher-user")
    schedule = await master_harness.client.get("/api/v1/teacher/schedule", headers=teacher_headers)
    assert schedule.status_code == 200, schedule.text
    assert len(schedule.json()) == 1
    assignment = schedule.json()[0]
    assert assignment["plan_id"] == ready["id"]
    assert set(assignment["student_ids"]) == {str(item) for item in configured_schedule.student_ids}

    first = await master_harness.client.post(
        f"/api/v1/teacher/assignments/{assignment['panel_assignment_id']}/confirm",
        headers=teacher_headers,
    )
    second = await master_harness.client.post(
        f"/api/v1/teacher/assignments/{assignment['panel_assignment_id']}/confirm",
        headers=teacher_headers,
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_second_publication_archives_previous_plan(
    master_harness, configured_schedule
) -> None:
    headers, first = await create_ready_plan(master_harness, configured_schedule)
    first_publish = await master_harness.client.post(
        f"/api/v1/plans/{first['id']}/publish",
        headers=headers,
    )
    assert first_publish.status_code == 200
    copied = await master_harness.client.post(
        f"/api/v1/plans/{first['id']}/copy",
        headers=headers,
    )
    assert copied.status_code == 201
    validated = await master_harness.client.post(
        f"/api/v1/plans/{copied.json()['id']}/validate",
        headers=headers,
    )
    assert validated.status_code == 200, validated.text
    second_publish = await master_harness.client.post(
        f"/api/v1/plans/{copied.json()['id']}/publish",
        headers=headers,
    )
    assert second_publish.status_code == 200, second_publish.text

    archived = await master_harness.client.get(f"/api/v1/plans/{first['id']}", headers=headers)
    assert archived.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_publication_revalidation_failure_restores_draft(
    master_harness,
    configured_schedule,
) -> None:
    headers, ready = await create_ready_plan(master_harness, configured_schedule)
    panel_teacher_id = ready["groups"][0]["teacher_ids"][0]
    async with master_harness.database.session() as session:
        student = await session.get(Student, configured_schedule.student_ids[0])
        assert student is not None
        student.advisor_id = UUID(panel_teacher_id)
        await session.commit()

    response = await master_harness.client.post(
        f"/api/v1/plans/{ready['id']}/publish",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_validation_failed"
    refreshed = await master_harness.client.get(f"/api/v1/plans/{ready['id']}", headers=headers)
    assert refreshed.json()["status"] == "draft"
