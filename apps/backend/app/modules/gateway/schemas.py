"""网关向外发送的 ai-agent.v1 协议模型。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _WireModel(BaseModel):
    """统一把 Python snake_case 字段映射为协议 camelCase 字段。"""

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
    """服务端请求页面执行宿主工具时携带的参数。"""

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
    """客户端可消费的稳定错误结构，避免暴露内部异常堆栈。"""

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
    "agent_loop_started",
    "agent_step_started",
    "agent_step_delta",
    "agent_step_completed",
    "agent_loop_completed",
]


class ProtocolEnvelope(_WireModel):
    """所有出站事件的统一外壳。

    ``sequence`` 用于客户端去重和断线重放；``conversation_id``、
    ``request_id`` 和 payload 中的 ``callId`` 分别标识会话、请求和工具调用。
    """

    id: str = Field(min_length=1)
    type: ProtocolEventType
    protocol_version: Literal[1]
    conversation_id: str | None = None
    request_id: str | None = None
    sequence: int = Field(ge=1)
    timestamp: datetime
    payload: ProtocolPayload
