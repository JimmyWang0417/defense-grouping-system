"""ORM model registry imported by Alembic and application services."""

from defense_grouping.models.availability import (
    CourseOccupancy,
    LeaveRecord,
    Room,
    RoomAvailability,
)
from defense_grouping.models.defense import (
    ActivityRoom,
    ActivityRuleSet,
    DefenseActivity,
    DefenseGroup,
    DefenseSlot,
    PanelAssignment,
    ScheduleJob,
    SchedulePlan,
    StudentAssignment,
    TeacherConfirmation,
)
from defense_grouping.models.governance import AuditLog, ConstraintException, ImportBatch
from defense_grouping.models.identity import RefreshToken, RoleAssignment, User
from defense_grouping.models.master import (
    AcademicTerm,
    Department,
    Direction,
    Major,
    Student,
    StudentDirection,
    Teacher,
    TeacherDirection,
)

__all__ = [
    "AcademicTerm",
    "ActivityRoom",
    "ActivityRuleSet",
    "AuditLog",
    "ConstraintException",
    "CourseOccupancy",
    "DefenseActivity",
    "DefenseGroup",
    "DefenseSlot",
    "Department",
    "Direction",
    "ImportBatch",
    "LeaveRecord",
    "Major",
    "PanelAssignment",
    "RefreshToken",
    "RoleAssignment",
    "Room",
    "RoomAvailability",
    "ScheduleJob",
    "SchedulePlan",
    "Student",
    "StudentAssignment",
    "StudentDirection",
    "Teacher",
    "TeacherConfirmation",
    "TeacherDirection",
    "User",
]
