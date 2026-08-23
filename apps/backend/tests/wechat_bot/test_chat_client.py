"""微信 chat 接口客户端单元测试（mock httpx）。"""

import asyncio

import httpx

from app.modules.wechat_bot.chat_client import (
    ConversationNotFoundError,
    WeChatChatClient,
)


class _FakeResponse:
    def __init__(self, body) -> None:
        self._body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def test_send_chat_returns_content(monkeypatch) -> None:
    captured = {}

    class _FakeAsyncClient:
        def __init__(self, timeout):
            self._timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse(
                {"data": {"content": "智能体回复", "conversation_id": 10}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = WeChatChatClient("http://api:8000")
    reply = asyncio.run(
        client.send_chat(api_token="tok", agent_id=7, message="你好")
    )
    assert reply.content == "智能体回复"
    assert reply.conversation_id == 10
    assert captured["url"] == "http://api:8000/api/v1/agents/7/chat"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["json"] == {"message": "你好", "stream": False}


def test_send_chat_carries_conversation_id(monkeypatch) -> None:
    captured = {}

    class _FakeAsyncClient:
        def __init__(self, timeout):
            self._timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            captured["json"] = json
            return _FakeResponse(
                {"data": {"content": "好的", "conversation_id": 42}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = WeChatChatClient("http://api:8000")
    reply = asyncio.run(
        client.send_chat(
            api_token="tok", agent_id=7, message="你好", conversation_id=42
        )
    )
    assert captured["json"] == {
        "message": "你好",
        "stream": False,
        "conversation_id": 42,
    }
    assert reply.conversation_id == 42


def test_send_chat_empty_content_falls_back(monkeypatch) -> None:
    class _FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            return _FakeResponse({"data": {"content": ""}})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = WeChatChatClient("http://api:8000")
    reply = asyncio.run(
        client.send_chat(api_token="tok", agent_id=7, message="你好")
    )
    assert "抱歉" in reply.content


def test_send_chat_conversation_404_raises(monkeypatch) -> None:
    class _NotFoundResponse:
        status_code = 404

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            return _NotFoundResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = WeChatChatClient("http://api:8000")
    try:
        asyncio.run(
            client.send_chat(
                api_token="tok", agent_id=7, message="你好", conversation_id=99
            )
        )
    except ConversationNotFoundError:
        return
    raise AssertionError("expected ConversationNotFoundError")
