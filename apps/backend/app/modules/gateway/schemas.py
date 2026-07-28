from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda field_name: "".join(
            part.capitalize() if index else part
            for index, part in enumerate(field_name.split("_"))
        ),
        extra="ignore",
        populate_by_name=True,
    )


class EmptyPayload(_WireModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MessageDeltaPayload(_WireModel):
    content: str


class CitationPayload(_WireModel):
    title: str
    text: str
    source_url: str | None = None


class ToolStatePayload(_WireModel):
    name: str
    status: str


class HostToolCallPayload(_WireModel):
    call_id: str
    name: str
    arguments: dict
    side_effect: str
    requires_confirmation: bool


class ConfirmationRequiredPayload(_WireModel):
    call_id: str
    name: str
    summary: dict | None = None


class ErrorPayload(_WireModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, str] | None = None


ProtocolPayload = Annotated[
    EmptyPayload
    | MessageDeltaPayload
    | CitationPayload
    | ToolStatePayload
    | HostToolCallPayload
    | ConfirmationRequiredPayload
    | ErrorPayload,
    Field(discriminator=None),
]


ProtocolEventType = Literal[
    "session_ready",
    "message_started",
    "message_delta",
    "citation",
    "message_completed",
    "tool_call",
    "tool_result",
    "host_tool_call",
    "confirmation_required",
    "error",
    "pong",
]


class ProtocolEnvelope(_WireModel):
    id: str = Field(min_length=1)
    type: ProtocolEventType
    protocol_version: Literal[1]
    conversation_id: str | None = None
    request_id: str | None = None
    sequence: int = Field(ge=1)
    timestamp: datetime
    payload: ProtocolPayload
