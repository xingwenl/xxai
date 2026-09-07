import asyncio

from app.modules.agent_runtime.contracts import AgentEvent
from app.modules.agent_runtime.loop import ModelTurn
from app.modules.agent_runtime.runtime import AgentRuntime
from app.modules.agent_runtime.persistence import BufferedAgentRunPersistence


def test_concurrent_streams_keep_events_on_their_own_request():
    async def model(messages, *, emit):
        request_id = messages[0]
        await emit(AgentEvent("message_delta", {"request": request_id}))
        return ModelTurn(content=request_id)

    runtime = AgentRuntime(model=model)

    async def collect(request_id):
        return [
            event
            async for event in runtime.stream([request_id], request_id=request_id)
        ]

    async def run():
        return await asyncio.gather(collect("a"), collect("b"))

    first, second = asyncio.run(run())
    assert {event.payload["request"] for event in first if "request" in event.payload} == {"a"}
    assert {event.payload["request"] for event in second if "request" in event.payload} == {"b"}


def test_concurrent_streams_can_create_request_scoped_persistence():
    persistences = {}

    def factory(request_id):
        persistence = BufferedAgentRunPersistence(request_id or "unknown")
        persistences[request_id] = persistence
        return persistence

    async def model(messages, *, emit):
        await emit(AgentEvent("message_delta", {"request": messages[0]}))
        return ModelTurn(content=messages[0])

    runtime = AgentRuntime(model=model, persistence_factory=factory)

    async def collect(request_id):
        return [
            event
            async for event in runtime.stream([request_id], request_id=request_id)
        ]

    async def run():
        await asyncio.gather(collect("a"), collect("b"))

    asyncio.run(run())

    assert set(persistences) == {"a", "b"}
    assert [event.request_id for event in persistences["a"].events] == ["a", "a"]
    assert [event.request_id for event in persistences["b"].events] == ["b", "b"]
