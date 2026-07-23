from __future__ import annotations

from typing import Any, Literal

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.role.schemas import RoleSummary
from app.shared.base_schemas import TimeSchemas
from app.shared.pagination import PageData


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    account: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)
    role_ids: list[int] = Field(default_factory=list)


class UserRead(TimeSchemas):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    account: str
    roles: list[RoleSummary] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    is_active: bool | None = None
    account: str | None = Field(default=None, min_length=3, max_length=255)
    role_ids: list[int] | None = None


UserListField = Literal["id", "name", "email", "account", "is_active", "created_at", "updated_at", "roles"]
UserSortField = Literal["created_at", "-created_at"]

DEFAULT_USER_LIST_FIELDS: tuple[UserListField, ...] = (
    "id",
    "name",
    "email",
    "account",
    "is_active",
    "created_at",
    "updated_at",
    "roles",
)


class UserListQuery(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    role_id: int | None = Field(default=None, ge=1)
    role_code: str | None = Field(default=None, min_length=1, max_length=100)
    sort: UserSortField = "-created_at"
    fields: list[UserListField] | None = None


class UserListData(PageData[dict[str, Any]]):
    pass
