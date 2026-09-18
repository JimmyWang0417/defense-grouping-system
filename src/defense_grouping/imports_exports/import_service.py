import asyncio
import hashlib
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.errors import APIError
from defense_grouping.db.session import Database
from defense_grouping.db.types import PersonType
from defense_grouping.imports_exports.schemas import (
    ImportIssue,
    ImportKind,
    ImportPreview,
    ImportResult,
    Severity,
)
from defense_grouping.imports_exports.templates import (
    TEMPLATES,
    ParsedRow,
    ParseResult,
    parse_workbook,
)
from defense_grouping.master_data.service import interval_fingerprint, validate_directions
from defense_grouping.models.availability import (
    CourseOccupancy,
    LeaveRecord,
    Room,
    RoomAvailability,
)
from defense_grouping.models.defense import DefenseActivity, DefenseSlot
from defense_grouping.models.governance import AuditLog, ImportBatch, ImportStatus
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

IMPORT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="excel-import")
SHANGHAI = ZoneInfo("Asia/Shanghai")
TITLE_RANKS = {"教授": 5, "副教授": 4, "讲师": 3, "助教": 2}
SECTION_TIMES: dict[int, tuple[time, time]] = {
    1: (time(8, 0), time(8, 45)),
    2: (time(8, 55), time(9, 40)),
    3: (time(10, 0), time(10, 45)),
    4: (time(10, 55), time(11, 40)),
    5: (time(14, 0), time(14, 45)),
    6: (time(14, 55), time(15, 40)),
    7: (time(16, 0), time(16, 45)),
    8: (time(16, 55), time(17, 40)),
    9: (time(19, 0), time(19, 45)),
    10: (time(19, 55), time(20, 40)),
    11: (time(20, 50), time(21, 35)),
    12: (time(21, 45), time(22, 30)),
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_directions(value: object) -> list[str]:
    if value in (None, ""):
        return []
    return [item.strip() for item in re.split(r"[、,，;；]", str(value)) if item.strip()]


def parse_person_type(value: object) -> PersonType | None:
    normalized = str(value).strip().casefold()
    if normalized in {"教师", "teacher"}:
        return PersonType.TEACHER
    if normalized in {"学生", "student"}:
        return PersonType.STUDENT
    return None


def parse_date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def parse_time_value(value: object) -> time:
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    return time.fromisoformat(str(value).strip())


def parse_datetime_value(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)


def issue(row: ParsedRow, field: str, code: str, message: str) -> ImportIssue:
    return ImportIssue(
        sheet=row.sheet,
        row=row.row,
        field=field,
        severity=Severity.ERROR,
        code=code,
        message=message,
    )


def required_fields(row: ParsedRow, fields: Sequence[str]) -> list[ImportIssue]:
    return [
        issue(row, field, "required", "该字段不能为空")
        for field in fields
        if row.values.get(field) in (None, "")
    ]


async def resolve_direction_ids(
    session: AsyncSession,
    department_id: UUID,
    names: list[str],
) -> tuple[list[str], list[str]]:
    if not names:
        return [], []
    rows = (
        await session.scalars(
            select(Direction).where(
                Direction.department_id == department_id,
                Direction.name.in_(names),
            )
        )
    ).all()
    by_name = {row.name: str(row.id) for row in rows}
    missing = [name for name in names if name not in by_name]
    return [by_name[name] for name in names if name in by_name], missing


async def resolve_person(
    session: AsyncSession,
    person_type: PersonType,
    number: str,
    department_id: UUID,
) -> UUID | None:
    if person_type is PersonType.TEACHER:
        teacher_id: UUID | None = await session.scalar(
            select(Teacher.id).where(
                Teacher.employee_number == number,
                Teacher.department_id == department_id,
            )
        )
        return teacher_id
    student_id: UUID | None = await session.scalar(
        select(Student.id).where(
            Student.student_number == number,
            Student.department_id == department_id,
        )
    )
    return student_id


async def validate_student_row(
    session: AsyncSession,
    batch: ImportBatch,
    department: Department,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("学号", "姓名", "院系", "专业", "年级", "导师工号"))
    if issues:
        return None, issues, False
    if str(row.values["院系"]).strip() != department.name:
        issues.append(issue(row, "院系", "department_mismatch", "院系与当前导入范围不一致"))
    major = await session.scalar(
        select(Major).where(
            Major.department_id == batch.department_id,
            Major.name == str(row.values["专业"]).strip(),
        )
    )
    if major is None:
        issues.append(issue(row, "专业", "major_not_found", "专业不存在"))
    advisor = await session.scalar(
        select(Teacher).where(
            Teacher.department_id == batch.department_id,
            Teacher.employee_number == str(row.values["导师工号"]).strip(),
        )
    )
    if advisor is None:
        issues.append(issue(row, "导师工号", "advisor_not_found", "导师工号不存在"))
    direction_ids, missing = await resolve_direction_ids(
        session,
        batch.department_id,
        split_directions(row.values.get("专业方向")),
    )
    if missing:
        issues.append(issue(row, "专业方向", "direction_not_found", f"专业方向不存在：{'、'.join(missing)}"))
    if issues or major is None or advisor is None:
        return None, issues, False
    number = str(row.values["学号"]).strip()
    existing = await session.scalar(select(Student.id).where(Student.student_number == number))
    return (
        {
            "student_number": number,
            "name": str(row.values["姓名"]).strip(),
            "department_id": str(batch.department_id),
            "major_id": str(major.id),
            "grade": str(row.values["年级"]).strip(),
            "direction_ids": direction_ids,
            "advisor_id": str(advisor.id),
        },
        [],
        existing is not None,
    )


async def validate_teacher_row(
    session: AsyncSession,
    batch: ImportBatch,
    department: Department,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("工号", "姓名", "院系", "职称", "工作量上限"))
    if issues:
        return None, issues, False
    if str(row.values["院系"]).strip() != department.name:
        issues.append(issue(row, "院系", "department_mismatch", "院系与当前导入范围不一致"))
    direction_ids, missing = await resolve_direction_ids(
        session,
        batch.department_id,
        split_directions(row.values.get("专业方向")),
    )
    if missing:
        issues.append(issue(row, "专业方向", "direction_not_found", f"专业方向不存在：{'、'.join(missing)}"))
    try:
        workload_limit = int(row.values["工作量上限"])
        if workload_limit < 1:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(issue(row, "工作量上限", "invalid_integer", "工作量上限必须为正整数"))
        workload_limit = 1
    if issues:
        return None, issues, False
    number = str(row.values["工号"]).strip()
    existing = await session.scalar(select(Teacher.id).where(Teacher.employee_number == number))
    title = str(row.values["职称"]).strip()
    return (
        {
            "employee_number": number,
            "name": str(row.values["姓名"]).strip(),
            "department_id": str(batch.department_id),
            "title": title,
            "title_rank": TITLE_RANKS.get(title, 1),
            "direction_ids": direction_ids,
            "workload_limit": workload_limit,
        },
        [],
        existing is not None,
    )


async def course_interval(
    session: AsyncSession,
    batch: ImportBatch,
    row: ParsedRow,
) -> tuple[datetime, datetime]:
    start_section = int(row.values["开始节次"])
    end_section = int(row.values["结束节次"])
    if start_section not in SECTION_TIMES or end_section not in SECTION_TIMES or end_section < start_section:
        raise ValueError("invalid section interval")
    raw_date = row.values["日期或教学周"]
    try:
        target_date = parse_date_value(raw_date)
    except (TypeError, ValueError):
        match = re.fullmatch(r"(.+)-第(\d+)周", str(raw_date).strip())
        if match is None:
            raise ValueError("invalid date or teaching week") from None
        term = await session.scalar(
            select(AcademicTerm).where(
                AcademicTerm.department_id == batch.department_id,
                AcademicTerm.code == match.group(1),
            )
        )
        if term is None:
            raise ValueError("academic term not found")
        weekday = int(row.values["星期"])
        if weekday < 1 or weekday > 7:
            raise ValueError("invalid weekday")
        target_date = term.start_date + timedelta(weeks=int(match.group(2)) - 1, days=weekday - 1)
    start = datetime.combine(target_date, SECTION_TIMES[start_section][0], SHANGHAI).astimezone(UTC)
    end = datetime.combine(target_date, SECTION_TIMES[end_section][1], SHANGHAI).astimezone(UTC)
    return start, end


async def validate_course_row(
    session: AsyncSession,
    batch: ImportBatch,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("人员编号", "人员类型", "日期或教学周", "开始节次", "结束节次"))
    if issues:
        return None, issues, False
    person_type = parse_person_type(row.values["人员类型"])
    if person_type is None:
        return None, [issue(row, "人员类型", "invalid_person_type", "人员类型必须为教师或学生")], False
    number = str(row.values["人员编号"]).strip()
    person_id = await resolve_person(session, person_type, number, batch.department_id)
    if person_id is None:
        issues.append(issue(row, "人员编号", "person_not_found", "人员编号不存在"))
    try:
        starts_at, ends_at = await course_interval(session, batch, row)
    except (TypeError, ValueError):
        issues.append(issue(row, "日期或教学周", "invalid_course_interval", "课程日期、教学周或节次无效"))
        starts_at = ends_at = datetime.now(UTC)
    if issues:
        return None, issues, False
    fingerprint = interval_fingerprint(person_type, person_id, starts_at, ends_at)
    existing = await session.scalar(
        select(CourseOccupancy.id).where(
            CourseOccupancy.department_id == batch.department_id,
            CourseOccupancy.source_fingerprint == fingerprint,
        )
    )
    return (
        {
            "department_id": str(batch.department_id),
            "person_type": person_type.value,
            "person_id": str(person_id),
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "source_fingerprint": fingerprint,
        },
        [],
        existing is not None,
    )


async def validate_leave_row(
    session: AsyncSession,
    batch: ImportBatch,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("人员编号", "人员类型", "开始时间", "结束时间", "原因"))
    if issues:
        return None, issues, False
    person_type = parse_person_type(row.values["人员类型"])
    if person_type is None:
        return None, [issue(row, "人员类型", "invalid_person_type", "人员类型必须为教师或学生")], False
    number = str(row.values["人员编号"]).strip()
    person_id = await resolve_person(session, person_type, number, batch.department_id)
    if person_id is None:
        issues.append(issue(row, "人员编号", "person_not_found", "人员编号不存在"))
    try:
        starts_at = parse_datetime_value(row.values["开始时间"])
        ends_at = parse_datetime_value(row.values["结束时间"])
        if ends_at <= starts_at:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(issue(row, "结束时间", "invalid_interval", "结束时间必须晚于开始时间"))
        starts_at = ends_at = datetime.now(UTC)
    if issues:
        return None, issues, False
    fingerprint = interval_fingerprint(person_type, person_id, starts_at, ends_at, row.values["原因"])
    existing = await session.scalar(
        select(LeaveRecord.id).where(
            LeaveRecord.department_id == batch.department_id,
            LeaveRecord.source_fingerprint == fingerprint,
        )
    )
    return (
        {
            "department_id": str(batch.department_id),
            "person_type": person_type.value,
            "person_id": str(person_id),
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "reason": str(row.values["原因"]).strip(),
            "source_fingerprint": fingerprint,
        },
        [],
        existing is not None,
    )


async def validate_slot_row(
    session: AsyncSession,
    batch: ImportBatch,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("活动", "日期", "开始时间", "结束时间", "最大组数"))
    if issues:
        return None, issues, False
    activity = await session.scalar(
        select(DefenseActivity).where(
            DefenseActivity.department_id == batch.department_id,
            DefenseActivity.name == str(row.values["活动"]).strip(),
        )
    )
    if activity is None:
        issues.append(issue(row, "活动", "activity_not_found", "答辩活动不存在"))
    try:
        slot_date = parse_date_value(row.values["日期"])
        start_time = parse_time_value(row.values["开始时间"])
        end_time = parse_time_value(row.values["结束时间"])
        max_groups = int(row.values["最大组数"])
        if end_time <= start_time or max_groups < 1:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(issue(row, "开始时间", "invalid_slot", "日期、时间或最大组数无效"))
        slot_date, start_time, end_time, max_groups = datetime.now(UTC).date(), time(), time(), 1
    if issues or activity is None:
        return None, issues, False
    existing = await session.scalar(
        select(DefenseSlot.id).where(
            DefenseSlot.activity_id == activity.id,
            DefenseSlot.slot_date == slot_date,
            DefenseSlot.start_time == start_time,
            DefenseSlot.end_time == end_time,
        )
    )
    return (
        {
            "activity_id": str(activity.id),
            "date": slot_date.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "max_groups": max_groups,
        },
        [],
        existing is not None,
    )


async def validate_room_row(
    session: AsyncSession,
    batch: ImportBatch,
    row: ParsedRow,
) -> tuple[dict[str, Any] | None, list[ImportIssue], bool]:
    issues = required_fields(row, ("校区", "楼宇", "教室", "容量"))
    try:
        capacity = int(row.values["容量"])
        if capacity < 1:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(issue(row, "容量", "invalid_capacity", "容量必须为正整数"))
        capacity = 1
    availability = str(row.values.get("可用日期时段") or "").strip()
    if availability and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}-\d{2}:\d{2}", availability) is None:
        issues.append(issue(row, "可用日期时段", "invalid_room_interval", "格式应为 YYYY-MM-DD HH:MM-HH:MM"))
    if issues:
        return None, issues, False
    campus = str(row.values["校区"]).strip()
    building = str(row.values["楼宇"]).strip()
    name = str(row.values["教室"]).strip()
    existing = await session.scalar(
        select(Room.id).where(Room.campus == campus, Room.building == building, Room.name == name)
    )
    return (
        {
            "department_id": str(batch.department_id),
            "campus": campus,
            "building": building,
            "name": name,
            "capacity": capacity,
            "availability": availability,
        },
        [],
        existing is not None,
    )


