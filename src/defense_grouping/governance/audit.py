from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from defense_grouping.models.governance import AuditLog

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "refresh_token",
    "jwt_secret",
}


class AuditMutationError(RuntimeError):
    """Raised when code attempts to alter an append-only audit record."""


def redact_summary(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if str(key).casefold() in SENSITIVE_KEYS else redact_summary(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact_summary(item) for item in value]
    return value


def _summary(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    redacted = redact_summary(value)
    if not isinstance(redacted, dict):
        raise TypeError("audit summary must be a mapping")
    return redacted


async def write_audit(
    session: AsyncSession,
    *,
    actor_id: UUID | None,
    action: str,
    object_type: str,
    object_id: UUID | None,
    request_id: str,
    before_summary: Mapping[str, object] | None,
    after_summary: Mapping[str, object] | None,
) -> AuditLog:
    record = AuditLog(
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        request_id=request_id,
        before_summary=_summary(before_summary),
        after_summary=_summary(after_summary),
    )
    session.add(record)
    await session.flush()
    return record


@event.listens_for(Session, "before_flush")
def protect_append_only_audits(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    for record in session.deleted:
        if isinstance(record, AuditLog):
            raise AuditMutationError("audit logs are append-only and cannot be deleted")
    for record in session.dirty:
        if isinstance(record, AuditLog) and session.is_modified(record, include_collections=False):
            raise AuditMutationError("audit logs are append-only and cannot be updated")
