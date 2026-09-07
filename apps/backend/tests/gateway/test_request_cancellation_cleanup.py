import asyncio

from app.modules.gateway.router import _cancel_pending_request_futures


def test_cancel_pending_request_futures_clears_waiting_inputs():
    async def check():
        loop = asyncio.get_running_loop()
        pending_maps = [
            {"mcp-1": loop.create_future()},
            {"host-1": loop.create_future()},
            {"question-1": loop.create_future()},
        ]
        futures = [future for pending in pending_maps for future in pending.values()]
        _cancel_pending_request_futures(*pending_maps)
        assert all(future.cancelled() for future in futures) is True
        assert all(pending == {} for pending in pending_maps)

    asyncio.run(check())