async def validate_parsed(
    session: AsyncSession,
    batch: ImportBatch,
    parsed: ParseResult,
) -> dict[str, Any]:
    kind = ImportKind(batch.template_kind)
    department = await session.get(Department, batch.department_id)
    if department is None:
        raise ValueError("department no longer exists")
    issues = [
        ImportIssue(
            sheet=TEMPLATES[kind].sheet_name,
            row=row_number,
            field=field,
            severity=Severity.ERROR,
            code=code,
            message=message,
        )
        for row_number, field, code, message in parsed.structural_errors
    ]
    commands: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    creates = updates = 0
    for row in parsed.rows:
        if kind is ImportKind.STUDENT:
            command, row_issues, existing = await validate_student_row(
                session, batch, department, row
            )
        elif kind is ImportKind.TEACHER:
            command, row_issues, existing = await validate_teacher_row(
                session, batch, department, row
            )
        elif kind is ImportKind.COURSE:
            command, row_issues, existing = await validate_course_row(session, batch, row)
        elif kind is ImportKind.LEAVE:
            command, row_issues, existing = await validate_leave_row(session, batch, row)
        elif kind is ImportKind.SLOT:
            command, row_issues, existing = await validate_slot_row(session, batch, row)
        else:
            command, row_issues, existing = await validate_room_row(session, batch, row)
        issues.extend(row_issues)
        if command is None:
            continue
        business_key = json_key(kind, command)
        if business_key in seen_keys:
            issues.append(issue(row, first_key_field(kind), "duplicate_row", "文件内业务键重复"))
            continue
        seen_keys.add(business_key)
        commands.append(command)
        if existing:
            updates += 1
        else:
            creates += 1
    return {
        "progress": 100,
        "issues": [item.model_dump(mode="json") for item in issues],
        "commands": commands,
        "creates": creates,
        "updates": updates,
        "unchanged": 0,
    }


