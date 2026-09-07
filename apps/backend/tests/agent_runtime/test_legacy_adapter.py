import asyncio

from app.modules.agent_runtime.legacy_adapter import LegacyGraphEventAdapter


def test_legacy_graph_event_adapter_preserves_payload_and_adds_context():
    async def source():
        yield {"type": "message_delta", "content": "你好"}

    async def collect():
        return [
            event
            async for event in LegacyGraphEventAdapter().stream(
                source(), request_id="r1", conversation_id=7
            )
        ]

    events = asyncio.run(collect())

    assert len(events) == 1
    assert events[0].type == "message_delta"
    assert events[0].payload["content"] == "你好"
    assert events[0].request_id == "r1"
    assert events[0].conversation_id == 7
