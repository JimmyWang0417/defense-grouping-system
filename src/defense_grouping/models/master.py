import uuid
from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from defense_grouping.db.base import Base, UUIDTimestampMixin, VersionMixin


class Department(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Major(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "majors"
    __table_args__ = (UniqueConstraint("department_id", "code", name="uq_majors_department_code"),)

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Direction(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "directions"
    __table_args__ = (
        UniqueConstraint("department_id", "code", name="uq_directions_department_code"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Teacher(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "teachers"

    employee_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        unique=True,
    )
    title: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    title_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    workload_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Student(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "students"

    student_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    major_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("majors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    advisor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TeacherDirection(Base):
    __tablename__ = "teacher_directions"

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("teachers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    direction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("directions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class StudentDirection(Base):
    __tablename__ = "student_directions"

    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        primary_key=True,
    )
    direction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("directions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class AcademicTerm(UUIDTimestampMixin, VersionMixin, Base):
    __tablename__ = "academic_terms"
    __table_args__ = (
        UniqueConstraint("department_id", "code", name="uq_academic_terms_department_code"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    section_timetable: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
