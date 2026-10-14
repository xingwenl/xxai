import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CUSTOM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_BLOCK_TYPES = {
    "text",
    "markdown",
    "image",
    "file",
    "table",
    "chart",
    "actions",
    "custom",
    "error",
}


def sanitize_content_blocks(
    blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """校验并限制消息内容块，异常块降级为可安全展示的错误块。"""
    if not blocks:
        return []
    safe: list[dict[str, Any]] = []
    for index, raw in enumerate(blocks[:32]):
        if not isinstance(raw, dict):
            safe.append(
                {
                    "id": f"invalid_{index}",
                    "type": "error",
                    "text": "内容块格式无效",
                    "status": "failed",
                }
            )
            continue
        block = dict(raw)
        block["id"] = str(block.get("id") or f"block_{index}")[:128]
        block_type = str(block.get("type") or "error")
        if block_type not in _BLOCK_TYPES:
            block = {
                "id": block["id"],
                "type": "error",
                "text": "暂不支持的内容类型",
                "status": "failed",
            }
        elif block_type in {"text", "markdown", "error"}:
            block["text"] = str(block.get("text") or block.get("fallback") or "")[
                :100_000
            ]
        elif block_type in {"image", "file"}:
            asset_id = block.get("asset_id", block.get("assetId"))
            if asset_id is not None and not _ASSET_ID.fullmatch(str(asset_id)):
                block = {
                    "id": block["id"],
                    "type": "error",
                    "text": "资源标识无效",
                    "status": "failed",
                }
            elif asset_id is not None:
                block["asset_id"] = str(asset_id)
            elif not str(block.get("url") or "").startswith(("https://", "http://")):
                block = {
                    "id": block["id"],
                    "type": "error",
                    "text": "资源地址无效",
                    "status": "failed",
                }
        elif block_type == "custom":
            name = str(block.get("component_name", block.get("componentName", "")))
            fallback = str(block.get("fallback") or "")[:2_000]
            if not _CUSTOM_NAME.fullmatch(name) or not fallback:
                block = {
                    "id": block["id"],
                    "type": "error",
                    "text": "自定义组件不可用",
                    "status": "failed",
                }
            else:
                block["component_name"] = name
                block["fallback"] = fallback
                block["props"] = (
                    block.get("props") if isinstance(block.get("props"), dict) else {}
                )
        if len(str(block)) <= 120_000:
            safe.append(block)
    return safe


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
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    loop: dict[str, Any] | None = None


class RuntimeContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent: Any
    version: Any
    knowledge_bases: list[Any] = Field(default_factory=list)
    skill_instructions: list[str] = Field(default_factory=list)
    skill_usages: list[dict[str, Any]] = Field(default_factory=list)
    skill_script_tools: list[Any] = Field(default_factory=list)
    skill_instruction_tool: Any | None = None
    mcp_tools: list[Any] = Field(default_factory=list)
    builtin_tools: list[Any] = Field(default_factory=list)
    host_tools: list[Any] = Field(default_factory=list)
    conversation_id: int | None = None


class ConversationPrincipalRead(BaseModel):
    """会话主体聚合项：一个主体在本平台的会话数与最近活跃时间。"""

    # 'user' = 后台用户（sys_users），'end_user' = 终端用户（platform_end_users）。
    principal_type: str
    principal_id: int
    display_name: str | None = None
    conversation_count: int
    last_conversation_at: datetime | None = None


class ConversationPrincipalPage(BaseModel):
    items: list[ConversationPrincipalRead]
    total: int
    page: int
    page_size: int


class ConsoleConversationRead(BaseModel):
    """后台会话记录列表项：会话头 + 列表渲染所需的轻量统计。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    agent_id: int
    agent_name: str | None = None
    principal_type: str
    principal_id: int
    principal_name: str | None = None
    title: str | None = None
    status: str
    message_count: int = 0
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime


class ConsoleConversationPage(BaseModel):
    items: list[ConsoleConversationRead]
    total: int
    page: int
    page_size: int


class ConsoleConversationUsage(BaseModel):
    """会话级用量汇总，取自 model_usage_records（计费事实来源）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    record_count: int = 0


class ConsoleConversationDetail(ConsoleConversationRead):
    usage: ConsoleConversationUsage = Field(default_factory=ConsoleConversationUsage)
