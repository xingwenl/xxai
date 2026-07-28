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
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(conversation_id: str | int) -> str:
        return f"agent:events:{conversation_id}"

    async def append(self, conversation_id: str | int, event: dict) -> str:
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
