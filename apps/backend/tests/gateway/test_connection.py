from __future__ import annotations

import pytest
from app.modules.gateway.connection import (
    MAX_MESSAGE_BYTES,
    MAX_TEXT_BYTES,
    normalize_conversation_id,
    validate_incoming_message,
)


class TestNormalizeConversationId:
    def test_positive_integer(self):
        assert normalize_conversation_id(10) == 10

    def test_string_positive(self):
        assert normalize_conversation_id("10") == 10

    def test_none(self):
        assert normalize_conversation_id(None) is None

    def test_reject_zero(self):
        with pytest.raises(ValueError, match="invalid_conversation_id"):
            normalize_conversation_id(0)

    def test_reject_negative(self):
        with pytest.raises(ValueError, match="invalid_conversation_id"):
            normalize_conversation_id(-1)

    def test_reject_boolean(self):
        with pytest.raises(ValueError, match="invalid_conversation_id"):
            normalize_conversation_id(True)

    def test_reject_non_numeric_string(self):
        with pytest.raises(ValueError, match="invalid_conversation_id"):
            normalize_conversation_id("abc")


class TestValidateIncomingMessage:
    def test_message_send_with_text(self):
        msg = validate_incoming_message(
            '{"type":"message_send","payload":{"text":"hello"}}'
        )
        assert msg["type"] == "message_send"
        assert msg["payload"]["text"] == "hello"

    def test_message_send_too_large(self):
        big = "x" * (MAX_MESSAGE_BYTES + 1)
        with pytest.raises(ValueError, match="message_too_large"):
            validate_incoming_message(
                '{"type":"message_send","payload":{"text":"' + big + '"}}'
            )

    def test_message_send_text_too_large(self):
        big = "x" * (MAX_TEXT_BYTES + 1)
        with pytest.raises(ValueError, match="text_too_large"):
            validate_incoming_message(
                '{"type":"message_send","payload":{"text":"' + big + '"}}'
            )

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="invalid_json"):
            validate_incoming_message("not json")

    def test_message_not_dict(self):
        with pytest.raises(ValueError, match="invalid_message"):
            validate_incoming_message("[1,2,3]")

    def test_message_send_with_attachments_accepts(self):
        """attachments 字段应被接受（网关层不做 schema 校验，仅大小检查）。"""
        msg = validate_incoming_message(
            '{"type":"message_send","payload":{"text":"hello","attachments":[{"assetId":"abc","filename":"a.pdf","mimeType":"application/pdf","size":100}]}}'
        )
        assert msg["type"] == "message_send"
        assert msg["payload"]["attachments"][0]["assetId"] == "abc"

    def test_host_tool_payload_required(self):
        with pytest.raises(ValueError, match="invalid_host_tool_payload"):
            validate_incoming_message(
                '{"type":"host_tool_result","payload":null}'
            )
