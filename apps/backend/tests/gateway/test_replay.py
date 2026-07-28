import asyncio

from app.modules.gateway.replay import ReplayStore


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
