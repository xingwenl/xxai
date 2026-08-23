from __future__ import annotations

import asyncio
from functools import wraps

import httpx
import pytest

from app.modules.builtin_tool.http_get import HttpGetError
from app.modules.builtin_tool.http_post import fetch_http_post
from app.modules.builtin_tool.registry import get_builtin_tool


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def test_http_post_tool_is_registered() -> None:
    tool = get_builtin_tool("http_post")
    assert tool is not None
    assert tool.executor == "http_post"
    assert "url" in tool.input_schema["properties"]
    assert "body" in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["url"]


@async_test
async def test_fetch_post_sends_json_body_and_returns_parsed_content(
    monkeypatch, tmp_path
) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_post.validate_public_target", allow_target
    )
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("content-type")
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            json={"data": {"list": [1, 2]}},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    result = await fetch_http_post(
        "https://api.example.com/feed",
        body={"cursor": "0", "limit": 20},
        temp_dir=tmp_path,
        total_timeout_seconds=30,
        text_max_bytes=4096,
        text_max_chars=1000,
        file_max_bytes=4096,
        transport=transport,
    )
    assert captured["method"] == "POST"
    assert "application/json" in captured["content_type"]
    assert result.kind == "json"
    assert result.content == {"data": {"list": [1, 2]}}


@async_test
async def test_fetch_post_rejects_non_text_response(monkeypatch, tmp_path) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_post.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4",
            request=request,
        )
    )
    with pytest.raises(HttpGetError) as error:
        await fetch_http_post(
            "https://api.example.com/export",
            temp_dir=tmp_path,
            total_timeout_seconds=30,
            text_max_bytes=4096,
            text_max_chars=1000,
            file_max_bytes=4096,
            transport=transport,
        )
    assert error.value.code == "unsupported_response_type"


@async_test
async def test_fetch_post_propagates_upstream_error(monkeypatch, tmp_path) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_post.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, request=request)
    )
    with pytest.raises(HttpGetError) as error:
        await fetch_http_post(
            "https://api.example.com/missing",
            temp_dir=tmp_path,
            total_timeout_seconds=30,
            text_max_bytes=4096,
            text_max_chars=1000,
            file_max_bytes=4096,
            transport=transport,
        )
    assert error.value.code == "upstream_http_error"
    assert error.value.status_code == 404
