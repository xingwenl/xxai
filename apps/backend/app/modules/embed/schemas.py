from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_origins(origins: list[str]) -> list[str]:
    normalized = []
    for origin in origins:
        value = origin.strip().rstrip("/")
        if (
            not value.startswith(("http://", "https://"))
            or "/" in value.split("://", 1)[1]
        ):
            raise ValueError("origins must be exact http(s) origins")
        normalized.append(value)
    return sorted(set(normalized))


class PlatformEmbedClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_origins: list[str] = Field(min_length=1, max_length=50)
    token_ttl_seconds: int = Field(default=600, ge=300, le=900)
    max_tokens_per_minute: int | None = Field(default=None, ge=1)
    max_connections: int | None = Field(default=None, ge=1)
    allow_temporary_tools: bool = False
    allow_agent_switching: bool = False

    _normalize_origins = field_validator("allowed_origins")(normalize_origins)


class PlatformEmbedClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_origins: list[str] | None = Field(default=None, min_length=1, max_length=50)
    token_ttl_seconds: int | None = Field(default=None, ge=300, le=900)
    is_active: bool | None = None
    max_tokens_per_minute: int | None = Field(default=None, ge=1)
    max_connections: int | None = Field(default=None, ge=1)
    allow_temporary_tools: bool | None = None
    allow_agent_switching: bool | None = None

    _normalize_origins = field_validator("allowed_origins")(normalize_origins)


class PlatformEmbedClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    client_id: str
    name: str
    allowed_origins: list[str]
    token_ttl_seconds: int
    is_active: bool
    max_tokens_per_minute: int | None = None
    max_connections: int | None = None
    allow_temporary_tools: bool
    allow_agent_switching: bool


class PlatformEmbedClientCreated(BaseModel):
    client: PlatformEmbedClientRead
    client_secret: str


class PlatformEmbedClientAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    agent_id: int


class EmbedTokenRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    client_secret: str = Field(min_length=1)
    agent_id: int = Field(ge=1)
    external_user_id: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=120)
    origin: str = Field(min_length=1, max_length=500)
    host_tool_names: list[str] = Field(default_factory=list, max_length=100)


class EmbedTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    jti: str


class MessageUsage(BaseModel):
    """单条 assistant 消息的模型用量明细（展示口径，非计费事实）。

    缓存字段缺失表示 provider 没有报告该计数（前端据此隐藏「缓存命中」行），
    与「报告了 0」区分开；``model``/``provider`` 是生成该消息时实际调用的模型
    快照，便于历史消息在模型配置变化后仍显示原样。
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    model: str | None = None
    provider: str | None = None


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    status: str = "completed"
    content_blocks: list[dict] = Field(default_factory=list)
    citations: list[dict]
    knowledge_grounded: bool
    tool_call_id: str | None
    created_at: datetime
    updated_at: datetime
    loop: dict | None = None
    usage: MessageUsage | None = None


class EmbedConversationRead(BaseModel):
    """会话列表的轻量投影。

    只携带列表渲染所需字段；消息正文由既有的消息快照接口按需拉取，
    避免列表接口随会话数 × 消息数膨胀。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    created_at: datetime
    message_count: int = 0
    last_message_preview: str | None = None


class EmbedConversationPage(BaseModel):
    """会话列表分页结果，字段口径与后台既有分页响应保持一致。"""

    items: list[EmbedConversationRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ConversationContextCompactRequest(BaseModel):
    """手动压缩上下文的可选参数。

    ``instructions`` 是本次摘要的额外关注点（例如「重点保留接口约定」），会作为
    一段附加要求拼进摘要提示词；不传则只按默认小节摘要。
    """

    instructions: str | None = Field(default=None, max_length=2000)


class ConversationContextCompactResult(BaseModel):
    """手动压缩的结果投影（snake_case，与 embed 其余 REST 数据一致）。

    ``compacted=False`` 不是错误：没有新的可压缩内容时幂等返回
    ``reason="nothing_to_compact"``。``window_tokens`` 为 null 表示该模型窗口
    未知，此时 ``percent`` 也为 null，调用方只能显示绝对 token 数。
    """

    compacted: bool
    reason: str
    trigger: str
    tokens_before: int
    tokens_after: int
    window_tokens: int | None = None
    used_tokens: int = 0
    percent: float | None = None
