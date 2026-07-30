from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlatformCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")


class PlatformUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )
    is_active: bool | None = None


class PlatformRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    is_active: bool = True
    owner_id: int | None = None
    created_at: datetime
    updated_at: datetime
