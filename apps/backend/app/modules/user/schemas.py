from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.shared.base_schemas import TimeSchemas
from app.shared.pagination import PageData


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)


class UserRead(TimeSchemas):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    is_active: bool | None = None


class UserListData(PageData[UserRead]):
    pass
