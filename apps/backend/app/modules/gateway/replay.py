"""基于 Redis Stream 的 WebSocket 事件重放。"""

import json
from dataclasses import dataclass

from redis.asyncio import Redis

STREAM_TTL_SECONDS = 900
STREAM_MAX_LENGTH = 1000


@dataclass(frozen=True)
class ReplayResult:
    recovered: bool
    events: list[dict]
    latest_sequence: str | None


class ReplayStore:
    """把已发送事件按会话保存一段有限时间，支持断线续传。

    事件重放不是聊天内容的永久存储：Stream 有长度上限和 TTL，
    Conversation 数据库仍是消息事实来源。这里保存的是带 sequence 的
    协议事件，客户端可用上次收到的 cursor 请求缺失事件。
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(conversation_id: str | int) -> str:
        """为会话生成稳定且不会跨会话混用的 Redis key。"""
        return f"agent:events:{conversation_id}"

    async def append(self, conversation_id: str | int, event: dict) -> str:
        """追加事件并刷新 TTL。

        ``maxlen`` 控制单个会话的事件数量，``approximate=False`` 保证
        Redis 按精确长度裁剪，便于测试和故障排查时得到确定行为。
        """
        key = self.key(conversation_id)
        identifier = await self.redis.xadd(
            key,
            {"event": json.dumps(event, ensure_ascii=False)},
            maxlen=STREAM_MAX_LENGTH,
            approximate=False,
        )
        await self.redis.expire(key, STREAM_TTL_SECONDS)
        return identifier.decode() if isinstance(identifier, bytes) else identifier

    async def replay(
        self, conversation_id: str | int, cursor: str | None
    ) -> ReplayResult:
        """根据客户端 cursor 读取尚未确认的事件。

        如果 cursor 早于 Stream 当前保留的第一条事件，说明中间事件已经
        因 TTL/长度限制丢失，返回 ``recovered=False``，上层可以让客户端
        重新建立完整状态，而不是伪造不完整的恢复结果。
        """
        key = self.key(conversation_id)
        info = await self.redis.xinfo_stream(key)
        first = info.get(b"first-entry") or info.get("first-entry")
        last = info.get(b"last-entry") or info.get("last-entry")
        if not first or not last:
            return ReplayResult(True, [], None)
        first_id = first[0].decode() if isinstance(first[0], bytes) else first[0]
        last_id = last[0].decode() if isinstance(last[0], bytes) else last[0]
        if cursor is not None and cursor < first_id:
            return ReplayResult(False, [], last_id)
        rows = await self.redis.xread({key: cursor or "0-0"}, count=STREAM_MAX_LENGTH)
        events = []
        for _stream, entries in rows:
            for _identifier, fields in entries:
                raw = fields.get(b"event") or fields.get("event")
                events.append(
                    json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                )
        return ReplayResult(True, events, last_id)
