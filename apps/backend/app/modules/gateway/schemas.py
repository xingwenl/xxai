"""网关向外发送的 ai-agent.v1 协议模型。"""

from datetime import datetime
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    """服务端请求页面执行��主工具时携带的参数。"""

    call_id: str
    name: str
    arguments: dict
    side_effect: str
    requires_confirmation: bool


class ConfirmationRequiredPayload(_WireModel):
    call_id: str
    name: str
    summary: dict | None = None


class QuestionOption(_WireModel):
    id: str
    label: str


class QuestionRequiredPayload(_WireModel):
    question_id: str
    question: str
    description: str | None = None
    options: list[QuestionOption]
    allow_free_text: bool = True
    require_selection: bool = True
    expires_at: str | None = None


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
    | QuestionRequiredPayload
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
    "question_required",
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


# ---------------------------------------------------------------------------
# 附件引用 schema（message_send 入站消息中的 attachments 字段）
# ---------------------------------------------------------------------------

_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_MAX_ATTACHMENTS = 10


class AttachmentRef(BaseModel):
    """消息发送时携带的附件引用，客户端只传元数据，后端重新校验。"""

    assetId: str = Field(
        min_length=1,
        max_length=128,
        description="附件唯一标识，由上传接口返回",
    )
    filename: str = Field(
        min_length=1,
        max_length=255,
        description="安全化处理后的文件名",
    )
    mimeType: str = Field(
        min_length=1,
        max_length=255,
        description="资源媒体类型",
    )
    size: int = Field(
        ge=1,
        description="资源字节大小",
    )

    @field_validator("assetId")
    @classmethod
    def validate_asset_id_format(cls, value: str) -> str:
        if not _ASSET_ID_RE.fullmatch(value):
            raise ValueError("assetId 格式无效")
        return value


class MessageSendPayload(BaseModel):
    """message_send 入站消息的 payload 结构。"""

    text: str = Field(
        min_length=1,
        max_length=20_000,
        description="用户消息文本",
    )
    conversationId: int | None = Field(
        default=None,
        ge=1,
        description="会话 ID",
    )
    attachments: list[AttachmentRef] | None = Field(
        default=None,
        max_length=_MAX_ATTACHMENTS,
        description="附件引用列表，最多 10 个",
    )
    systemPrompt: str | None = Field(
        default=None,
        max_length=20_000,
        description="可选的系统提示词",
    )
    thinking: bool | None = Field(
        default=None,
        description=(
            "请求级思考开关：true 进入思考模式，false 关闭，"
            "不传表示不干预（沿用模型与厂商默认）"
        ),
    )
