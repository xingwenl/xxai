from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=500)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    description: str | None = None
    is_default: bool = False
    is_active: bool = True
    default_version_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class AgentListData(BaseModel):
    page_no: int
    page_size: int
    items: list[AgentRead]
    total: int
    pages: int


class AgentVersionCreate(BaseModel):
    system_prompt: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=120)
    model_base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    model_options: dict[str, Any] = Field(default_factory=dict)


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    version: int
    system_prompt: str
    model_name: str
    model_base_url: str | None = None
    temperature: float
    model_options: dict[str, Any]
    created_at: datetime
    published_at: datetime | None = None
    has_api_key: bool = False


class AgentDetailRead(AgentRead):
    current_version: AgentVersionRead | None = None
