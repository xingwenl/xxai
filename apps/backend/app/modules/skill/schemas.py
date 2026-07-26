from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=500)
    instruction_template: str = Field(min_length=1)
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    lifecycle_hooks: dict[str, Any] = Field(default_factory=dict)


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    description: str | None
    instruction_template: str
    parameter_schema: dict[str, Any]
    lifecycle_hooks: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentSkillBind(BaseModel):
    skill_id: int = Field(ge=1)
    sort_order: int = Field(default=0, ge=0)