def json_key(kind: ImportKind, command: dict[str, Any]) -> str:
    fields = {
        ImportKind.STUDENT: ("student_number",),
        ImportKind.TEACHER: ("employee_number",),
        ImportKind.COURSE: ("source_fingerprint",),
        ImportKind.LEAVE: ("source_fingerprint",),
        ImportKind.SLOT: ("activity_id", "date", "start_time", "end_time"),
        ImportKind.ROOM: ("campus", "building", "name"),
    }[kind]
    return "|".join(str(command[field]) for field in fields)


def first_key_field(kind: ImportKind) -> str:
    return {
        ImportKind.STUDENT: "学号",
        ImportKind.TEACHER: "工号",
        ImportKind.COURSE: "人员编号",
        ImportKind.LEAVE: "人员编号",
        ImportKind.SLOT: "活动",
        ImportKind.ROOM: "教室",
    }[kind]


async def run_preflight(database: Database, batch_id: UUID) -> None:
    async with database.session() as session:
        batch = await session.get(ImportBatch, batch_id)
        if batch is None:
            return
        batch.status = ImportStatus.RUNNING
        batch.preview = {"progress": 10, "issues": [], "commands": []}
        await session.commit()
        try:
            loop = asyncio.get_running_loop()
            parsed = await loop.run_in_executor(
                IMPORT_POOL,
                parse_workbook,
                Path(batch.stored_path),
                ImportKind(batch.template_kind),
            )
            preview = await validate_parsed(session, batch, parsed)
            batch.preview = preview
            batch.create_count = cast(int, preview["creates"])
            batch.update_count = cast(int, preview["updates"])
            batch.unchanged_count = cast(int, preview["unchanged"])
            preview_issues = cast(list[dict[str, Any]], preview["issues"])
            has_errors = any(item["severity"] == Severity.ERROR for item in preview_issues)
            batch.status = ImportStatus.READY if not has_errors else ImportStatus.FAILED
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - persistent jobs must capture every worker error
            await session.rollback()
            batch = await session.get(ImportBatch, batch_id)
            if batch is not None:
                batch.status = ImportStatus.FAILED
                batch.preview = {
                    "progress": 100,
                    "issues": [
                        ImportIssue(
                            sheet=batch.template_kind,
                            row=1,
                            field="",
                            severity=Severity.ERROR,
                            code="workbook_parse_failed",
                            message=f"工作簿解析失败：{type(exc).__name__}",
                        ).model_dump(mode="json")
                    ],
                    "commands": [],
                    "creates": 0,
                    "updates": 0,
                    "unchanged": 0,
                }
                await session.commit()


