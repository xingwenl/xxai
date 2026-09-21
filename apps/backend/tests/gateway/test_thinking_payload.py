"""message_send 的 thinking 字段校验与透传。"""

import asyncio
import json

from app.modules.gateway.router import _handle_message_send
from app.modules.gateway.runtime import RequestRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def make_envelope(sent: list[dict]):
    def envelope(
        event_type: str,
        event_payload: dict,
        *,
        conversation_id: int | None = None,
        request_id: str | None = None,
    ) -> str:
        value = {
            "id": f"evt_{len(sent) + 1}",
            "type": event_type,
            "protocolVersion": 1,
            "payload": event_payload,
        }
        if conversation_id is not None:
            value["conversationId"] = conversation_id
        if request_id is not None:
            value["requestId"] = request_id
        sent.append(value)
        return json.dumps(value, ensure_ascii=False)

    return envelope


def message_send_kwargs(
    ws: FakeWebSocket, *, payload: dict, request_id: str = "req-1"
):
    return {
        "websocket": ws,
        "envelope": make_envelope(ws.sent),
        "message": {
            "type": "message_send",
            "requestId": request_id,
            "payload": payload,
        },
        "request_id": request_id,
        "payload": {"platform_id": 1, "client_id": "client-1", "sub": 2},
        "agent_id": 7,
        "quota_service": None,
        "registry": RequestRegistry(),
        "active_task": None,
        "active_request": None,
        "event_queue": asyncio.Queue(),
        "pending_mcp_confirmations": {},
        "pending_host_results": {},
        "pending_questions": {},
        "host_tool_repo": None,
        "registered_host_tools": set(),
        "registered_host_policies": {},
    }


def test_non_boolean_thinking_is_rejected():
    """字符串等歧义取值必须被拒绝，避免 "false" 被当成真值开启思考。"""

    async def scenario():
        ws = FakeWebSocket()
        active_request, active_task = await _handle_message_send(
            **message_send_kwargs(
                ws, payload={"text": "hello", "thinking": "false"}
            )
        )

        assert active_request is None
        assert active_task is None
        error = ws.sent[-1]
        assert error["type"] == "error"
        assert error["payload"]["code"] == "invalid_thinking"
        assert error["payload"]["retryable"] is False

    asyncio.run(scenario())


def test_boolean_thinking_is_accepted():
    async def scenario():
        ws = FakeWebSocket()
        # 校验通过即会启动真实后台任务，这里只断言未被协议错误拦截。
        active_request, active_task = await _handle_message_send(
            **message_send_kwargs(ws, payload={"text": "hello", "thinking": True})
        )

        assert active_request == "req-1"
        assert active_task is not None
        assert ws.sent == []
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)

    asyncio.run(scenario())


def test_omitted_thinking_is_accepted():
    """不传 thinking 保持兼容，不触发校验错误。"""

    async def scenario():
        ws = FakeWebSocket()
        active_request, active_task = await _handle_message_send(
            **message_send_kwargs(ws, payload={"text": "hello"})
        )

        assert active_request == "req-1"
        assert active_task is not None
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)

    asyncio.run(scenario())
