from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends

from defense_grouping.api.errors import APIError
from defense_grouping.models.identity import Role


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    roles: frozenset[Role]
    department_ids: frozenset[UUID]


def ensure_department_access(principal: Principal, department_id: UUID) -> None:
    if Role.SYSTEM_ADMIN not in principal.roles and department_id not in principal.department_ids:
        raise PermissionError("department_scope_denied")


def require_roles(
    *roles: Role,
) -> Callable[..., Coroutine[Any, Any, Principal]]:
    from defense_grouping.api.dependencies import get_current_principal

    async def check_roles(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.roles.intersection(roles):
            raise APIError(status_code=403, code="forbidden", message="无权执行此操作")
        return principal

    return check_roles
