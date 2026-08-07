from __future__ import annotations

import asyncio
import socket
from functools import wraps

import httpx
import pytest

from app.modules.builtin_tool.http_get import (
    HttpGetError,
    fetch_http_get,
    sanitized_url,
    validate_public_target,
    validate_public_url,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def test_validate_public_url_rejects_credentials_and_non_http_protocols() -> None:
    for url in (
        "file:///etc/passwd",
        "https://user:password@example.com/data",
        "http://",
    ):
        with pytest.raises(HttpGetError) as error:
            validate_public_url(url)
        assert error.value.code == "invalid_url"


@async_test
async def test_validate_public_target_rejects_any_private_dns_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ],
    )
    with pytest.raises(HttpGetError) as error:
        await validate_public_target("https://example.com/data")
    assert error.value.code == "target_not_public"


@async_test
async def test_fetch_json_returns_parsed_content_and_sanitized_url(
    monkeypatch, tmp_path
) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_get.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            json={"ok": True},
            request=request,
        )
    )
    result = await fetch_http_get(
        "https://example.com/data?token=secret#fragment",
        temp_dir=tmp_path,
        total_timeout_seconds=30,
        text_max_bytes=1024,
        text_max_chars=100,
        file_max_bytes=1024,
        transport=transport,
    )
    assert result.kind == "json"
    assert result.content == {"ok": True}
    assert result.final_url == "https://example.com/data"
    assert sanitized_url("https://example.com/a?secret=1#x") == "https://example.com/a"


@async_test
async def test_fetch_binary_streams_to_temp_file(monkeypatch, tmp_path) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_get.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={
                "content-type": "image/png",
                "content-disposition": 'attachment; filename="preview.png"',
            },
            content=b"png-bytes",
            request=request,
        )
    )
    result = await fetch_http_get(
        "https://example.com/preview",
        temp_dir=tmp_path,
        total_timeout_seconds=30,
        text_max_bytes=1024,
        text_max_chars=100,
        file_max_bytes=1024,
        transport=transport,
    )
    assert result.kind == "image"
    assert result.filename == "preview.png"
    assert result.temp_path is not None
    assert result.temp_path.read_bytes() == b"png-bytes"
    result.temp_path.unlink()


@async_test
async def test_unknown_binary_media_type_is_forced_to_octet_stream(
    monkeypatch, tmp_path
) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_get.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/x-dangerous-plugin"},
            content=b"binary",
            request=request,
        )
    )
    result = await fetch_http_get(
        "https://example.com/plugin.bin",
        temp_dir=tmp_path,
        total_timeout_seconds=30,
        text_max_bytes=1024,
        text_max_chars=100,
        file_max_bytes=1024,
        transport=transport,
    )
    assert result.kind == "file"
    assert result.content_type == "application/octet-stream"
    assert result.temp_path is not None
    result.temp_path.unlink()


@async_test
async def test_fetch_rejects_oversized_chunked_file_and_cleans_temp(
    monkeypatch, tmp_path
) -> None:
    async def allow_target(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_get.validate_public_target", allow_target
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"0123456789",
            request=request,
        )
    )
    with pytest.raises(HttpGetError) as error:
        await fetch_http_get(
            "https://example.com/report.pdf",
            temp_dir=tmp_path,
            total_timeout_seconds=30,
            text_max_bytes=4,
            text_max_chars=4,
            file_max_bytes=5,
            transport=transport,
        )
    assert error.value.code == "response_too_large"
    assert list(tmp_path.iterdir()) == []


@async_test
async def test_redirect_target_is_revalidated(monkeypatch, tmp_path) -> None:
    checked: list[str] = []

    async def validate_target(url: str) -> None:
        checked.append(url)
        if "127.0.0.1" in url:
            raise HttpGetError("target_not_public")

    monkeypatch.setattr(
        "app.modules.builtin_tool.http_get.validate_public_target", validate_target
    )

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            request=request,
        )

    with pytest.raises(HttpGetError) as error:
        await fetch_http_get(
            "https://example.com/start",
            temp_dir=tmp_path,
            total_timeout_seconds=30,
            text_max_bytes=1024,
            text_max_chars=100,
            file_max_bytes=1024,
            transport=httpx.MockTransport(respond),
        )
    assert error.value.code == "target_not_public"
    assert checked == [
        "https://example.com/start",
        "http://127.0.0.1/private",
    ]
