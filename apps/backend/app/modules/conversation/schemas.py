from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CitationRead(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    text: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: int | None = Field(default=None, ge=1)
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    content: str
    citations: list[CitationRead]
    knowledge_grounded: bool
    pending_confirmation_id: int | None = None


class ChatEvent(BaseModel):
    type: str
    conversation_id: int
    message_id: int | None = None
    sequence: int
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent: Any
    version: Any
    knowledge_bases: list[Any] = Field(default_factory=list)
    skill_instructions: list[str] = Field(default_factory=list)
    mcp_tools: list[Any] = Field(default_factory=list)
    host_tools: list[Any] = Field(default_factory=list)
