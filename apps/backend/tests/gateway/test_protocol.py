import pytest
from pydantic import ValidationError

from app.modules.gateway.schemas import ErrorPayload, ProtocolEnvelope


def test_protocol_envelope_uses_wire_aliases_and_preserves_optional_fields():
    event = ProtocolEnvelope.model_validate(
        {
            "id": "evt_01",
            "type": "message_delta",
            "protocolVersion": 1,
            "conversationId": "42",
            "requestId": "req_01",
            "sequence": 3,
            "timestamp": "2026-07-27T00:00:00Z",
            "payload": {"content": "你好"},
            "futureField": "ignored",
        }
    )

    assert event.protocol_version == 1
    assert event.conversation_id == "42"
    assert event.payload.content == "你好"
    assert event.model_dump(by_alias=True)["protocolVersion"] == 1
    assert "futureField" not in event.model_dump(by_alias=True)


def test_protocol_envelope_rejects_unknown_major_version():
    with pytest.raises(ValidationError):
        ProtocolEnvelope.model_validate(
            {
                "id": "evt_01",
                "type": "message_delta",
                "protocolVersion": 2,
                "sequence": 1,
                "timestamp": "2026-07-27T00:00:00Z",
                "payload": {},
            }
        )


def test_protocol_envelope_requires_wire_fields():
    with pytest.raises(ValidationError):
        ProtocolEnvelope.model_validate(
            {
                "id": "evt_01",
                "type": "message_delta",
                "protocolVersion": 1,
                "sequence": 1,
                "payload": {},
            }
        )


def test_error_payload_has_stable_retry_contract():
    error = ErrorPayload.model_validate(
        {"code": "token_expired", "message": "Token expired", "retryable": True}
    )

    assert error.code == "token_expired"
    assert error.retryable is True