def preview_from_batch(batch: ImportBatch) -> ImportPreview:
    preview = batch.preview or {}
    progress_value = preview.get("progress", 0)
    progress = progress_value if isinstance(progress_value, int) else 0
    return ImportPreview(
        id=batch.id,
        kind=ImportKind(batch.template_kind),
        status=batch.status,
        progress=progress,
        creates=batch.create_count,
        updates=batch.update_count,
        unchanged=batch.unchanged_count,
        issues=[
            ImportIssue.model_validate(item)
            for item in cast(list[dict[str, Any]], preview.get("issues", []))
        ],
    )


class ImportWriter(Protocol):
    async def apply(
        self,
        session: AsyncSession,
        batch: ImportBatch,
        commands: list[dict[str, Any]],
    ) -> tuple[int, int, int]: ...


class DefaultImportWriter:
    async def apply(
        self,
        session: AsyncSession,
        batch: ImportBatch,
        commands: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        handler = {
            ImportKind.STUDENT: self._students,
            ImportKind.TEACHER: self._teachers,
            ImportKind.COURSE: self._courses,
            ImportKind.LEAVE: self._leaves,
            ImportKind.SLOT: self._slots,
            ImportKind.ROOM: self._rooms,
        }[ImportKind(batch.template_kind)]
        return await handler(session, batch, commands)

    async def _students(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        creates = updates = 0
        for command in commands:
            major = await session.get(Major, UUID(command["major_id"]))
            advisor = await session.get(Teacher, UUID(command["advisor_id"]))
            direction_ids = {UUID(item) for item in command["direction_ids"]}
            if (
                major is None
                or major.department_id != batch.department_id
                or advisor is None
                or advisor.department_id != batch.department_id
            ):
                raise ValueError("student references changed after preflight")
            await validate_directions(session, batch.department_id, direction_ids)
            student = await session.scalar(
                select(Student).where(Student.student_number == command["student_number"])
            )
            if student is None:
                student = Student(
                    student_number=command["student_number"],
                    department_id=batch.department_id,
                    name=command["name"],
                    major_id=major.id,
                    advisor_id=advisor.id,
                    grade=command["grade"],
                    is_active=True,
                )
                session.add(student)
                await session.flush()
                creates += 1
            else:
                if student.department_id != batch.department_id:
                    raise ValueError("student belongs to another department")
                student.name = command["name"]
                student.major_id = major.id
                student.advisor_id = advisor.id
                student.grade = command["grade"]
                student.is_active = True
                student.version += 1
                await session.execute(
                    delete(StudentDirection).where(StudentDirection.student_id == student.id)
                )
                updates += 1
            session.add_all(
                [
                    StudentDirection(student_id=student.id, direction_id=direction_id)
                    for direction_id in direction_ids
                ]
            )
        return creates, updates, 0

    async def _teachers(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        creates = updates = 0
        for command in commands:
            direction_ids = {UUID(item) for item in command["direction_ids"]}
            await validate_directions(session, batch.department_id, direction_ids)
            teacher = await session.scalar(
                select(Teacher).where(Teacher.employee_number == command["employee_number"])
            )
            if teacher is None:
                teacher = Teacher(
                    employee_number=command["employee_number"],
                    department_id=batch.department_id,
                    name=command["name"],
                    title=command["title"],
                    title_rank=command["title_rank"],
                    workload_limit=command["workload_limit"],
                    is_active=True,
                )
                session.add(teacher)
                await session.flush()
                creates += 1
            else:
                if teacher.department_id != batch.department_id:
                    raise ValueError("teacher belongs to another department")
                teacher.name = command["name"]
                teacher.title = command["title"]
                teacher.title_rank = command["title_rank"]
                teacher.workload_limit = command["workload_limit"]
                teacher.is_active = True
                teacher.version += 1
                await session.execute(
                    delete(TeacherDirection).where(TeacherDirection.teacher_id == teacher.id)
                )
                updates += 1
            session.add_all(
                [
                    TeacherDirection(teacher_id=teacher.id, direction_id=direction_id)
                    for direction_id in direction_ids
                ]
            )
        return creates, updates, 0

    async def _courses(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        creates = unchanged = 0
        for command in commands:
            existing = await session.scalar(
                select(CourseOccupancy.id).where(
                    CourseOccupancy.department_id == batch.department_id,
                    CourseOccupancy.source_fingerprint == command["source_fingerprint"],
                )
            )
            if existing is not None:
                unchanged += 1
                continue
            session.add(
                CourseOccupancy(
                    department_id=batch.department_id,
                    person_type=PersonType(command["person_type"]),
                    person_id=UUID(command["person_id"]),
                    starts_at=datetime.fromisoformat(command["starts_at"]),
                    ends_at=datetime.fromisoformat(command["ends_at"]),
                    source_fingerprint=command["source_fingerprint"],
                )
            )
            creates += 1
        return creates, 0, unchanged

    async def _leaves(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        creates = unchanged = 0
        for command in commands:
            existing = await session.scalar(
                select(LeaveRecord.id).where(
                    LeaveRecord.department_id == batch.department_id,
                    LeaveRecord.source_fingerprint == command["source_fingerprint"],
                )
            )
            if existing is not None:
                unchanged += 1
                continue
            session.add(
                LeaveRecord(
                    department_id=batch.department_id,
                    person_type=PersonType(command["person_type"]),
                    person_id=UUID(command["person_id"]),
                    starts_at=datetime.fromisoformat(command["starts_at"]),
                    ends_at=datetime.fromisoformat(command["ends_at"]),
                    reason=command["reason"],
                    source_fingerprint=command["source_fingerprint"],
                )
            )
            creates += 1
        return creates, 0, unchanged

    async def _slots(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        del batch
        creates = updates = 0
        for command in commands:
            activity_id = UUID(command["activity_id"])
            slot_date = date.fromisoformat(command["date"])
            start_time = time.fromisoformat(command["start_time"])
            end_time = time.fromisoformat(command["end_time"])
            slot = await session.scalar(
                select(DefenseSlot).where(
                    DefenseSlot.activity_id == activity_id,
                    DefenseSlot.slot_date == slot_date,
                    DefenseSlot.start_time == start_time,
                    DefenseSlot.end_time == end_time,
                )
            )
            if slot is None:
                session.add(
                    DefenseSlot(
                        activity_id=activity_id,
                        slot_date=slot_date,
                        start_time=start_time,
                        end_time=end_time,
                        max_groups=command["max_groups"],
                    )
                )
                creates += 1
            else:
                slot.max_groups = command["max_groups"]
                slot.version += 1
                updates += 1
        return creates, updates, 0

    async def _rooms(
        self, session: AsyncSession, batch: ImportBatch, commands: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        creates = updates = 0
        for command in commands:
            room = await session.scalar(
                select(Room).where(
                    Room.campus == command["campus"],
                    Room.building == command["building"],
                    Room.name == command["name"],
                )
            )
            if room is None:
                room = Room(
                    department_id=batch.department_id,
                    campus=command["campus"],
                    building=command["building"],
                    name=command["name"],
                    capacity=command["capacity"],
                )
                session.add(room)
                await session.flush()
                creates += 1
            else:
                if room.department_id != batch.department_id:
                    raise ValueError("room belongs to another department")
                room.capacity = command["capacity"]
                room.version += 1
                updates += 1
            if command["availability"]:
                date_part, interval = command["availability"].split(" ", 1)
                start_text, end_text = interval.split("-", 1)
                available_date = date.fromisoformat(date_part)
                start_time = time.fromisoformat(start_text)
                end_time = time.fromisoformat(end_text)
                exists = await session.scalar(
                    select(RoomAvailability.id).where(
                        RoomAvailability.room_id == room.id,
                        RoomAvailability.available_date == available_date,
                        RoomAvailability.start_time == start_time,
                        RoomAvailability.end_time == end_time,
                    )
                )
                if exists is None:
                    session.add(
                        RoomAvailability(
                            room_id=room.id,
                            available_date=available_date,
                            start_time=start_time,
                            end_time=end_time,
                        )
                    )
        return creates, updates, 0


async def confirm_import(
    session: AsyncSession,
    batch: ImportBatch,
    writer: ImportWriter,
    *,
    actor_id: UUID,
    request_id: str,
) -> ImportResult:
    batch_id = batch.id
    path = Path(batch.stored_path)
    if not path.is_file() or file_sha256(path) != batch.file_sha256:
        raise APIError(
            status_code=409,
            code="import_file_changed",
            message="上传文件在预检后发生变化，请重新上传",
        )
    if batch.status is not ImportStatus.READY:
        raise APIError(
            status_code=409,
            code="import_not_ready",
            message="导入批次尚未通过预检或已经确认",
        )
    commands = cast(list[dict[str, Any]], batch.preview.get("commands", []))
    try:
        creates, updates, unchanged = await writer.apply(session, batch, commands)
        batch.status = ImportStatus.CONFIRMED
        batch.create_count = creates
        batch.update_count = updates
        batch.unchanged_count = unchanged
        batch.confirmed_at = datetime.now(UTC)
        session.add(
            AuditLog(
                actor_id=actor_id,
                action="import.confirmed",
                object_type="import_batch",
                object_id=batch_id,
                request_id=request_id,
                before_summary={"status": ImportStatus.READY.value},
                after_summary={
                    "status": ImportStatus.CONFIRMED.value,
                    "creates": creates,
                    "updates": updates,
                    "unchanged": unchanged,
                },
            )
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        failed_batch = await session.get(ImportBatch, batch_id)
        if failed_batch is not None:
            failed_batch.status = ImportStatus.FAILED
            await session.commit()
        raise APIError(
            status_code=500,
            code="import_write_failed",
            message="导入写入失败，全部数据已回滚",
        ) from exc
    return ImportResult(
        id=batch_id,
        status=batch.status,
        creates=creates,
        updates=updates,
        unchanged=unchanged,
    )
