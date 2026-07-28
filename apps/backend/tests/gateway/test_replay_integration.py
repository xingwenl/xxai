import os
import asyncio

import pytest
from redis.asyncio import Redis

from app.modules.gateway.replay import ReplayStore


def test_replay_store_with_real_redis():
    async def run():
        url = os.getenv("PHASE2_REDIS_URL")
        if not url:
            pytest.skip("PHASE2_REDIS_URL is not set")
        redis = Redis.from_url(url)
        await redis.flushdb()
        try:
            store = ReplayStore(redis)
            first = await store.append("integration", {"type": "message_delta"})
            second = await store.append("integration", {"type": "message_completed"})
            result = await store.replay("integration", first)

            assert result.recovered is True
            assert result.events == [{"type": "message_completed"}]
            assert result.latest_sequence == second
            assert await redis.ttl("agent:events:integration") <= 900
        finally:
            await redis.flushdb()
            await redis.aclose()

    asyncio.run(run())
