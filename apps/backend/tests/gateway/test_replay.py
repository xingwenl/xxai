import asyncio

from redis.exceptions import ResponseError

from app.modules.gateway.replay import ReplayStore
from app.modules.gateway.router import _numeric_sequence_floor


class FakeRedis:
    def __init__(self):
        self.streams = {}
        self.expirations = {}

    async def xadd(self, key, fields, maxlen, approximate):
        entries = self.streams.setdefault(key, [])
        identifier = f"{len(entries) + 1}-0"
        entries.append((identifier, fields))
        return identifier

    async def expire(self, key, seconds):
        self.expirations[key] = seconds

    async def xinfo_stream(self, key):
        entries = self.streams.get(key, [])
        if not entries:
            return {b"length": 0}
        return {
            b"length": len(entries),
            b"first-entry": (entries[0][0].encode(), entries[0][1]),
            b"last-entry": (entries[-1][0].encode(), entries[-1][1]),
        }

    async def xread(self, streams, count):
        key, cursor = next(iter(streams.items()))
        entries = self.streams.get(key, [])
        result = [entry for entry in entries if entry[0] > cursor]
        return [
            (
                key.encode(),
                [
                    (identifier.encode(), fields)
                    for identifier, fields in result[:count]
                ],
            )
        ]


def test_replay_store_limits_stream_and_recovers_after_cursor():
    async def run():
        redis = FakeRedis()
        store = ReplayStore(redis)
        first = await store.append("conv-1", {"type": "message_delta"})
        second = await store.append("conv-1", {"type": "message_completed"})

        result = await store.replay("conv-1", first)
        assert result.recovered is True
        assert [event["type"] for event in result.events] == ["message_completed"]
        assert redis.expirations["agent:events:conv-1"] == 900
        assert second == result.latest_sequence

    asyncio.run(run())


def test_replay_store_reports_expired_cursor():
    async def run():
        redis = FakeRedis()
        store = ReplayStore(redis)
        await store.append("conv-1", {"type": "message_delta"})
        redis.streams["agent:events:conv-1"] = [
            ("5-0", {"event": '{"type":"message_completed"}'})
        ]

        result = await store.replay("conv-1", "1-0")
        assert result.recovered is False
        assert result.events == []

    asyncio.run(run())


def test_replay_store_does_not_repeat_event_at_cursor():
    async def run():
        redis = FakeRedis()
        store = ReplayStore(redis)
        first = await store.append("conv-1", {"type": "message_delta"})
        await store.append("conv-1", {"type": "message_completed"})

        result = await store.replay("conv-1", first)

        assert [event["type"] for event in result.events] == ["message_completed"]

    asyncio.run(run())


def test_replay_store_supports_protocol_sequence_cursor():
    async def run():
        redis = FakeRedis()
        store = ReplayStore(redis)
        await store.append("conv-1", {"type": "message_delta", "sequence": 4})
        await store.append("conv-1", {"type": "message_completed", "sequence": 5})

        result = await store.replay("conv-1", "4")

        assert result.events == [{"type": "message_completed", "sequence": 5}]
        assert result.latest_sequence == "5"

    asyncio.run(run())


def test_replay_store_accepts_numeric_sdk_cursor():
    async def run():
        redis = FakeRedis()
        store = ReplayStore(redis)
        await store.append("conv-1", {"type": "message_delta", "sequence": 4})
        await store.append("conv-1", {"type": "message_completed", "sequence": 5})

        result = await store.replay("conv-1", 4)

        assert result.latest_sequence == "5"
        assert len(result.events) == 1

    asyncio.run(run())


class MissingStreamRedis(FakeRedis):
    """模拟会话尚无事件流时 Redis 的 "no such key" 行为。"""

    async def xinfo_stream(self, key):
        raise ResponseError("no such key")


def test_replay_store_skips_missing_stream():
    """Stream 不存在时按「无可重放事件」处理，不能抛异常打断建连。"""

    async def run():
        store = ReplayStore(MissingStreamRedis())

        result = await store.replay("conv-missing", "3")

        assert result.recovered is True
        assert result.events == []
        assert result.latest_sequence is None

    asyncio.run(run())


def test_numeric_sequence_floor_accepts_redis_stream_id():
    """旧客户端把 Redis Stream ID 当游标时，序号计算不得抛 ValueError。"""

    assert _numeric_sequence_floor("1789749522980-0") == 0
    assert _numeric_sequence_floor("12") == 12
    assert _numeric_sequence_floor(7) == 7
    assert _numeric_sequence_floor(None) == 0
    assert _numeric_sequence_floor(True) == 0
