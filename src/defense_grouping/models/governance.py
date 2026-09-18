import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from defense_grouping.db.base import Base, UUIDTimestampMixin, VersionMixin


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ImportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class ConstraintException(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "constraint_exceptions"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    constraint_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("teachers.id", ondelete="RESTRICT"),
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    slot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("defense_slots.id", ondelete="RESTRICT"),
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(
            ApprovalStatus,
            name="approval_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ApprovalStatus.PENDING,
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportBatch(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "import_batches"

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(
            ImportStatus,
            name="import_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ImportStatus.PENDING,
        nullable=False,
    )
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    preview: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    create_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    update_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDTimestampMixin, Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    before_summary: Mapped[dict[str, object] | None] = mapped_column(JSON)
    after_summary: Mapped[dict[str, object] | None] = mapped_column(JSON)
