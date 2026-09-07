import asyncio

from app.modules.agent_runtime.conversation_adapter import (
    stream_runtime_as_conversation,
)
from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentEventType,
    ToolOutcome,
)


async def _events(*events):
    for event in events:
        yield event


def test_runtime_tool_events_are_expanded_for_conversation():
    outcome = ToolOutcome(status="completed", result={"ok": True}, call_id="c1")
    source = _events(
        AgentEvent(
            AgentEventType.TOOL_STARTED,
            {
                "tool_calls": [
                    {"id": "c1", "name": "first", "arguments": {}},
                    {"id": "c2", "name": "second", "arguments": {"x": 1}},
                ]
            },
        ),
        AgentEvent(
            AgentEventType.TOOL_COMPLETED,
            {
                "tool_call_id": "c1",
                "tool_name": "first",
                "outcome": outcome,
            },
        ),
    )

    async def collect():
        return [item async for item in stream_runtime_as_conversation(source)]

    actual = asyncio.run(collect())

    assert [item["type"] for item in actual] == [
        "tool_started",
        "tool_started",
        "tool_completed",
    ]
    assert actual[0]["tool_call_id"] == "c1"
    assert actual[1]["tool"] == "second"
    assert actual[2]["outcome"] is outcome


def test_tool_started_keeps_runtime_tool_type_when_available():
    source = _events(
        AgentEvent(
            AgentEventType.TOOL_STARTED,
            {
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "lookup",
                        "arguments": {"city": "上海"},
                        "tool_type": "mcp_tool",
                    }
                ]
            },
        ),
    )

    async def collect():
        return [item async for item in stream_runtime_as_conversation(source)]

    actual = asyncio.run(collect())

    assert actual[0]["tool_type"] == "mcp_tool"
    assert actual[0]["input_summary"] == '{"city":"上海"}'


def test_tool_started_falls_back_to_host_tool_without_type():
    source = _events(
        AgentEvent(
            AgentEventType.TOOL_STARTED,
            {
                "tool_calls": [
                    {"id": "c1", "name": "browser", "arguments": {}}
                ]
            },
        ),
    )

    async def collect():
        return [item async for item in stream_runtime_as_conversation(source)]

    actual = asyncio.run(collect())

    assert actual[0]["tool_type"] == "host_tool"
