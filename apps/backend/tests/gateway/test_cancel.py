import asyncio

from app.modules.gateway.runtime import RequestRegistry


def test_request_registry_deduplicates_and_cancels_request():
    async def run():
        registry = RequestRegistry()
        first = asyncio.create_task(asyncio.sleep(10))
        assert registry.register("req-1", first) is True
        assert registry.register("req-1", first) is False
        assert await registry.cancel("req-1") is True
        assert first.cancelled() is True
        assert await registry.cancel("missing") is False
        registry.complete("req-1")
        duplicate = asyncio.create_task(asyncio.sleep(0))
        assert registry.register("req-1", duplicate) is False
        duplicate.cancel()

    asyncio.run(run())
