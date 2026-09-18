import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from defense_grouping.db.base import Base, UUIDTimestampMixin, VersionMixin


class ActivityStatus(StrEnum):
    CONFIGURING = "configuring"
    READY = "ready"
    CLOSED = "closed"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class DefenseActivity(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "defense_activities"

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_terms.id", ondelete="SET NULL"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    semester: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[ActivityStatus] = mapped_column(
        Enum(
            ActivityStatus,
            name="activity_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ActivityStatus.CONFIGURING,
        nullable=False,
    )
    current_rule_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class DefenseSlot(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "defense_slots"
    __table_args__ = (
        UniqueConstraint(
            "activity_id",
            "slot_date",
            "start_time",
            "end_time",
            name="uq_defense_slots_activity_interval",
        ),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    max_groups: Mapped[int] = mapped_column(Integer, nullable=False)


class ActivityRoom(Base):
    __tablename__ = "activity_rooms"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ActivityRuleSet(UUIDTimestampMixin, Base):
    __tablename__ = "activity_rule_sets"
    __table_args__ = (
        UniqueConstraint("activity_id", "rule_version", name="uq_activity_rule_sets_version"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    students_per_group: Mapped[int] = mapped_column(Integer, nullable=False)
    teachers_per_group: Mapped[int] = mapped_column(Integer, nullable=False)
    chair_min_title_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    teacher_workload_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    soft_weights: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)


class ScheduleJob(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "schedule_jobs"
    __table_args__ = (
        UniqueConstraint(
            "created_by_id",
            "idempotency_key",
            name="uq_schedule_jobs_creator_idempotency",
        ),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=JobStatus.PENDING,
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(80), default="pending", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(2000))
    result_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_plans.id", ondelete="SET NULL", use_alter=True),
    )


class SchedulePlan(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "schedule_plans"
    __table_args__ = (
        UniqueConstraint("activity_id", "version_number", name="uq_schedule_plans_version"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_plans.id", ondelete="SET NULL"),
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[PlanStatus] = mapped_column(
        Enum(
            PlanStatus,
            name="plan_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=PlanStatus.DRAFT,
        nullable=False,
    )
    solver_parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    quality_metrics: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    exception_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DefenseGroup(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "defense_groups"
    __table_args__ = (
        UniqueConstraint("plan_id", "code", name="uq_defense_groups_plan_code"),
        UniqueConstraint(
            "plan_id",
            "slot_id",
            "room_id",
            name="uq_defense_groups_plan_slot_room",
        ),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    slot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
    )


class PanelAssignment(UUIDTimestampMixin, Base):
    __tablename__ = "panel_assignments"
    __table_args__ = (
        UniqueConstraint("group_id", "teacher_id", name="uq_panel_assignments_group_teacher"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_chair: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class StudentAssignment(UUIDTimestampMixin, Base):
    __tablename__ = "student_assignments"
    __table_args__ = (
        UniqueConstraint("plan_id", "student_id", name="uq_student_assignments_plan_student"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class TeacherConfirmation(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "teacher_confirmations"

    panel_assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("panel_assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[ConfirmationStatus] = mapped_column(
        Enum(
            ConfirmationStatus,
            name="confirmation_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ConfirmationStatus.PENDING,
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
