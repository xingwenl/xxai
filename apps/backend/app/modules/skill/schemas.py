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
    package_id: int | None = None
    name: str
    slug: str
    description: str | None
    instruction_template: str
    parameter_schema: dict[str, Any]
    lifecycle_hooks: dict[str, Any]
    package_skill_path: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillListData(BaseModel):
    page_no: int
    page_size: int
    items: list[SkillRead]
    total: int
    pages: int


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instruction_template: str | None = Field(default=None, min_length=1)
    parameter_schema: dict[str, Any] | None = None
    lifecycle_hooks: dict[str, Any] | None = None
    is_active: bool | None = None


class AgentSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    skill_id: int
    sort_order: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentSkillBind(BaseModel):
    skill_id: int = Field(ge=1)
    sort_order: int = Field(default=0, ge=0)


class SkillPackageFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    package_id: int
    relative_path: str
    role: str
    size_bytes: int
    media_type: str | None
    created_at: datetime
    updated_at: datetime


class SkillPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    package_type: str
    source_filename: str
    storage_key: str
    storage_path: str
    manifest: dict[str, Any]
    warnings: list[str]
    allow_script_execution: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillPackageDetail(SkillPackageRead):
    files: list[SkillPackageFileRead]
    skills: list[SkillRead]


class SkillPackageListData(BaseModel):
    page_no: int
    page_size: int
    items: list[SkillPackageRead]
    total: int
    pages: int


class SkillPackageUpdate(BaseModel):
    allow_script_execution: bool | None = None
    is_active: bool | None = None


class SkillPackageImportResult(BaseModel):
    package: SkillPackageDetail
    warnings: list[str]


class SkillScriptExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    package_id: int
    skill_id: int
    agent_id: int
    user_id: int | None
    platform_end_user_id: int | None
    conversation_id: int | None
    request_id: str | None
    script_path: str
    arguments: list[str]
    status: str
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    error: str | None
    duration_ms: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SkillScriptExecutionListData(BaseModel):
    page_no: int
    page_size: int
    items: list[SkillScriptExecutionRead]
    total: int
    pages: int
