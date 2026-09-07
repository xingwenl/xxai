"""旧图运行时事件到 Agent runtime 事件的兼容转换。"""

from typing import Any

from app.modules.agent_runtime.contracts import AgentEvent, AgentEventType


_EVENT_TYPES = {item.value for item in AgentEventType}


def event_from_legacy(
    event: dict[str, Any],
    *,
    request_id: str | None = None,
    conversation_id: int | None = None,
) -> AgentEvent:
    """将旧的事件字典转换为统一事件。

    未知事件不会被静默丢弃，而是保留原始类型和完整 payload，便于协议适配器
    在迁移期间继续兼容历史事件，也避免新事件导致 Agent loop 崩溃。
    """

    event_type = str(event.get("type", "error"))
    payload = dict(event.get("payload") or {})
    for key, value in event.items():
        if key not in {"type", "payload"}:
            payload.setdefault(key, value)
    return AgentEvent(
        type=event_type if event_type in _EVENT_TYPES else event_type,
        payload=payload,
        request_id=request_id,
        conversation_id=conversation_id,
        message_id=event.get("message_id"),
    )


def event_to_legacy(event: AgentEvent) -> dict[str, Any]:
    """把统一事件还原为现有 gateway/conversation 使用的事件字典。"""

    legacy = {"type": str(event.type), **event.payload}
    # 旧实现的 error 事件读取 ``item["payload"]``，而流式增量事件读取顶层
    # 字段。两种形状在迁移期必须同时提供，不能为了统一内部模型破坏旧出口。
    legacy.setdefault("payload", dict(event.payload))
    if event.request_id is not None:
        legacy.setdefault("request_id", event.request_id)
    if event.conversation_id is not None:
        legacy.setdefault("conversation_id", event.conversation_id)
    if event.message_id is not None:
        legacy.setdefault("message_id", event.message_id)
    return legacy
