from typing import Any, Literal
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

SideEffect = Literal["none", "navigation", "write", "financial", "external"]
ConfirmationPolicy = Literal["auto", "always"]
HostToolStatus = Literal[
    "requested",
    "awaiting_confirmation",
    "running",
    "succeeded",
    "failed",
    "rejected",
    "expired",
]


def validate_schema(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("type") != "object":
        raise ValueError("host tool schema must be an object schema")
    if len(json.dumps(value, separators=(",", ":"))) > 64 * 1024:
        raise ValueError("host tool schema is too large")
    return value


class HostToolPolicyCreate(BaseModel):
    name: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$"
    )
    description: str = Field(min_length=1, max_length=1000)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] | None = None
    side_effect: SideEffect = "external"
    confirmation_policy: ConfirmationPolicy = "always"

    _validate_input_schema = field_validator("input_schema")(validate_schema)
    _validate_output_schema = field_validator("output_schema")(
        lambda v: validate_schema(v) if v else v
    )


class HostToolPolicyUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    side_effect: SideEffect | None = None
    confirmation_policy: ConfirmationPolicy | None = None
    is_enabled: bool | None = None

    _validate_input_schema = field_validator("input_schema")(
        lambda v: validate_schema(v) if v else v
    )
    _validate_output_schema = field_validator("output_schema")(
        lambda v: validate_schema(v) if v else v
    )


class HostToolPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    side_effect: SideEffect
    confirmation_policy: ConfirmationPolicy
    is_enabled: bool


class HostToolRegistration(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class HostToolCall(BaseModel):
    call_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class HostToolConfirmationResolve(BaseModel):
    call_id: str = Field(min_length=8, max_length=128)
    approved: bool


class HostToolResult(BaseModel):
    call_id: str = Field(min_length=8, max_length=128)
    result: Any = None


class HostToolError(BaseModel):
    call_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class HostToolAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    call_id: str
    platform_id: int
    agent_id: int
    platform_end_user_id: int
    conversation_id: int | None
    request_id: str | None
    tool_name: str
    status: HostToolStatus
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
