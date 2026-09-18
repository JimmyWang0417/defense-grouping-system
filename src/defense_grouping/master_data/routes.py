from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.dependencies import get_db_session
from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal, require_roles
from defense_grouping.db.base import as_utc
from defense_grouping.master_data.schemas import (
    AcademicTermCreate,
    AcademicTermRead,
    AcademicTermUpdate,
    ActivityCreate,
    ActivityRead,
    ActivityRoomsWrite,
    ActivityRulesRead,
    ActivityRulesWrite,
    ActivityUpdate,
    DepartmentChildCreate,
    DepartmentChildUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DirectionRead,
    DirectionUpdate,
    LeaveCreate,
    LeaveRead,
    LeaveUpdate,
    MajorRead,
    OccupancyCreate,
    OccupancyRead,
    OccupancyUpdate,
    Page,
    RoomCreate,
    RoomRead,
    RoomUpdate,
    SlotRead,
    SlotUpdate,
    SlotWrite,
    StudentCreate,
    StudentRead,
    StudentUpdate,
    TeacherCreate,
    TeacherRead,
    TeacherUpdate,
)
from defense_grouping.master_data.service import (
    check_version,
    create_activity,
    create_direction,
    create_major,
    create_slot,
    create_student,
    create_teacher,
    ensure_person_in_department,
    get_activity_scoped,
    interval_fingerprint,
    list_teachers,
    normalized_utc,
    require_department_scope,
    scoped_department_ids,
    set_activity_rooms,
    student_read,
    teacher_read,
    validate_directions,
    write_rules,
)
from defense_grouping.models.availability import CourseOccupancy, LeaveRecord, Room
from defense_grouping.models.defense import ActivityRuleSet, DefenseActivity, DefenseSlot
from defense_grouping.models.identity import Role
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

router = APIRouter(prefix="/api/v1")

