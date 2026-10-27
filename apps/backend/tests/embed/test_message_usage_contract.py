"""embed 消息快照的响应契约：`usage` 是可选字段，老消息缺省不能 500。

线上客户端（SDK）直接读 `usage` 渲染「本轮用量」，因此这里锁住字段名与
可空性，避免未来 refresh 时被序列化层悄悄改名。
"""

from datetime import datetime, timezone

from app.modules.embed.schemas import ConversationMessageRead


def _payload(**overrides):
    now = datetime(2026, 10, 27, 9, 30, tzinfo=timezone.utc)
    payload = {
        "id": 1,
        "conversation_id": 10,
        "role": "assistant",
        "content": "回答",
        "citations": [],
        "knowledge_grounded": False,
        "tool_call_id": None,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return payload


def test_message_read_accepts_usage_detail():
    model = ConversationMessageRead.model_validate(
        _payload(
            usage={
                "prompt_tokens": 120,
                "completion_tokens": 8,
                "total_tokens": 128,
                "cache_read_tokens": 100,
                "model": "deepseek-v4.1-flash",
                "provider": "deepseek",
            }
        )
    )

    assert model.usage is not None
    assert model.usage.cache_read_tokens == 100
    assert model.model_dump()["usage"]["provider"] == "deepseek"


def test_message_read_allows_missing_usage_for_legacy_messages():
    assert ConversationMessageRead.model_validate(_payload()).usage is None
