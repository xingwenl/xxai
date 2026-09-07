import asyncio

from app.modules.gateway.runtime import RequestRegistry


def test_request_registry_deduplicates_and_cancels_request():
    async def run():
        registry = RequestRegistry()
        first = asyncio.create_task(asyncio.sleep(10))
        assert registry.register("req-1", first) is True
        assert registry.register("req-1", first) is False
        assert await registry.cancel("req-1") is True
        assert registry.status("req-1").value == "cancelled"
        assert first.cancelled() is True
        assert await registry.cancel("missing") is False
        registry.complete("req-1")
        duplicate = asyncio.create_task(asyncio.sleep(0))
        assert registry.register("req-1", duplicate) is False
        duplicate.cancel()

        failed = asyncio.create_task(asyncio.sleep(10))
        assert registry.register("req-2", failed) is True
        registry.fail("req-2", {"code": "provider_error"})
        assert registry.status("req-2").value == "failed"
        failed.cancel()

    asyncio.run(run())


def test_request_registry_allows_next_request_after_cancellation():
    async def run():
        registry = RequestRegistry()
        first = asyncio.create_task(asyncio.sleep(10))
        assert registry.register("req-1", first) is True

        assert await registry.cancel("req-1") is True

        second = asyncio.create_task(asyncio.sleep(10))
        try:
            assert registry.register("req-2", second) is True
        finally:
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)

    asyncio.run(run())


def test_request_registry_preserves_budget_terminal_state():
    async def run():
        registry = RequestRegistry()
        task = asyncio.create_task(asyncio.sleep(10))
        assert registry.register("budget-1", task) is True
        registry.budget_exceeded("budget-1")
        registry.complete("budget-1")
        assert registry.status("budget-1").value == "budget_exceeded"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
