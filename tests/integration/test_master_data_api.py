from datetime import UTC, datetime

import pytest


async def create_major_and_direction(master_harness, headers):
    major = await master_harness.client.post(
        "/api/v1/majors",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "code": "SE",
            "name": "软件工程",
        },
    )
    direction = await master_harness.client.post(
        "/api/v1/directions",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "code": "AI",
            "name": "人工智能",
        },
    )
    assert major.status_code == direction.status_code == 201
    return major.json(), direction.json()


async def create_teacher(master_harness, headers, number="T001"):
    response = await master_harness.client.post(
        "/api/v1/teachers",
        headers=headers,
        json={
            "employee_number": number,
            "name": f"教师{number}",
            "department_id": str(master_harness.department_id),
            "title": "副教授",
            "title_rank": 4,
            "direction_ids": [],
            "workload_limit": 10,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_student_advisor_must_belong_to_department(master_harness) -> None:
    headers = await master_harness.headers()
    major, direction = await create_major_and_direction(master_harness, headers)

    response = await master_harness.client.post(
        "/api/v1/students",
        headers=headers,
        json={
            "student_number": "S001",
            "name": "李明",
            "department_id": str(master_harness.department_id),
            "major_id": major["id"],
            "grade": "2022",
            "direction_ids": [direction["id"]],
            "advisor_id": str(master_harness.other_teacher_id),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "advisor_department_mismatch"


@pytest.mark.asyncio
async def test_teacher_crud_pagination_scope_and_optimistic_lock(master_harness) -> None:
    headers = await master_harness.headers()
    first = await create_teacher(master_harness, headers, "T001")
    await create_teacher(master_harness, headers, "T002")
    await create_teacher(master_harness, headers, "T003")

    page = await master_harness.client.get(
        "/api/v1/teachers?page=1&page_size=2&search=教师&sort=employee_number",
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert [item["employee_number"] for item in page.json()["items"]] == ["T001", "T002"]

    duplicate = await master_harness.client.post(
        "/api/v1/teachers",
        headers=headers,
        json={
            "employee_number": "T001",
            "name": "重复教师",
            "department_id": str(master_harness.department_id),
            "title": "讲师",
            "title_rank": 3,
            "direction_ids": [],
            "workload_limit": 8,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "teacher_number_exists"

    cross_scope = await master_harness.client.post(
        "/api/v1/teachers",
        headers=headers,
        json={
            "employee_number": "CS-T002",
            "name": "越权教师",
            "department_id": str(master_harness.other_department_id),
            "title": "讲师",
            "title_rank": 3,
            "direction_ids": [],
            "workload_limit": 8,
        },
    )
    assert cross_scope.status_code == 403
    assert cross_scope.json()["error"]["code"] == "department_scope_denied"

    conflict = await master_harness.client.patch(
        f"/api/v1/teachers/{first['id']}",
        headers=headers,
        json={"name": "新姓名", "version": first["version"] + 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "optimistic_lock_conflict"


@pytest.mark.asyncio
async def test_availability_boundaries_return_all_blocks(master_harness) -> None:
    headers = await master_harness.headers()
    teacher = await create_teacher(master_harness, headers)
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

    occupancy = await master_harness.client.post(
        "/api/v1/occupancies",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "person_type": "teacher",
            "person_id": teacher["id"],
            "starts_at": "2026-09-21T09:00:00+08:00",
            "ends_at": "2026-09-21T10:00:00+08:00",
        },
    )
    leave = await master_harness.client.post(
        "/api/v1/leaves",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "person_type": "teacher",
            "person_id": teacher["id"],
            "starts_at": "2026-09-21T09:30:00+08:00",
            "ends_at": "2026-09-21T10:30:00+08:00",
            "reason": "参加学术会议",
        },
    )
    assert occupancy.status_code == leave.status_code == 201

    activity = await master_harness.client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "department_id": str(master_harness.department_id),
            "name": "可用性测试活动",
            "academic_year": "2026-2027",
            "semester": "秋",
        },
    )
    slot = await master_harness.client.post(
        f"/api/v1/activities/{activity.json()['id']}/slots",
        headers=headers,
        json={
            "date": "2026-09-21",
            "start_time": "09:45",
            "end_time": "10:15",
            "max_groups": 1,
        },
    )
    assert activity.status_code == slot.status_code == 201

    from defense_grouping.master_data.service import AvailabilityService

    async with master_harness.database.session() as session:
        service = AvailabilityService(session)
        blocked = await service.for_interval(
            "teacher",
            teacher["id"],
            datetime(2026, 9, 21, 1, 45, tzinfo=UTC),
            datetime(2026, 9, 21, 2, 15, tzinfo=UTC),
        )
        boundary = await service.for_interval(
            "teacher",
            teacher["id"],
            datetime(2026, 9, 21, 2, 30, tzinfo=UTC),
            datetime(2026, 9, 21, 3, 0, tzinfo=UTC),
        )
        by_slot = await service.is_available("teacher", teacher["id"], slot.json()["id"])

    assert not blocked.available
    assert {item.code for item in blocked.blocks} == {"course_conflict", "leave_conflict"}
    assert {item.code for item in by_slot.blocks} == {"course_conflict", "leave_conflict"}
    assert boundary.available


@pytest.mark.asyncio
async def test_room_capacity_is_validated(master_harness) -> None:
    response = await master_harness.client.post(
        "/api/v1/rooms",
        headers=await master_harness.headers(),
        json={
            "department_id": str(master_harness.department_id),
            "campus": "兴庆",
            "building": "主楼",
            "name": "A101",
            "capacity": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
