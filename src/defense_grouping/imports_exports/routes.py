import asyncio
import hashlib
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from defense_grouping.api.dependencies import get_db_session
from defense_grouping.api.errors import APIError
from defense_grouping.auth.permissions import Principal, require_roles
from defense_grouping.db.session import Database
from defense_grouping.imports_exports.import_service import (
    DefaultImportWriter,
    ImportWriter,
    confirm_import,
    preview_from_batch,
    run_preflight,
)
from defense_grouping.imports_exports.schemas import (
    ImportKind,
    ImportPreview,
    ImportResult,
)
from defense_grouping.imports_exports.templates import TEMPLATES, generate_template
from defense_grouping.master_data.service import require_department_scope
from defense_grouping.models.governance import ImportBatch, ImportStatus
from defense_grouping.models.identity import Role

router = APIRouter(prefix="/api/v1/imports")

ScopedAdmin = Annotated[
    Principal,
    Depends(require_roles(Role.SYSTEM_ADMIN, Role.ACADEMIC_ADMIN)),
]
Session = Annotated[AsyncSession, Depends(get_db_session)]


def get_import_writer() -> ImportWriter:
    return DefaultImportWriter()


def resolve_department(principal: Principal, requested: UUID | None) -> UUID:
    if requested is not None:
        require_department_scope(principal, requested)
        return requested
    if len(principal.department_ids) == 1:
        return next(iter(principal.department_ids))
    raise APIError(
        status_code=422,
        code="department_required",
        message="必须明确指定导入院系",
        fields={"department_id": "系统管理员或多院系账号必须指定院系"},
    )


@router.get("/templates/{kind}")
async def download_template(kind: ImportKind, _principal: ScopedAdmin) -> Response:
    definition = TEMPLATES[kind]
    filename = quote(definition.filename)
    return Response(
        content=generate_template(kind),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post(
    "/{kind}/preflight",
    response_model=ImportPreview,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_preflight(
    kind: ImportKind,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
    file: Annotated[UploadFile, File()],
    department_id: Annotated[UUID | None, Query()] = None,
) -> ImportPreview:
    original_name = file.filename or "upload.xlsx"
    if Path(original_name).suffix.casefold() != ".xlsx":
        raise APIError(
            status_code=422,
            code="invalid_workbook_type",
            message="只允许上传不含宏的 .xlsx 文件",
        )
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise APIError(status_code=413, code="workbook_too_large", message="文件不能超过 20 MiB")
    if not content:
        raise APIError(status_code=422, code="empty_workbook", message="上传文件为空")

    active_department = resolve_department(principal, department_id)
    batch_id = uuid4()
    storage_root = Path(request.app.state.settings.storage_dir)
    target_directory = storage_root / "uploads" / "imports"
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / f"{batch_id}.xlsx"
    target.write_bytes(content)
    batch = ImportBatch(
        id=batch_id,
        department_id=active_department,
        template_kind=kind.value,
        status=ImportStatus.PENDING,
        file_sha256=hashlib.sha256(content).hexdigest(),
        original_name=original_name,
        stored_path=str(target),
        file_size=len(content),
        uploader_id=principal.user_id,
        preview={"progress": 0, "issues": [], "commands": []},
    )
    session.add(batch)
    await session.commit()

    database = cast(Database, request.app.state.database)
    task = asyncio.create_task(run_preflight(database, batch.id))
    tasks = getattr(request.app.state, "import_tasks", None)
    if tasks is None:
        tasks = set()
        request.app.state.import_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return preview_from_batch(batch)


@router.get("/{batch_id}", response_model=ImportPreview)
async def get_preview(batch_id: UUID, principal: ScopedAdmin, session: Session) -> ImportPreview:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None:
        raise APIError(status_code=404, code="import_batch_not_found", message="导入批次不存在")
    require_department_scope(principal, batch.department_id)
    return preview_from_batch(batch)


@router.post("/{batch_id}/confirm", response_model=ImportResult)
async def confirm_preview(
    batch_id: UUID,
    request: Request,
    principal: ScopedAdmin,
    session: Session,
    writer: Annotated[ImportWriter, Depends(get_import_writer)],
) -> ImportResult:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None:
        raise APIError(status_code=404, code="import_batch_not_found", message="导入批次不存在")
    require_department_scope(principal, batch.department_id)
    batch.confirmed_by_id = principal.user_id
    return await confirm_import(
        session,
        batch,
        writer,
        actor_id=principal.user_id,
        request_id=request.state.request_id,
    )
