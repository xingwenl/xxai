from app.modules.agent_runtime.tool_events import build_tool_event, summarize_tool_value


def test_tool_event_is_bounded_and_classified():
    tool = type("Tool", (), {"name": "search", "kind": "builtin"})()
    event = build_tool_event(tool, {"id": "c1", "args": {"q": "x"}})

    assert event["tool_type"] == "builtin_tool"
    assert event["tool_call_id"] == "c1"
    assert len(summarize_tool_value("x" * 20, limit=5)) == 5
