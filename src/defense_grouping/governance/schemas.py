from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from defense_grouping.models.governance import ApprovalStatus


class ExceptionRequest(BaseModel):
    activity_id: UUID
    constraint_code: Literal[
        "advisor_conflict",
        "course_conflict",
        "leave_conflict",
        "workload_limit",
    ]
    subject_type: Literal["teacher_student", "person_slot", "teacher"]
    teacher_id: UUID | None = None
    student_id: UUID | None = None
    person_id: UUID | None = None
    slot_id: UUID | None = None
    reason: str = Field(min_length=10, max_length=1000)
    expires_at: datetime

    @model_validator(mode="after")
    def exact_scope(self) -> "ExceptionRequest":
        if self.constraint_code == "advisor_conflict":
            valid = (
                self.subject_type == "teacher_student"
                and self.teacher_id is not None
                and self.student_id is not None
                and self.person_id is None
                and self.slot_id is None
            )
        elif self.constraint_code in {"course_conflict", "leave_conflict"}:
            valid = (
                self.subject_type == "person_slot"
                and self.person_id is not None
                and self.slot_id is not None
                and self.teacher_id is None
                and self.student_id is None
            )
        else:
            valid = (
                self.subject_type == "teacher"
                and self.teacher_id is not None
                and self.student_id is None
                and self.person_id is None
                and self.slot_id is None
            )
        if not valid:
            raise ValueError("exception subject IDs must exactly match the constraint scope")
        return self


class ExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_id: UUID
    constraint_code: str
    subject_type: str
    teacher_id: UUID | None
    student_id: UUID | None
    person_id: UUID | None
    slot_id: UUID | None
    reason: str
    requester_id: UUID
    approver_id: UUID | None
    expires_at: datetime
    status: ApprovalStatus
    decided_at: datetime | None
    revoked_at: datetime | None
    version: int


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    action: str
    object_type: str
    object_id: UUID | None
    request_id: str
    before_summary: dict[str, object] | None
    after_summary: dict[str, object] | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditRead]
    page: int
    page_size: int
    total: int
