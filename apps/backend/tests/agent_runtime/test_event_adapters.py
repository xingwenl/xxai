from app.modules.agent_runtime.event_adapters import event_from_legacy, event_to_legacy


def test_event_adapter_preserves_legacy_fields_in_payload():
    event = event_from_legacy(
        {
            "type": "tool_completed",
            "tool": "search",
            "outcome": {"ok": True},
        },
        request_id="r1",
        conversation_id=3,
    )

    assert event.type == "tool_completed"
    assert event.payload["tool"] == "search"
    assert event.payload["outcome"] == {"ok": True}
    assert event.request_id == "r1"
    assert event.conversation_id == 3


def test_event_adapter_round_trips_protocol_fields():
    original = event_from_legacy(
        {"type": "message_delta", "content": "hi"},
        request_id="r1",
        conversation_id=3,
    )

    assert event_to_legacy(original) == {
        "type": "message_delta",
        "content": "hi",
        "request_id": "r1",
        "conversation_id": 3,
        "payload": {"content": "hi"},
    }
