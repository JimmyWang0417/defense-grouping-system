import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from defense_grouping.db.base import Base, UUIDTimestampMixin, VersionMixin
from defense_grouping.db.types import PersonType


class LeaveStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


PERSON_TYPE_ENUM = Enum(
    PersonType,
    name="person_type",
    native_enum=False,
    values_callable=lambda values: [value.value for value in values],
)


class CourseOccupancy(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "course_occupancies"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "source_fingerprint",
            name="uq_course_occupancies_department_fingerprint",
        ),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_type: Mapped[PersonType] = mapped_column(PERSON_TYPE_ENUM, nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    academic_term_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_terms.id", ondelete="SET NULL"),
    )
    teaching_week: Mapped[int | None] = mapped_column(Integer)
    weekday: Mapped[int | None] = mapped_column(Integer)
    start_section: Mapped[int | None] = mapped_column(Integer)
    end_section: Mapped[int | None] = mapped_column(Integer)


class LeaveRecord(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "leave_records"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "source_fingerprint",
            name="uq_leave_records_department_fingerprint",
        ),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_type: Mapped[PersonType] = mapped_column(PERSON_TYPE_ENUM, nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(
            LeaveStatus,
            name="leave_status",
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=LeaveStatus.APPROVED,
        nullable=False,
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class Room(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("campus", "building", "name", name="uq_rooms_campus_building_name"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campus: Mapped[str] = mapped_column(String(120), nullable=False)
    building: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)


class RoomAvailability(UUIDTimestampMixin, Base):
    __tablename__ = "room_availabilities"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "available_date",
            "start_time",
            "end_time",
            name="uq_room_availabilities_interval",
        ),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    available_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
