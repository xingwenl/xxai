import asyncio
import json
import time

from app.modules.gateway.router import _handle_message_send
from app.modules.gateway.runtime import RequestRegistry
from app.modules.quota.service import QuotaDimensions, QuotaService


class FakeRedis:
    def __init__(self, values: dict[str, int]) -> None:
        self.values = values

    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        current = self.values.get(key, 0)
        if current + amount > limit:
            return False, current, window_seconds
        self.values[key] = current + amount
        return True, current + amount, window_seconds

    async def check_and_increment_capped(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[int, int, int]:
        current = self.values.get(key, 0)
        updated = min(limit, current + amount)
        self.values[key] = updated
        exceeded = 1 if current + amount > limit else 0
        return updated, window_seconds, exceeded

    async def peek(self, key: str) -> int:
        return self.values.get(key, 0)


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


def build_quota_service(values: dict[str, int]) -> QuotaService:
    return QuotaService(
        FakeRedis(values),
        limits={"message": 100, "model_tokens": 10},
        window_seconds={"message": 60, "model_tokens": 60},
    )


def message_send_kwargs(ws: FakeWebSocket, quota_service: QuotaService, *, request_id: str):
    return {
        "websocket": ws,
        "envelope": make_envelope(ws.sent),
        "message": {
            "type": "message_send",
            "requestId": request_id,
            "payload": {"text": "hello", "conversationId": 1},
        },
        "request_id": request_id,
        "payload": {"platform_id": 1, "client_id": "client-1", "sub": 2},
        "agent_id": 7,
        "quota_service": quota_service,
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


def test_message_send_blocked_when_model_tokens_window_exhausted():
    async def scenario():
        dimensions = QuotaDimensions(
            platform_id="1",
            client_id="client-1",
            agent_id="7",
            end_user_id="2",
        )
        window = int(time.time() // 60)
        key = QuotaService.key("model_tokens", dimensions, window)
        ws = FakeWebSocket()
        active_request, active_task = await _handle_message_send(
            **message_send_kwargs(
                ws, build_quota_service({key: 10}), request_id="req-1"
            )
        )

        assert active_request is None
        assert active_task is None
        error = ws.sent[-1]
        assert error["type"] == "error"
        assert error["payload"]["code"] == "quota_exceeded"
        assert error["payload"]["message"] == "model token quota exceeded"
        assert error["payload"]["retryable"] is True
        assert int(error["payload"]["details"]["retryAfterSeconds"]) > 0

    asyncio.run(scenario())


def test_message_send_starts_generation_below_model_tokens_limit():
    async def scenario():
        ws = FakeWebSocket()
        active_request, active_task = await _handle_message_send(
            **message_send_kwargs(
                ws, build_quota_service({}), request_id="req-1"
            )
        )

        assert active_request == "req-1"
        assert active_task is not None
        assert ws.sent == []
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)

    asyncio.run(scenario())
