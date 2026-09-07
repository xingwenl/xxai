from app.modules.agent_runtime.context import AgentRuntimeContext


def test_context_copy_isolated_for_turn_state():
    context = AgentRuntimeContext(
        agent=object(),
        version=object(),
        messages=["user"],
        tools=["tool"],
        citations=[{"id": 1}],
        metadata={"trace": "r1"},
    )

    copied = context.copy_for_turn()
    copied.messages.append("assistant")
    copied.metadata["turn"] = 1

    assert context.messages == ["user"]
    assert "turn" not in context.metadata
