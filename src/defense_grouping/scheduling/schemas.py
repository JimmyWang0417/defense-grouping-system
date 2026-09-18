from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from defense_grouping.models.defense import ConfirmationStatus, JobStatus, PlanStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ScheduleJobCreate(BaseModel):
    seed: int = Field(default=20260918, ge=0, le=2_147_483_647)
    time_limit_seconds: float = Field(default=60, gt=0, le=600)


class ScheduleJobRead(ORMModel):
    id: UUID
    activity_id: UUID
    status: JobStatus
    stage: str
    progress: float
    random_seed: int
    plan_id: UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class GroupRead(BaseModel):
    id: UUID
    code: str
    slot_id: UUID
    room_id: UUID
    student_ids: list[UUID]
    teacher_ids: list[UUID]
    chair_id: UUID
    version: int


class PlanRead(BaseModel):
    id: UUID
    activity_id: UUID
    version_number: int
    source_plan_id: UUID | None
    status: PlanStatus
    solver_parameters: dict[str, object]
    quality_metrics: dict[str, object]
    exception_snapshot: list[dict[str, object]]
    validated_at: datetime | None
    published_at: datetime | None
    version: int
    groups: list[GroupRead]


class GroupAdjustment(BaseModel):
    version: int = Field(ge=1)
    student_ids: set[UUID] | None = None
    teacher_ids: set[UUID] | None = None
    chair_id: UUID | None = None
    slot_id: UUID | None = None
    room_id: UUID | None = None


class PlanComparison(BaseModel):
    left_plan_id: UUID
    right_plan_id: UUID
    student_moves: list[dict[str, object]]
    teacher_changes: list[dict[str, object]]
    resource_changes: list[dict[str, object]]
    objective_deltas: dict[str, int | float]
    exception_use_delta: int


class TeacherScheduleItem(BaseModel):
    plan_id: UUID
    group_id: UUID
    group_code: str
    panel_assignment_id: UUID
    student_ids: list[UUID]
    fellow_teacher_ids: list[UUID]
    date: date
    start_time: time
    end_time: time
    room_id: UUID
    exception_marker: bool
    confirmation_status: ConfirmationStatus


class ConfirmationRead(BaseModel):
    panel_assignment_id: UUID
    status: ConfirmationStatus
    confirmed_at: datetime | None
    version: int
