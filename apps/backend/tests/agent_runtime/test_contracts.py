from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentEventType,
    AgentRequest,
    ToolCall,
    ToolOutcome,
)


def test_contracts_keep_runtime_data_typed_and_protocol_free():
    request = AgentRequest(agent_id=1, message="你好", channel="embed")
    call = ToolCall(id="call-1", name="search", arguments={"q": "agent"})
    event = AgentEvent(AgentEventType.TOOL_STARTED, payload={"name": call.name})
    outcome = ToolOutcome(status="completed", result={"ok": True})

    assert request.agent_id == 1
    assert call.arguments["q"] == "agent"
    assert event.type == AgentEventType.TOOL_STARTED
    assert outcome.result == {"ok": True}
