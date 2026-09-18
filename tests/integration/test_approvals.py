from datetime import UTC, datetime, timedelta

import pytest


def advisor_exception_payload(configured_schedule) -> dict[str, object]:
    return {
        "activity_id": str(configured_schedule.activity_id),
        "constraint_code": "advisor_conflict",
        "subject_type": "teacher_student",
        "teacher_id": str(configured_schedule.teacher_ids[2]),
        "student_id": str(configured_schedule.student_ids[0]),
        "reason": "该教师为不可替代的唯一评审专家",
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    }


@pytest.mark.asyncio
async def test_requester_cannot_approve_own_exception(master_harness, configured_schedule) -> None:
    headers = await master_harness.headers()
    created = await master_harness.client.post(
        "/api/v1/exceptions",
        headers=headers,
        json=advisor_exception_payload(configured_schedule),
    )
    assert created.status_code == 201, created.text

    response = await master_harness.client.post(
        f"/api/v1/exceptions/{created.json()['id']}/approve",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_approval_forbidden"


@pytest.mark.asyncio
async def test_approve_reject_revoke_and_scope(master_harness, configured_schedule) -> None:
    requester = await master_harness.headers()
    approver = await master_harness.headers("approver-admin")
    created = await master_harness.client.post(
        "/api/v1/exceptions",
        headers=requester,
        json=advisor_exception_payload(configured_schedule),
    )
    exception_id = created.json()["id"]

    denied = await master_harness.client.post(
        f"/api/v1/exceptions/{exception_id}/approve",
        headers=await master_harness.headers("other-admin"),
    )
    assert denied.status_code == 403
    approved = await master_harness.client.post(
        f"/api/v1/exceptions/{exception_id}/approve",
        headers=approver,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    revoked = await master_harness.client.post(
        f"/api/v1/exceptions/{exception_id}/revoke",
        headers=requester,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    second = await master_harness.client.post(
        "/api/v1/exceptions",
        headers=requester,
        json={
            **advisor_exception_payload(configured_schedule),
            "reason": "第二个例外用于验证拒绝状态流转",
        },
    )
    rejected = await master_harness.client.post(
        f"/api/v1/exceptions/{second.json()['id']}/reject",
        headers=approver,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_expired_and_broad_exceptions_are_rejected(master_harness, configured_schedule) -> None:
    headers = await master_harness.headers()
    expired = await master_harness.client.post(
        "/api/v1/exceptions",
        headers=headers,
        json={
            **advisor_exception_payload(configured_schedule),
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )
    broad = await master_harness.client.post(
        "/api/v1/exceptions",
        headers=headers,
        json={
            **advisor_exception_payload(configured_schedule),
            "student_id": None,
        },
    )

    assert expired.status_code == 422
    assert expired.json()["error"]["code"] == "exception_expired"
    assert broad.status_code == 422
    assert broad.json()["error"]["code"] == "validation_error"
