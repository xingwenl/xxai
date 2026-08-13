"""WebSocket 入站消息的大小和基础结构校验。"""

import json

MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEXT_BYTES = 16 * 1024


def normalize_conversation_id(value: object) -> int | None:
    """把 WebSocket 字符串会话 ID 转为数据库主键类型。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_conversation_id")
    if isinstance(value, int):
        conversation_id = value
    elif isinstance(value, str) and value.isdecimal():
        conversation_id = int(value)
    else:
        raise ValueError("invalid_conversation_id")
    if conversation_id < 1:
        raise ValueError("invalid_conversation_id")
    return conversation_id


def validate_incoming_message(raw: str) -> dict:
    """把客户端文本消息解析为受限的协议字典。

    该函数不负责校验每一种业务消息的完整 Schema，而是先完成网关层
    必须的三件事：限制单条消息大小、保证 JSON 顶层是对象、为带 payload
    的宿主工具消息建立统一入口。更细的权限和状态校验在 WebSocket 主循环中
    根据消息类型执行，避免把认证前的任意数据直接送入业务层。
    """
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("message_too_large")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(message, dict):
        raise ValueError("invalid_message")
    if message.get("type") in {
        "host_tools_register",
        "host_tool_result",
        "host_tool_error",
        "confirmation_resolve",
    } and not isinstance(message.get("payload"), dict):
        raise ValueError("invalid_host_tool_payload")
    if message.get("type") == "message_send":
        text = message.get("payload", {}).get("text")
        if isinstance(text, str) and len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("text_too_large")
    return message
