from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from defense_grouping.models.governance import ImportStatus


class ImportKind(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    COURSE = "course"
    LEAVE = "leave"
    SLOT = "slot"
    ROOM = "room"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ImportIssue(BaseModel):
    sheet: str
    row: int
    field: str
    severity: Severity
    code: str
    message: str


class ImportPreview(BaseModel):
    id: UUID
    kind: ImportKind
    status: ImportStatus
    progress: int
    creates: int
    updates: int
    unchanged: int
    issues: list[ImportIssue]


class ImportResult(BaseModel):
    id: UUID
    status: ImportStatus
    creates: int
    updates: int
    unchanged: int
