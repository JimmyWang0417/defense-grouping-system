from uuid import UUID

from pydantic import BaseModel, Field

from defense_grouping.models.identity import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=500)
    device_info: str | None = Field(default=None, max_length=500)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=500)
    device_info: str | None = Field(default=None, max_length=500)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=500)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=12, max_length=500)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool


class CurrentUserResponse(BaseModel):
    id: UUID
    username: str
    roles: list[Role]
    department_ids: list[UUID]
    must_change_password: bool


class RoleAssignmentWrite(BaseModel):
    role: Role
    department_id: UUID | None = None
    can_approve_exceptions: bool = False


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    temporary_password: str = Field(min_length=12, max_length=500)
    roles: list[RoleAssignmentWrite] = Field(min_length=1)


class UserStatusWrite(BaseModel):
    is_active: bool


class UserRolesWrite(BaseModel):
    roles: list[RoleAssignmentWrite] = Field(min_length=1)


class UserRead(BaseModel):
    id: UUID
    username: str
    is_active: bool
    must_change_password: bool
    roles: list[RoleAssignmentWrite]


class ResetPasswordRequest(BaseModel):
    temporary_password: str | None = Field(default=None, min_length=12, max_length=500)


class ResetPasswordResponse(BaseModel):
    temporary_password: str
