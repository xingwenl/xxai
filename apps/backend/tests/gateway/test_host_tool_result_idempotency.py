import asyncio
from types import SimpleNamespace

from app.modules.gateway.router import _handle_host_tool_result
from app.modules.gateway.router import _handle_confirmation_resolve


def test_confirmation_rejection_resolves_waiter_once_and_marks_audit_rejected():
    async def scenario():
        audit = SimpleNamespace(status="awaiting_confirmation")
        transitions = []

        class Repo:
            async def get_call(self, *args, **kwargs):
                return audit

            async def transition_call(self, current, status, **kwargs):
                transitions.append((status, kwargs))
                current.status = status

        future = asyncio.get_running_loop().create_future()
        pending = {"call-reject": future}
        message = {
            "payload": {"callId": "call-reject", "approved": False}
        }
        payload = {"platform_id": 1, "sub": 2}

        await _handle_confirmation_resolve(
            message=message,
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_mcp_confirmations={},
            pending_host_results=pending,
        )
        # 页面重复发送拒绝时，审计已离开 awaiting_confirmation，不能再次转换。
        await _handle_confirmation_resolve(
            message=message,
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_mcp_confirmations={},
            pending_host_results=pending,
        )

        assert await future == {"error": "host_tool_rejected"}
        assert audit.status == "rejected"
        assert transitions == [("rejected", {})]

    asyncio.run(scenario())


def test_late_confirmation_and_host_result_do_not_mutate_terminal_audit():
    async def scenario():
        audit = SimpleNamespace(status="rejected")
        transitions = []

        class Repo:
            async def get_call(self, *args, **kwargs):
                return audit

            async def transition_call(self, current, status, **kwargs):
                transitions.append((status, kwargs))
                current.status = status

        confirmation_message = {
            "payload": {"callId": "call-late", "approved": True}
        }
        result_message = {
            "payload": {"callId": "call-late", "result": {"ok": True}}
        }
        payload = {"platform_id": 1, "sub": 2}
        pending = {"call-late": asyncio.get_running_loop().create_future()}

        await _handle_confirmation_resolve(
            message=confirmation_message,
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_mcp_confirmations={},
            pending_host_results=pending,
        )
        await _handle_host_tool_result(
            message=result_message,
            message_type="host_tool_result",
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_host_results=pending,
        )

        assert audit.status == "rejected"
        assert transitions == []
        assert not pending["call-late"].done()
        pending["call-late"].cancel()

    asyncio.run(scenario())


def test_host_tool_result_resolves_once_and_ignores_late_duplicate():
    async def scenario():
        audit = SimpleNamespace(status="running")
        transitions = []

        class Repo:
            async def get_call(self, *args, **kwargs):
                return audit

            async def transition_call(self, current, status, **kwargs):
                transitions.append((status, kwargs))
                current.status = status

        future = asyncio.get_running_loop().create_future()
        pending = {"call-1": future}
        message = {
            "payload": {"callId": "call-1", "result": {"ok": True}}
        }
        payload = {"platform_id": 1, "sub": 2}

        await _handle_host_tool_result(
            message=message,
            message_type="host_tool_result",
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_host_results=pending,
        )
        await _handle_host_tool_result(
            message=message,
            message_type="host_tool_result",
            payload=payload,
            agent_id=3,
            host_tool_repo=Repo(),
            pending_host_results=pending,
        )

        assert await future == {"ok": True}
        assert transitions == [("succeeded", {"result": {"ok": True}})]

    asyncio.run(scenario())


def test_late_callback_for_different_request_id_does_not_wake_waiter():
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        pending = {"call-1": future}
        audit = SimpleNamespace(status="running")

        class Repo:
            async def get_call(self, *args, **kwargs):
                return audit

            async def transition_call(self, *args, **kwargs):
                raise AssertionError("mismatched request must not mutate audit")

        await _handle_host_tool_result(
            message={
                "requestId": "request-b",
                "payload": {"callId": "call-1", "result": {"ok": True}},
            },
            message_type="host_tool_result",
            payload={"platform_id": 1, "sub": 2},
            agent_id=3,
            host_tool_repo=Repo(),
            pending_host_results=pending,
            active_request_id="request-a",
        )

        assert not future.done()
        future.cancel()

    asyncio.run(scenario())
