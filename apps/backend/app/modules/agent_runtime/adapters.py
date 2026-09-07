"""旧 Agent 实现与 agent_runtime 契约之间的兼容适配器。"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.agent_runtime.contracts import AgentResult, ToolCall, ToolOutcome


def agent_result_from_legacy(raw: object) -> AgentResult:
    """将旧 GraphResult 转换为 runtime 的统一最终结果。"""

    return AgentResult(
        content=str(getattr(raw, "content", "")),
        citations=list(getattr(raw, "citations", []) or []),
        content_blocks=list(getattr(raw, "content_blocks", []) or []),
        tool_events=list(getattr(raw, "tool_events", []) or []),
        usage=getattr(raw, "usage", None),
        pending_confirmation_id=getattr(raw, "pending_confirmation_id", None),
        knowledge_grounded=bool(getattr(raw, "knowledge_grounded", False)),
        thinking_text=str(getattr(raw, "thinking_text", "") or ""),
        loop_id=getattr(raw, "loop_id", None),
    )


def tool_outcome_from_legacy(raw: object) -> ToolOutcome:
    """将旧工具结果统一为 ToolOutcome，同时保留确认/审计关联字段。"""

    if isinstance(raw, ToolOutcome):
        return raw
    if isinstance(raw, dict):
        return ToolOutcome(
            status=str(raw.get("status", "completed")),
            result=raw.get("result", raw),
            error=raw.get("error"),
            resume_token=raw.get("resume_token"),
            call_id=raw.get("call_id"),
            audit_id=raw.get("audit_id"),
            confirmation_id=raw.get("confirmation_id"),
            metadata=raw.get("metadata", {}),
        )
    return ToolOutcome(
        status=str(getattr(raw, "status", "completed")),
        result=getattr(raw, "result", raw),
        error=getattr(raw, "error", None),
        resume_token=getattr(raw, "resume_token", None),
        call_id=getattr(raw, "call_id", None),
        audit_id=getattr(raw, "audit_id", None),
        confirmation_id=getattr(raw, "confirmation_id", None),
        metadata=getattr(raw, "metadata", {}) or {},
    )


def tool_call_from_legacy(call: dict[str, Any], *, name: str) -> ToolCall:
    """将当前 runtime 使用的 ``{"id", "args"}`` 调用转换为 ToolCall。"""

    arguments = call.get("args", {})
    return ToolCall(
        id=str(call.get("id") or name),
        name=name,
        arguments=arguments if isinstance(arguments, dict) else {},
        metadata=dict(call),
    )


async def invoke_legacy_tool(
    callback: Callable[..., Awaitable[object]],
    tool: object,
    call: ToolCall,
) -> ToolOutcome:
    """调用现有工具回调，并统一不同返回对象/字典的结果形状。"""

    raw = await callback(
        tool=tool,
        call={"id": call.id, "args": call.arguments},
    )
    return tool_outcome_from_legacy(raw)
