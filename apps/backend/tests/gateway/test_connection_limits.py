import pytest

from app.modules.gateway.connection import (
    MAX_MESSAGE_BYTES,
    MAX_TEXT_BYTES,
    normalize_conversation_id,
    validate_incoming_message,
)


def test_connection_rejects_oversized_messages_and_text():
    with pytest.raises(ValueError, match="message_too_large"):
        validate_incoming_message("x" * (MAX_MESSAGE_BYTES + 1))

    with pytest.raises(ValueError, match="text_too_large"):
        validate_incoming_message(
            '{"type":"message_send","payload":{"text":"'
            + "x" * (MAX_TEXT_BYTES + 1)
            + '"}}'
        )


def test_connection_accepts_ping_and_auth_sized_messages():
    validate_incoming_message('{"type":"ping","payload":{}}')
    validate_incoming_message('{"type":"auth","payload":{"token":"short"}}')


@pytest.mark.parametrize("value", ["42", 42])
def test_normalize_conversation_id_accepts_positive_numeric_values(value):
    assert normalize_conversation_id(value) == 42


@pytest.mark.parametrize("value", ["", "abc", "0", 0, -1, True])
def test_normalize_conversation_id_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="invalid_conversation_id"):
        normalize_conversation_id(value)
