import asyncio

from app.modules.agent_runtime.contracts import AgentEvent
from app.modules.agent_runtime.persistence import (
    BufferedAgentRunPersistence,
    NullAgentRunPersistence,
)


def test_null_persistence_is_safe_for_runtime_without_storage():
    asyncio.run(NullAgentRunPersistence().record(AgentEvent("completed")))


def test_buffered_persistence_deduplicates_replayed_events():
    persistence = BufferedAgentRunPersistence("r1")
    event = AgentEvent("completed", {"event_id": "e1"})

    async def record_twice():
        await persistence.record(event)
        await persistence.record(AgentEvent("completed", {"event_id": "e1"}))

    asyncio.run(record_twice())
    assert len(persistence.events) == 1
    assert persistence.events[0].request_id == "r1"


def test_buffered_persistence_keeps_multiple_streaming_events_without_id():
    persistence = BufferedAgentRunPersistence("r1")

    async def record_stream():
        await persistence.record(AgentEvent("message_delta", {"content": "a"}))
        await persistence.record(AgentEvent("message_delta", {"content": "b"}))

    asyncio.run(record_stream())

    assert [event.payload["content"] for event in persistence.events] == ["a", "b"]


def test_buffered_persistence_assigns_local_order_and_snapshot():
    persistence = BufferedAgentRunPersistence("r1")

    async def record_events():
        await persistence.record(AgentEvent("message_delta", {"content": "a"}))
        await persistence.record(AgentEvent("message_delta", {"content": "b"}))

    asyncio.run(record_events())
    snapshot = persistence.snapshot()

    assert isinstance(snapshot, tuple)
    assert persistence.sequences == [1, 2]
    assert "_runtime_sequence" not in snapshot[0].payload