ScopedAdmin = Annotated[
    Principal,
    Depends(require_roles(Role.SYSTEM_ADMIN, Role.ACADEMIC_ADMIN)),
]
SystemAdmin = Annotated[Principal, Depends(require_roles(Role.SYSTEM_ADMIN))]
Session = Annotated[AsyncSession, Depends(get_db_session)]
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def fetch_page(
    session: AsyncSession,
    statement: Select[Any],
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    total = await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = list(
        await session.scalars(statement.offset((page - 1) * page_size).limit(page_size))
    )
    return rows, int(total or 0)


async def delete_or_conflict(session: AsyncSession, entity: object) -> None:
    try:
        await session.delete(entity)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise APIError(
            status_code=409,
            code="entity_in_use",
            message="该数据正在被其他记录使用，不能删除",
        ) from exc


@router.get("/departments", response_model=Page[DepartmentRead])
async def departments(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "code",
) -> Page[DepartmentRead]:
    statement = select(Department)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(Department.id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Department.code.ilike(pattern), Department.name.ilike(pattern)))
    order = Department.name if sort == "name" else Department.code
    rows, total = await fetch_page(session, statement.order_by(order, Department.id), page, page_size)
    return Page[DepartmentRead](
        items=[DepartmentRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/departments", response_model=DepartmentRead, status_code=201)
async def add_department(payload: DepartmentCreate, _principal: SystemAdmin, session: Session) -> DepartmentRead:
    if await session.scalar(select(Department.id).where(Department.code == payload.code.strip())):
        raise APIError(status_code=409, code="department_code_exists", message="院系代码已存在")
    department = Department(code=payload.code.strip(), name=payload.name.strip(), is_active=True)
    session.add(department)
    await session.commit()
    return DepartmentRead.model_validate(department)


@router.patch("/departments/{department_id}", response_model=DepartmentRead)
async def edit_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    _principal: SystemAdmin,
    session: Session,
) -> DepartmentRead:
    department = await session.get(Department, department_id)
    if department is None:
        raise APIError(status_code=404, code="department_not_found", message="院系不存在")
    check_version(department.version, payload.version)
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(department, name, value)
    department.version += 1
    await session.commit()
    return DepartmentRead.model_validate(department)


@router.delete("/departments/{department_id}", status_code=204)
async def remove_department(department_id: UUID, _principal: SystemAdmin, session: Session) -> Response:
    department = await session.get(Department, department_id)
    if department is None:
        raise APIError(status_code=404, code="department_not_found", message="院系不存在")
    await delete_or_conflict(session, department)
    return Response(status_code=204)


@router.get("/majors", response_model=Page[MajorRead])
async def majors(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "code",
) -> Page[MajorRead]:
    statement = select(Major)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(Major.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Major.code.ilike(pattern), Major.name.ilike(pattern)))
    order = Major.name if sort == "name" else Major.code
    rows, total = await fetch_page(session, statement.order_by(order, Major.id), page, page_size)
    return Page[MajorRead](
        items=[MajorRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/majors", response_model=MajorRead, status_code=201)
async def add_major(payload: DepartmentChildCreate, principal: ScopedAdmin, session: Session) -> MajorRead:
    return await create_major(session, principal, payload)


@router.patch("/majors/{major_id}", response_model=MajorRead)
async def edit_major(
    major_id: UUID,
    payload: DepartmentChildUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> MajorRead:
    major = await session.get(Major, major_id)
    if major is None:
        raise APIError(status_code=404, code="major_not_found", message="专业不存在")
    require_department_scope(principal, major.department_id)
    check_version(major.version, payload.version)
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(major, name, value)
    major.version += 1
    await session.commit()
    return MajorRead.model_validate(major)


@router.delete("/majors/{major_id}", status_code=204)
async def remove_major(major_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    major = await session.get(Major, major_id)
    if major is None:
        raise APIError(status_code=404, code="major_not_found", message="专业不存在")
    require_department_scope(principal, major.department_id)
    await delete_or_conflict(session, major)
    return Response(status_code=204)


@router.get("/directions", response_model=Page[DirectionRead])
async def directions(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "code",
) -> Page[DirectionRead]:
    statement = select(Direction)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(Direction.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Direction.code.ilike(pattern), Direction.name.ilike(pattern)))
    order = Direction.name if sort == "name" else Direction.code
    rows, total = await fetch_page(session, statement.order_by(order, Direction.id), page, page_size)
    return Page[DirectionRead](
        items=[DirectionRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/directions", response_model=DirectionRead, status_code=201)
async def add_direction(
    payload: DepartmentChildCreate,
    principal: ScopedAdmin,
    session: Session,
) -> DirectionRead:
    return DirectionRead.model_validate(await create_direction(session, principal, payload))


@router.patch("/directions/{direction_id}", response_model=DirectionRead)
async def edit_direction(
    direction_id: UUID,
    payload: DirectionUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> DirectionRead:
    direction = await session.get(Direction, direction_id)
    if direction is None:
        raise APIError(status_code=404, code="direction_not_found", message="专业方向不存在")
    require_department_scope(principal, direction.department_id)
    check_version(direction.version, payload.version)
    if payload.name is not None:
        direction.name = payload.name.strip()
    direction.version += 1
    await session.commit()
    return DirectionRead.model_validate(direction)


@router.delete("/directions/{direction_id}", status_code=204)
async def remove_direction(direction_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    direction = await session.get(Direction, direction_id)
    if direction is None:
        raise APIError(status_code=404, code="direction_not_found", message="专业方向不存在")
    require_department_scope(principal, direction.department_id)
    await delete_or_conflict(session, direction)
    return Response(status_code=204)


@router.get("/teachers", response_model=Page[TeacherRead])
async def teachers(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "employee_number",
) -> Page[TeacherRead]:
    items, total = await list_teachers(
        session,
        principal,
        page=page,
        page_size=page_size,
        search=search,
        sort=sort,
    )
    return Page[TeacherRead](items=items, page=page, page_size=page_size, total=total)


@router.post("/teachers", response_model=TeacherRead, status_code=201)
async def add_teacher(payload: TeacherCreate, principal: ScopedAdmin, session: Session) -> TeacherRead:
    return await create_teacher(session, principal, payload)


@router.patch("/teachers/{teacher_id}", response_model=TeacherRead)
async def edit_teacher(
    teacher_id: UUID,
    payload: TeacherUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> TeacherRead:
    teacher = await session.get(Teacher, teacher_id)
    if teacher is None:
        raise APIError(status_code=404, code="teacher_not_found", message="教师不存在")
    require_department_scope(principal, teacher.department_id)
    check_version(teacher.version, payload.version)
    values = payload.model_dump(exclude_unset=True, exclude={"version", "direction_ids"})
    for name, value in values.items():
        setattr(teacher, name, value)
    if payload.direction_ids is not None:
        await validate_directions(session, teacher.department_id, payload.direction_ids)
        await session.execute(
            delete(TeacherDirection).where(TeacherDirection.teacher_id == teacher.id)
        )
        session.add_all(
            [
                TeacherDirection(teacher_id=teacher.id, direction_id=direction_id)
                for direction_id in payload.direction_ids
            ]
        )
    teacher.version += 1
    await session.commit()
    return await teacher_read(session, teacher)


@router.delete("/teachers/{teacher_id}", status_code=204)
async def remove_teacher(teacher_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    teacher = await session.get(Teacher, teacher_id)
    if teacher is None:
        raise APIError(status_code=404, code="teacher_not_found", message="教师不存在")
    require_department_scope(principal, teacher.department_id)
    teacher.is_active = False
    teacher.version += 1
    await session.commit()
    return Response(status_code=204)


@router.get("/students", response_model=Page[StudentRead])
async def students(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "student_number",
) -> Page[StudentRead]:
    statement = select(Student)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(Student.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Student.student_number.ilike(pattern), Student.name.ilike(pattern)))
    order = Student.name if sort == "name" else Student.student_number
    rows, total = await fetch_page(session, statement.order_by(order, Student.id), page, page_size)
    return Page[StudentRead](
        items=[await student_read(session, row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/students", response_model=StudentRead, status_code=201)
async def add_student(payload: StudentCreate, principal: ScopedAdmin, session: Session) -> StudentRead:
    return await create_student(session, principal, payload)


@router.patch("/students/{student_id}", response_model=StudentRead)
async def edit_student(
    student_id: UUID,
    payload: StudentUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> StudentRead:
    student = await session.get(Student, student_id)
    if student is None:
        raise APIError(status_code=404, code="student_not_found", message="学生不存在")
    require_department_scope(principal, student.department_id)
    check_version(student.version, payload.version)
    if payload.major_id is not None:
        major = await session.get(Major, payload.major_id)
        if major is None or major.department_id != student.department_id:
            raise APIError(status_code=422, code="major_department_mismatch", message="专业不属于学生院系")
    if payload.advisor_id is not None:
        advisor = await session.get(Teacher, payload.advisor_id)
        if advisor is None or advisor.department_id != student.department_id:
            raise APIError(status_code=422, code="advisor_department_mismatch", message="导师不属于学生院系")
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version", "direction_ids"}).items():
        setattr(student, name, value)
    if payload.direction_ids is not None:
        await validate_directions(session, student.department_id, payload.direction_ids)
        await session.execute(
            delete(StudentDirection).where(StudentDirection.student_id == student.id)
        )
        session.add_all(
            [
                StudentDirection(student_id=student.id, direction_id=direction_id)
                for direction_id in payload.direction_ids
            ]
        )
    student.version += 1
    await session.commit()
    return await student_read(session, student)


@router.delete("/students/{student_id}", status_code=204)
async def remove_student(student_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    student = await session.get(Student, student_id)
    if student is None:
        raise APIError(status_code=404, code="student_not_found", message="学生不存在")
    require_department_scope(principal, student.department_id)
    student.is_active = False
    student.version += 1
    await session.commit()
    return Response(status_code=204)


@router.get("/terms", response_model=Page[AcademicTermRead])
async def terms(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "code",
) -> Page[AcademicTermRead]:
    statement = select(AcademicTerm)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(AcademicTerm.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(AcademicTerm.code.ilike(pattern), AcademicTerm.name.ilike(pattern)))
    order = AcademicTerm.name if sort == "name" else AcademicTerm.code
    rows, total = await fetch_page(session, statement.order_by(order, AcademicTerm.id), page, page_size)
    return Page[AcademicTermRead](
        items=[AcademicTermRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/terms", response_model=AcademicTermRead, status_code=201)
async def add_term(payload: AcademicTermCreate, principal: ScopedAdmin, session: Session) -> AcademicTermRead:
    require_department_scope(principal, payload.department_id)
    if await session.scalar(
        select(AcademicTerm.id).where(
            AcademicTerm.department_id == payload.department_id,
            AcademicTerm.code == payload.code.strip(),
        )
    ):
        raise APIError(status_code=409, code="term_code_exists", message="学期代码已存在")
    term = AcademicTerm(**payload.model_dump())
    session.add(term)
    await session.commit()
    return AcademicTermRead.model_validate(term)


@router.patch("/terms/{term_id}", response_model=AcademicTermRead)
async def edit_term(
    term_id: UUID,
    payload: AcademicTermUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> AcademicTermRead:
    term = await session.get(AcademicTerm, term_id)
    if term is None:
        raise APIError(status_code=404, code="term_not_found", message="学期不存在")
    require_department_scope(principal, term.department_id)
    check_version(term.version, payload.version)
    values = payload.model_dump(exclude_unset=True, exclude={"version"})
    start_date = values.get("start_date", term.start_date)
    end_date = values.get("end_date", term.end_date)
    if end_date < start_date:
        raise APIError(status_code=422, code="invalid_term_dates", message="学期结束日期不能早于开始日期")
    for name, value in values.items():
        setattr(term, name, value)
    term.version += 1
    await session.commit()
    return AcademicTermRead.model_validate(term)


@router.delete("/terms/{term_id}", status_code=204)
async def remove_term(term_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    term = await session.get(AcademicTerm, term_id)
    if term is None:
        raise APIError(status_code=404, code="term_not_found", message="学期不存在")
    require_department_scope(principal, term.department_id)
    await delete_or_conflict(session, term)
    return Response(status_code=204)


@router.get("/occupancies", response_model=Page[OccupancyRead])
async def occupancies(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "starts_at",
) -> Page[OccupancyRead]:
    del search, sort
    statement = select(CourseOccupancy)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(CourseOccupancy.department_id.in_(scope))
    rows, total = await fetch_page(
        session,
        statement.order_by(CourseOccupancy.starts_at, CourseOccupancy.id),
        page,
        page_size,
    )
    return Page[OccupancyRead](
        items=[OccupancyRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/occupancies", response_model=OccupancyRead, status_code=201)
async def add_occupancy(
    payload: OccupancyCreate,
    principal: ScopedAdmin,
    session: Session,
) -> OccupancyRead:
    require_department_scope(principal, payload.department_id)
    await ensure_person_in_department(
        session, payload.department_id, payload.person_type, payload.person_id
    )
    start = normalized_utc(payload.starts_at)
    end = normalized_utc(payload.ends_at)
    fingerprint = interval_fingerprint(payload.person_type, payload.person_id, start, end)
    occupancy = CourseOccupancy(
        department_id=payload.department_id,
        person_type=payload.person_type,
        person_id=payload.person_id,
        starts_at=start,
        ends_at=end,
        source_fingerprint=fingerprint,
        academic_term_id=payload.academic_term_id,
        teaching_week=payload.teaching_week,
        weekday=payload.weekday,
        start_section=payload.start_section,
        end_section=payload.end_section,
    )
    session.add(occupancy)
    await session.commit()
    return OccupancyRead.model_validate(occupancy)


@router.patch("/occupancies/{occupancy_id}", response_model=OccupancyRead)
async def edit_occupancy(
    occupancy_id: UUID,
    payload: OccupancyUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> OccupancyRead:
    occupancy = await session.get(CourseOccupancy, occupancy_id)
    if occupancy is None:
        raise APIError(status_code=404, code="occupancy_not_found", message="课程占用不存在")
    require_department_scope(principal, occupancy.department_id)
    check_version(occupancy.version, payload.version)
    start = normalized_utc(payload.starts_at) if payload.starts_at else as_utc(occupancy.starts_at)
    end = normalized_utc(payload.ends_at) if payload.ends_at else as_utc(occupancy.ends_at)
    if end <= start:
        raise APIError(status_code=422, code="invalid_interval", message="结束时间必须晚于开始时间")
    occupancy.starts_at = start
    occupancy.ends_at = end
    occupancy.source_fingerprint = interval_fingerprint(
        occupancy.person_type, occupancy.person_id, start, end
    )
    occupancy.version += 1
    await session.commit()
    return OccupancyRead.model_validate(occupancy)


@router.delete("/occupancies/{occupancy_id}", status_code=204)
async def remove_occupancy(occupancy_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    occupancy = await session.get(CourseOccupancy, occupancy_id)
    if occupancy is None:
        raise APIError(status_code=404, code="occupancy_not_found", message="课程占用不存在")
    require_department_scope(principal, occupancy.department_id)
    await delete_or_conflict(session, occupancy)
    return Response(status_code=204)


@router.get("/leaves", response_model=Page[LeaveRead])
async def leaves(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "starts_at",
) -> Page[LeaveRead]:
    del search, sort
    statement = select(LeaveRecord)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(LeaveRecord.department_id.in_(scope))
    rows, total = await fetch_page(
        session,
        statement.order_by(LeaveRecord.starts_at, LeaveRecord.id),
        page,
        page_size,
    )
    return Page[LeaveRead](
        items=[LeaveRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/leaves", response_model=LeaveRead, status_code=201)
async def add_leave(payload: LeaveCreate, principal: ScopedAdmin, session: Session) -> LeaveRead:
    require_department_scope(principal, payload.department_id)
    await ensure_person_in_department(
        session, payload.department_id, payload.person_type, payload.person_id
    )
    start = normalized_utc(payload.starts_at)
    end = normalized_utc(payload.ends_at)
    leave = LeaveRecord(
        department_id=payload.department_id,
        person_type=payload.person_type,
        person_id=payload.person_id,
        starts_at=start,
        ends_at=end,
        reason=payload.reason.strip(),
        source_fingerprint=interval_fingerprint(payload.person_type, payload.person_id, start, end),
    )
    session.add(leave)
    await session.commit()
    return LeaveRead.model_validate(leave)


@router.patch("/leaves/{leave_id}", response_model=LeaveRead)
async def edit_leave(
    leave_id: UUID,
    payload: LeaveUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> LeaveRead:
    leave = await session.get(LeaveRecord, leave_id)
    if leave is None:
        raise APIError(status_code=404, code="leave_not_found", message="请假记录不存在")
    require_department_scope(principal, leave.department_id)
    check_version(leave.version, payload.version)
    start = normalized_utc(payload.starts_at) if payload.starts_at else as_utc(leave.starts_at)
    end = normalized_utc(payload.ends_at) if payload.ends_at else as_utc(leave.ends_at)
    if end <= start:
        raise APIError(status_code=422, code="invalid_interval", message="结束时间必须晚于开始时间")
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version", "starts_at", "ends_at"}).items():
        setattr(leave, name, value)
    leave.starts_at = start
    leave.ends_at = end
    leave.source_fingerprint = interval_fingerprint(leave.person_type, leave.person_id, start, end)
    leave.version += 1
    await session.commit()
    return LeaveRead.model_validate(leave)


@router.delete("/leaves/{leave_id}", status_code=204)
async def remove_leave(leave_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    leave = await session.get(LeaveRecord, leave_id)
    if leave is None:
        raise APIError(status_code=404, code="leave_not_found", message="请假记录不存在")
    require_department_scope(principal, leave.department_id)
    await delete_or_conflict(session, leave)
    return Response(status_code=204)


@router.get("/rooms", response_model=Page[RoomRead])
async def rooms(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "name",
) -> Page[RoomRead]:
    statement = select(Room)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(Room.department_id.in_(scope))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Room.name.ilike(pattern), Room.building.ilike(pattern)))
    order = Room.capacity if sort == "capacity" else Room.name
    rows, total = await fetch_page(session, statement.order_by(order, Room.id), page, page_size)
    return Page[RoomRead](
        items=[RoomRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/rooms", response_model=RoomRead, status_code=201)
async def add_room(payload: RoomCreate, principal: ScopedAdmin, session: Session) -> RoomRead:
    require_department_scope(principal, payload.department_id)
    existing = await session.scalar(
        select(Room.id).where(
            Room.campus == payload.campus.strip(),
            Room.building == payload.building.strip(),
            Room.name == payload.name.strip(),
        )
    )
    if existing is not None:
        raise APIError(status_code=409, code="room_exists", message="教室已存在")
    room = Room(**payload.model_dump())
    session.add(room)
    await session.commit()
    return RoomRead.model_validate(room)


@router.patch("/rooms/{room_id}", response_model=RoomRead)
async def edit_room(
    room_id: UUID,
    payload: RoomUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> RoomRead:
    room = await session.get(Room, room_id)
    if room is None:
        raise APIError(status_code=404, code="room_not_found", message="教室不存在")
    require_department_scope(principal, room.department_id)
    check_version(room.version, payload.version)
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(room, name, value)
    room.version += 1
    await session.commit()
    return RoomRead.model_validate(room)


@router.delete("/rooms/{room_id}", status_code=204)
async def remove_room(room_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    room = await session.get(Room, room_id)
    if room is None:
        raise APIError(status_code=404, code="room_not_found", message="教室不存在")
    require_department_scope(principal, room.department_id)
    await delete_or_conflict(session, room)
    return Response(status_code=204)


@router.get("/activities", response_model=Page[ActivityRead])
async def activities(
    principal: ScopedAdmin,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 50,
    search: str = "",
    sort: str = "name",
) -> Page[ActivityRead]:
    del sort
    statement = select(DefenseActivity)
    scope = scoped_department_ids(principal)
    if scope is not None:
        statement = statement.where(DefenseActivity.department_id.in_(scope))
    if search:
        statement = statement.where(DefenseActivity.name.ilike(f"%{search.strip()}%"))
    rows, total = await fetch_page(
        session,
        statement.order_by(DefenseActivity.name, DefenseActivity.id),
        page,
        page_size,
    )
    return Page[ActivityRead](
        items=[ActivityRead.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/activities", response_model=ActivityRead, status_code=201)
async def add_activity(payload: ActivityCreate, principal: ScopedAdmin, session: Session) -> ActivityRead:
    return await create_activity(session, principal, payload)


@router.patch("/activities/{activity_id}", response_model=ActivityRead)
async def edit_activity(
    activity_id: UUID,
    payload: ActivityUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> ActivityRead:
    activity = await get_activity_scoped(session, principal, activity_id)
    check_version(activity.version, payload.version)
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(activity, name, value)
    activity.version += 1
    await session.commit()
    return ActivityRead.model_validate(activity)


@router.delete("/activities/{activity_id}", status_code=204)
async def remove_activity(activity_id: UUID, principal: ScopedAdmin, session: Session) -> Response:
    activity = await get_activity_scoped(session, principal, activity_id)
    await delete_or_conflict(session, activity)
    return Response(status_code=204)


@router.get("/activities/{activity_id}/slots", response_model=list[SlotRead])
async def slots(activity_id: UUID, principal: ScopedAdmin, session: Session) -> list[SlotRead]:
    await get_activity_scoped(session, principal, activity_id)
    rows = (
        await session.scalars(
            select(DefenseSlot)
            .where(DefenseSlot.activity_id == activity_id)
            .order_by(DefenseSlot.slot_date, DefenseSlot.start_time)
        )
    ).all()
    return [
        SlotRead(
            id=row.id,
            activity_id=row.activity_id,
            date=row.slot_date,
            start_time=row.start_time,
            end_time=row.end_time,
            max_groups=row.max_groups,
            version=row.version,
        )
        for row in rows
    ]


@router.post("/activities/{activity_id}/slots", response_model=SlotRead, status_code=201)
async def add_slot(
    activity_id: UUID,
    payload: SlotWrite,
    principal: ScopedAdmin,
    session: Session,
) -> SlotRead:
    return await create_slot(session, principal, activity_id, payload)


@router.put("/activities/{activity_id}/slots/{slot_id}", response_model=SlotRead)
async def edit_slot(
    activity_id: UUID,
    slot_id: UUID,
    payload: SlotUpdate,
    principal: ScopedAdmin,
    session: Session,
) -> SlotRead:
    await get_activity_scoped(session, principal, activity_id)
    slot = await session.get(DefenseSlot, slot_id)
    if slot is None or slot.activity_id != activity_id:
        raise APIError(status_code=404, code="slot_not_found", message="答辩时段不存在")
    check_version(slot.version, payload.version)
    overlap = await session.scalar(
        select(DefenseSlot.id).where(
            DefenseSlot.activity_id == activity_id,
            DefenseSlot.id != slot_id,
            DefenseSlot.slot_date == payload.date,
            DefenseSlot.start_time < payload.end_time,
            DefenseSlot.end_time > payload.start_time,
        )
    )
    if overlap is not None:
        raise APIError(status_code=409, code="slot_overlap", message="答辩时段发生重叠")
    slot.slot_date = payload.date
    slot.start_time = payload.start_time
    slot.end_time = payload.end_time
    slot.max_groups = payload.max_groups
    slot.version += 1
    await session.commit()
    return SlotRead(
        id=slot.id,
        activity_id=slot.activity_id,
        date=slot.slot_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        max_groups=slot.max_groups,
        version=slot.version,
    )


@router.delete("/activities/{activity_id}/slots/{slot_id}", status_code=204)
async def remove_slot(
    activity_id: UUID,
    slot_id: UUID,
    principal: ScopedAdmin,
    session: Session,
) -> Response:
    await get_activity_scoped(session, principal, activity_id)
    slot = await session.get(DefenseSlot, slot_id)
    if slot is None or slot.activity_id != activity_id:
        raise APIError(status_code=404, code="slot_not_found", message="答辩时段不存在")
    await delete_or_conflict(session, slot)
    return Response(status_code=204)


@router.get("/activities/{activity_id}/rules", response_model=ActivityRulesRead)
async def read_rules(activity_id: UUID, principal: ScopedAdmin, session: Session) -> ActivityRulesRead:
    activity = await get_activity_scoped(session, principal, activity_id)
    row = await session.scalar(
        select(ActivityRuleSet).where(
            ActivityRuleSet.activity_id == activity_id,
            ActivityRuleSet.rule_version == activity.current_rule_version,
        )
    )
    if row is None:
        raise APIError(status_code=404, code="activity_rules_missing", message="活动规则尚未配置")
    from defense_grouping.master_data.service import rules_read

    return rules_read(row)


@router.put("/activities/{activity_id}/rules", response_model=ActivityRulesRead)
async def replace_rules(
    activity_id: UUID,
    payload: ActivityRulesWrite,
    principal: ScopedAdmin,
    session: Session,
) -> ActivityRulesRead:
    return await write_rules(session, principal, activity_id, payload)


@router.put("/activities/{activity_id}/rooms", response_model=list[RoomRead])
async def replace_activity_rooms(
    activity_id: UUID,
    payload: ActivityRoomsWrite,
    principal: ScopedAdmin,
    session: Session,
) -> list[RoomRead]:
    return await set_activity_rooms(session, principal, activity_id, payload)
