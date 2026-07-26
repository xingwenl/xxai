import pytest
from pydantic import ValidationError

from app.modules.conversation.schemas import ChatRequest, CitationRead


def test_chat_request_accepts_new_conversation_and_stream_flag():
    request = ChatRequest(message="退款规则是什么？", stream=True)

    assert request.conversation_id is None
    assert request.stream is True


def test_citation_requires_source_text():
    with pytest.raises(ValidationError):
        CitationRead(title="退款规则", text="")
