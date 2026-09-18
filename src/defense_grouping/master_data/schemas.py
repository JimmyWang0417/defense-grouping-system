from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from defense_grouping.db.types import PersonType
from defense_grouping.models.availability import LeaveStatus
from defense_grouping.models.defense import ActivityStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)


class DepartmentUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class DepartmentRead(ORMModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    version: int


class DepartmentChildCreate(BaseModel):
    department_id: UUID
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)


class DepartmentChildUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class MajorRead(ORMModel):
    id: UUID
    department_id: UUID
    code: str
    name: str
    is_active: bool
    version: int


class DirectionUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class DirectionRead(ORMModel):
    id: UUID
    department_id: UUID
    code: str
    name: str
    version: int


class TeacherCreate(BaseModel):
    employee_number: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    department_id: UUID
    title: str = Field(default="", max_length=80)
    title_rank: int = Field(ge=1, le=10)
    direction_ids: set[UUID] = Field(default_factory=set)
    workload_limit: int = Field(ge=1, le=100)


class TeacherUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=80)
    title_rank: int | None = Field(default=None, ge=1, le=10)
    direction_ids: set[UUID] | None = None
    workload_limit: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None


class TeacherRead(ORMModel):
    id: UUID
    employee_number: str
    name: str
    department_id: UUID
    title: str
    title_rank: int
    direction_ids: list[UUID]
    workload_limit: int
    is_active: bool
    version: int


class StudentCreate(BaseModel):
    student_number: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    department_id: UUID
    major_id: UUID
    grade: str = Field(min_length=1, max_length=20)
    direction_ids: set[UUID] = Field(default_factory=set)
    advisor_id: UUID


class StudentUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    major_id: UUID | None = None
    grade: str | None = Field(default=None, min_length=1, max_length=20)
    direction_ids: set[UUID] | None = None
    advisor_id: UUID | None = None
    is_active: bool | None = None


class StudentRead(ORMModel):
    id: UUID
    student_number: str
    name: str
    department_id: UUID
    major_id: UUID
    grade: str
    direction_ids: list[UUID]
    advisor_id: UUID
    is_active: bool
    version: int


class AcademicTermCreate(BaseModel):
    department_id: UUID
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    section_timetable: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dates_in_order(self) -> "AcademicTermCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class AcademicTermUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    section_timetable: dict[str, object] | None = None


class AcademicTermRead(ORMModel):
    id: UUID
    department_id: UUID
    code: str
    name: str
    start_date: date
    end_date: date
    section_timetable: dict[str, object]
    version: int


class IntervalWrite(BaseModel):
    department_id: UUID
    person_type: PersonType
    person_id: UUID
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def interval_in_order(self) -> "IntervalWrite":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("interval datetimes must include a timezone")
        return self


class OccupancyCreate(IntervalWrite):
    academic_term_id: UUID | None = None
    teaching_week: int | None = Field(default=None, ge=1, le=60)
    weekday: int | None = Field(default=None, ge=1, le=7)
    start_section: int | None = Field(default=None, ge=1, le=30)
    end_section: int | None = Field(default=None, ge=1, le=30)


class OccupancyRead(ORMModel):
    id: UUID
    department_id: UUID
    person_type: PersonType
    person_id: UUID
    starts_at: datetime
    ends_at: datetime
    version: int


class OccupancyUpdate(BaseModel):
    version: int = Field(ge=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class LeaveCreate(IntervalWrite):
    reason: str = Field(min_length=2, max_length=1000)


class LeaveUpdate(BaseModel):
    version: int = Field(ge=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, min_length=2, max_length=1000)
    status: LeaveStatus | None = None


class LeaveRead(ORMModel):
    id: UUID
    department_id: UUID
    person_type: PersonType
    person_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str
    status: LeaveStatus
    version: int


class RoomCreate(BaseModel):
    department_id: UUID
    campus: str = Field(min_length=1, max_length=120)
    building: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    capacity: int = Field(ge=1, le=10000)


class RoomUpdate(BaseModel):
    version: int = Field(ge=1)
    campus: str | None = Field(default=None, min_length=1, max_length=120)
    building: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    capacity: int | None = Field(default=None, ge=1, le=10000)


class RoomRead(ORMModel):
    id: UUID
    department_id: UUID
    campus: str
    building: str
    name: str
    capacity: int
    version: int


class ActivityCreate(BaseModel):
    department_id: UUID
    name: str = Field(min_length=1, max_length=200)
    academic_year: str = Field(min_length=1, max_length=20)
    semester: str = Field(min_length=1, max_length=20)
    academic_term_id: UUID | None = None


class ActivityUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: ActivityStatus | None = None


class ActivityRead(ORMModel):
    id: UUID
    department_id: UUID
    name: str
    academic_year: str
    semester: str
    academic_term_id: UUID | None
    status: ActivityStatus
    current_rule_version: int
    version: int


class ActivityRulesWrite(BaseModel):
    students_per_group: int = Field(ge=1, le=100)
    teachers_per_group: int = Field(ge=1, le=20)
    chair_min_title_rank: int = Field(ge=1, le=10)
    teacher_workload_limit: int = Field(ge=1, le=100)
    balance_students_weight: int = Field(ge=0, le=1000)
    balance_teacher_load_weight: int = Field(ge=0, le=1000)
    direction_match_weight: int = Field(ge=0, le=1000)
    compact_schedule_weight: int = Field(ge=0, le=1000)
    exception_use_weight: int = Field(ge=0, le=1000)


class ActivityRulesRead(ActivityRulesWrite):
    id: UUID
    activity_id: UUID
    rule_version: int


class SlotWrite(BaseModel):
    date: date
    start_time: time
    end_time: time
    max_groups: int = Field(ge=1, le=200)

    @model_validator(mode="after")
    def times_in_order(self) -> "SlotWrite":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SlotUpdate(SlotWrite):
    version: int = Field(ge=1)


class SlotRead(ORMModel):
    id: UUID
    activity_id: UUID
    date: date
    start_time: time
    end_time: time
    max_groups: int
    version: int


class ActivityRoomsWrite(BaseModel):
    room_ids: set[UUID]
