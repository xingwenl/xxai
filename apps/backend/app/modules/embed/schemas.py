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

    _normalize_origins = field_validator("allowed_origins")(normalize_origins)


class PlatformEmbedClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_origins: list[str] | None = Field(default=None, min_length=1, max_length=50)
    token_ttl_seconds: int | None = Field(default=None, ge=300, le=900)
    is_active: bool | None = None
    max_tokens_per_minute: int | None = Field(default=None, ge=1)
    max_connections: int | None = Field(default=None, ge=1)
    allow_temporary_tools: bool | None = None

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
