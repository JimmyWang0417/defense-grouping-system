import pytest


async def create_activity(master_harness, headers):
    response = await master_harness.client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "name": "2026 秋季本科答辩",
            "academic_year": "2026-2027",
            "semester": "秋",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_overlapping_slots_are_rejected(master_harness) -> None:
    headers = await master_harness.headers()
    activity = await create_activity(master_harness, headers)
    first = await master_harness.client.post(
        f"/api/v1/activities/{activity['id']}/slots",
        headers=headers,
        json={
            "date": "2026-10-12",
            "start_time": "08:00",
            "end_time": "10:00",
            "max_groups": 4,
        },
    )
    assert first.status_code == 201

    response = await master_harness.client.post(
        f"/api/v1/activities/{activity['id']}/slots",
        headers=headers,
        json={
            "date": "2026-10-12",
            "start_time": "09:00",
            "end_time": "11:00",
            "max_groups": 4,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_overlap"


@pytest.mark.asyncio
async def test_activity_rules_rooms_and_snapshot(master_harness) -> None:
    headers = await master_harness.headers()
    activity = await create_activity(master_harness, headers)
    rules = await master_harness.client.put(
        f"/api/v1/activities/{activity['id']}/rules",
        headers=headers,
        json={
            "students_per_group": 25,
            "teachers_per_group": 3,
            "chair_min_title_rank": 4,
            "teacher_workload_limit": 8,
            "balance_students_weight": 100,
            "balance_teacher_load_weight": 50,
            "direction_match_weight": 30,
            "compact_schedule_weight": 20,
            "exception_use_weight": 500,
        },
    )
    assert rules.status_code == 200

    slot = await master_harness.client.post(
        f"/api/v1/activities/{activity['id']}/slots",
        headers=headers,
        json={
            "date": "2026-10-12",
            "start_time": "08:00",
            "end_time": "10:00",
            "max_groups": 4,
        },
    )
    assert slot.status_code == 201
    room = await master_harness.client.post(
        "/api/v1/rooms",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "campus": "创新港",
            "building": "泓理楼",
            "name": "1-101",
            "capacity": 30,
        },
    )
    assert room.status_code == 201
    attached = await master_harness.client.put(
        f"/api/v1/activities/{activity['id']}/rooms",
        headers=headers,
        json={"room_ids": [room.json()["id"]]},
    )
    assert attached.status_code == 200

    from defense_grouping.master_data.service import ActivityService

    async with master_harness.database.session() as session:
        snapshot = await ActivityService(session).snapshot(activity["id"])

    assert snapshot.activity_id == activity["id"]
    assert len(snapshot.slots) == 1
    assert len(snapshot.rooms) == 1
    assert snapshot.rules["teachers_per_group"] == 3


@pytest.mark.asyncio
async def test_activity_department_scope_and_rule_validation(master_harness) -> None:
    headers = await master_harness.headers()
    denied = await master_harness.client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "department_id": str(master_harness.other_department_id),
            "name": "越权活动",
            "academic_year": "2026-2027",
            "semester": "秋",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "department_scope_denied"

    activity = await create_activity(master_harness, headers)
    invalid = await master_harness.client.put(
        f"/api/v1/activities/{activity['id']}/rules",
        headers=headers,
        json={
            "students_per_group": 0,
            "teachers_per_group": 3,
            "chair_min_title_rank": 4,
            "teacher_workload_limit": 8,
            "balance_students_weight": 100,
            "balance_teacher_load_weight": 50,
            "direction_match_weight": 30,
            "compact_schedule_weight": 20,
            "exception_use_weight": 500,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
