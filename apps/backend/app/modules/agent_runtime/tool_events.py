"""与协议无关的工具事件构造函数。"""

import json
from typing import Any


def summarize_tool_value(value: Any, *, limit: int = 500) -> str:
    """生成有界工具摘要，避免超长结果或不可序列化对象进入事件。"""

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]


def build_tool_event(tool: object, call: dict[str, Any], *, waiting_status: str | None = None) -> dict[str, Any]:
    """构造工具调用的稳定事件字段，供 REST/WS 共用。"""

    event = {
        "tool": tool.name,
        "tool_type": classify_tool_type(tool),
        "tool_call_id": call.get("id", tool.name),
        "input_summary": summarize_tool_value(call.get("args", {}), limit=300),
        "skill_name": getattr(tool, "skill_name", None),
        "skill_version": getattr(tool, "skill_version", None),
    }
    if waiting_status is not None:
        event["waiting_status"] = waiting_status
    return event


def build_tool_completed_event(
    tool_event: dict[str, Any], outcome: object
) -> dict[str, Any]:
    """在统一基础字段上附加工具结果，避免各入口重复拼接状态。"""

    return {
        **tool_event,
        "outcome": outcome,
        "status": getattr(outcome, "status", "completed"),
        "result": getattr(outcome, "result", None),
        "error": getattr(outcome, "error", None),
    }


def classify_tool_type(tool: object) -> str:
    """按来源归类工具，避免协议层重复理解工具对象结构。"""

    if hasattr(tool, "server_id"):
        return "mcp_tool"
    kind = getattr(tool, "kind", None)
    if kind in {"skill_script", "skill_instruction"}:
        return "skill_tool"
    if kind == "builtin":
        return "builtin_tool"
    return "host_tool"


def tool_result_content(tool: object, outcome: object) -> str:
    """生成回填给模型的工具结果文本，并按工具来源设置上限。

    builtin 工具允许较大的有界响应，便于读取类工具保留有效内容；其他工具
    使用较小上限，防止外部服务返回超大文本挤占后续模型上下文。失败工具
    只有 error 没有 result 时，把错误摘要作为结果文本回填，避免模型只看到
    字面量 ``None`` 而无法判断失败原因。
    """

    limit = 100_000 if getattr(tool, "kind", None) == "builtin" else 20_000
    value = getattr(outcome, "result", None)
    if value is None and getattr(outcome, "error", None) is not None:
        value = {
            "status": str(getattr(outcome, "status", "failed")),
            "error": getattr(outcome, "error"),
        }
    if getattr(tool, "kind", None) == "builtin":
        return summarize_tool_value(value, limit=limit)
    return str(value)[:limit]


def normalize_tool_step_status(outcome_status: object) -> str:
    """将工具执行状态安全转换为持久化 loop step 状态。

    未知状态默认失败，避免新增工具来源忘记注册映射时被误报为成功。
    """

    return {
        "completed": "succeeded",
        "succeeded": "succeeded",
        "confirmation_required": "waiting_confirmation",
        "waiting_user": "waiting_question",
        "waiting_question": "waiting_question",
        "failed": "failed",
        "error": "failed",
        "expired": "failed",
        "rejected": "failed",
        "cancelled": "cancelled",
        "budget_exceeded": "budget_exceeded",
        "quota_exceeded": "budget_exceeded",
    }.get(str(outcome_status), "failed")
