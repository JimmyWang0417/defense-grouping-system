from enum import StrEnum


class PersonType(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
