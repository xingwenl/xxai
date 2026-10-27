"""消息快照的用量投影：明细来自消息元数据，坏数据不能让整份时间线 500。

embed 消息快照接口与后台会话查阅共用 `build_message_snapshots`，用量只认
元数据里的白名单字段；历史消息（本方案上线前没有该元数据）只是没有 chip，
不影响其他字段。
"""

import asyncio
from types import SimpleNamespace

from app.modules.conversation.serializers import build_message_snapshots


class FakeLoopRepository:
    """只需要 `list_loops` 与批量能力缺失的轻量替身。"""

    def __init__(self, loops=()):
        self._loops = list(loops)

    async def list_loops(self, conversation_id):
        return self._loops


def _message(identifier: int, metadata) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        conversation_id=1,
        role="assistant",
        content="回答",
        status="completed",
        content_blocks=[],
        citations=[],
        knowledge_grounded=False,
        tool_call_id=None,
        created_at=None,
        updated_at=None,
        message_metadata=metadata,
    )


def _snapshots(messages):
    async def run():
        return await build_message_snapshots(
            FakeLoopRepository(), conversation_id=1, messages=messages
        )

    return asyncio.run(run())


def test_snapshot_exposes_usage_detail_from_message_metadata():
    usage = {
        "prompt_tokens": 120,
        "completion_tokens": 8,
        "total_tokens": 128,
        "cache_read_tokens": 100,
        "model": "deepseek-v4.1-flash",
        "provider": "deepseek",
    }
    snapshots = _snapshots([_message(1, {"usage": usage})])

    assert snapshots[0]["usage"] == usage
    assert snapshots[0]["content"] == "回答"


def test_snapshot_usage_ignores_unknown_keys_and_bad_payloads():
    with_junk = _message(1, {"usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6, "junk": 1}})
    bad_type = _message(2, {"usage": "oops"})
    bad_value = _message(3, {"usage": {"prompt_tokens": "5"}})
    missing = _message(4, {})

    snapshots = _snapshots([with_junk, bad_type, bad_value, missing])

    assert snapshots[0]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 1,
        "total_tokens": 6,
    }
    assert snapshots[1]["usage"] is None
    assert snapshots[2]["usage"] is None
    assert snapshots[3]["usage"] is None
    # 坏用量字段不影响同一批消息的其余投影。
    assert [item["role"] for item in snapshots] == ["assistant"] * 4
