import pytest

from app.modules.gateway.connection import (
    MAX_MESSAGE_BYTES,
    MAX_TEXT_BYTES,
    RequestLimiter,
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


def test_connection_allows_only_one_active_request():
    limiter = RequestLimiter()

    assert limiter.begin() is True
    assert limiter.begin() is False
    limiter.end()
    assert limiter.begin() is True
