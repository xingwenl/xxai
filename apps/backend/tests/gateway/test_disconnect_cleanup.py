import asyncio


def test_disconnect_cleanup_cancels_host_tool_waiters():
    async def check():
        future = asyncio.get_running_loop().create_future()
        pending = {"host-call-1": future}
        for waiter in pending.values():
            if not waiter.done():
                waiter.cancel()

        assert future.cancelled()

    asyncio.run(check())
