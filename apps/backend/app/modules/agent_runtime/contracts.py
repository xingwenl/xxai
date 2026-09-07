"""Agent runtime 的类型化内部契约。

这些对象是 runtime 与协议 Adapter 之间的 seam。它们不携带 FastAPI、SQLAlchemy
或 WebSocket 类型，保证核心 Agent 逻辑可以在不同入口和纯单元测试中复用。
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class AgentEventType(StrEnum):
    """Agent 运行期间对外适配的内部事件类型。"""

    MESSAGE_DELTA = "message_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    QUESTION_REQUIRED = "question_required"
    COMPLETED = "completed"
    ERROR = "error"


class ToolOutcomeStatus(StrEnum):
    """工具调用的统一状态，屏蔽不同工具 Adapter 的返回差异。"""

    COMPLETED = "completed"
    FAILED = "failed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    WAITING_USER = "waiting_user"
    EXPIRED = "expired"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


def merge_usage(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """累加两次模型调用的 token 用量；缺失一侧时保留另一侧。

    legacy Graph 对所有模型轮次的 usage 逐轮相加，REST/SSE/WS 的最终 usage
    都是跨轮累计值；AgentLoop 必须保持同一口径，否则多轮工具或 wrap-up
    场景下灰度结果的 token 统计会小于真实消耗。字段名不做假设，存在即相加，
    兼容不同供应商的 usage 键名。
    """

    if previous is None:
        return dict(current) if current is not None else None
    if current is None:
        return dict(previous)
    keys = set(previous) | set(current)
    return {
        key: int(previous.get(key, 0)) + int(current.get(key, 0))
        for key in keys
    }


@dataclass(slots=True, frozen=True)
class ToolCall:
    """一次模型工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    tool_type: str | None = None
    server_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolOutcome:
    """工具 Adapter 返回给 Agent loop 的统一结果。"""

    status: ToolOutcomeStatus | str
    result: Any = None
    error: dict[str, Any] | None = None
    resume_token: str | None = None
    call_id: str | None = None
    # MCP/宿主工具的旧审计流程需要这些关联字段来恢复用户确认。
    audit_id: int | None = None
    confirmation_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        """提供 Pydantic 结果对象的兼容序列化接口。"""

        return {
            "status": str(self.status),
            "result": self.result,
            "error": self.error,
            "resume_token": self.resume_token,
            "call_id": self.call_id,
            "audit_id": self.audit_id,
            "confirmation_id": self.confirmation_id,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class AgentRequest:
    """一次 Agent 执行请求的最小输入。"""

    agent_id: int
    message: str
    conversation_id: int | None = None
    principal: Any = None
    channel: Literal["rest", "embed"] = "rest"
    request_id: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str | None = None


@dataclass(slots=True)
class AgentEvent:
    """Agent loop 产生的结构化事件，由协议层负责序列化。"""

    type: AgentEventType | str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    conversation_id: int | None = None
    message_id: int | None = None


@dataclass(slots=True)
class AgentResult:
    """一次 Agent 执行的最终结果。"""

    content: str
    conversation_id: int | None = None
    message_id: int | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None
    error: dict[str, Any] | None = None
    pending_confirmation_id: int | None = None
    knowledge_grounded: bool = False
    thinking_text: str = ""
    loop_id: int | None = None


@dataclass(slots=True)
class ToolRoundState:
    """一轮工具执行的内部状态，不携带协议或数据库对象。"""

    executed_tool: bool = False
    budget_exceeded: bool = False
    confirmation_result: Any = None
