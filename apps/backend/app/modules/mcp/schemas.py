from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SideEffect = Literal["none", "navigation", "write", "financial", "external"]


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    endpoint_url: str = Field(min_length=1, max_length=2000)
    auth_headers: dict[str, str] = Field(default_factory=dict)


class McpServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    endpoint_url: str
    is_active: bool
    has_auth_headers: bool = False
    created_at: datetime
    updated_at: datetime


class McpServerListData(BaseModel):
    page_no: int
    page_size: int
    items: list[McpServerRead]
    total: int
    pages: int


class McpServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=2000)
    auth_headers: dict[str, str] | None = None
    is_active: bool | None = None


class McpToolPolicyUpdate(BaseModel):
    is_allowed: bool
    side_effect: SideEffect


class McpToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    server_id: int
    name: str
    description: str | None
    input_schema: dict[str, Any]
    is_allowed: bool
    side_effect: SideEffect


class AgentMcpServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    server_id: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentMcpBind(BaseModel):
    server_id: int = Field(ge=1)


class ToolInvokeRequest(BaseModel):
    server_id: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConfirmationResolveRequest(BaseModel):
    approved: bool


class McpAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    agent_id: int
    user_id: int | None
    platform_end_user_id: int | None
    server_id: int
    tool_id: int
    tool_name: str
    arguments: dict[str, Any]
    status: str
    result: Any = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class DiscoveredMcpTool(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ToolInvocationOutcome(BaseModel):
    status: Literal[
        "completed", "confirmation_required", "rejected", "expired", "failed"
    ]
    audit_id: int
    confirmation_id: int | None = None
    expires_at: datetime | None = None
    result: Any = None
