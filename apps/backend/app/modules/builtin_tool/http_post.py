"""内置工具 http_post：向公开 HTTP/HTTPS 地址发送 POST 请求。

安全约束与 http_get 一致：仅允许公开公网地址（SSRF 防护）、无认证信息、
响应大小受限。支持 JSON 请求体，返回 JSON/文本内容。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.core.logging import get_logger
from app.modules.builtin_tool.http_get import (
    HttpGetError,
    HttpGetResult,
    _media_type,
    _read_limited,
    _response_kind,
    sanitized_url,
    validate_public_target,
    validate_public_url,
)

logger = get_logger(__name__)


async def fetch_http_post(
    url: str,
    *,
    body: dict | None = None,
    temp_dir: Path,
    total_timeout_seconds: float,
    text_max_bytes: int,
    text_max_chars: int,
    file_max_bytes: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpGetResult:
    """发送 POST 请求并返回 JSON/文本响应（文件等非文本响应报错提示）。"""
    current_url = validate_public_url(url)
    payload = body if isinstance(body, dict) else {}
    try:
        async with asyncio.timeout(total_timeout_seconds):
            timeout = httpx.Timeout(
                min(total_timeout_seconds, 30.0),
                connect=min(total_timeout_seconds, 10.0),
            )
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                transport=transport,
                trust_env=False,
            ) as client:
                for redirect_count in range(4):
                    await validate_public_target(current_url)
                    async with client.stream(
                        "POST", current_url, json=payload
                    ) as response:
                        if response.is_redirect:
                            if redirect_count >= 3:
                                raise HttpGetError("too_many_redirects")
                            location = response.headers.get("location")
                            if not location:
                                raise HttpGetError("invalid_redirect")
                            current_url = validate_public_url(
                                urljoin(current_url, location)
                            )
                            continue
                        if not 200 <= response.status_code < 300:
                            raise HttpGetError(
                                "upstream_http_error",
                                status_code=response.status_code,
                            )
                        media_type = _media_type(response.headers)
                        kind = _response_kind(media_type)
                        if kind not in {"json", "text"}:
                            raise HttpGetError(
                                "unsupported_response_type",
                                status_code=response.status_code,
                            )
                        data = await _read_limited(response, text_max_bytes)
                        try:
                            text = data.decode(response.encoding or "utf-8")
                        except (LookupError, UnicodeDecodeError) as exc:
                            raise HttpGetError(
                                "unsupported_content_encoding"
                            ) from exc
                        truncated = len(text) > text_max_chars
                        content: object = text[:text_max_chars]
                        if kind == "json":
                            try:
                                parsed = json.loads(data)
                                serialized = json.dumps(
                                    parsed,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                content = (
                                    parsed
                                    if len(serialized) <= text_max_chars
                                    else serialized[:text_max_chars]
                                )
                                truncated = len(serialized) > text_max_chars
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                kind = "text"
                        return HttpGetResult(
                            kind=kind,
                            status_code=response.status_code,
                            content_type=media_type,
                            final_url=sanitized_url(str(response.url)),
                            size_bytes=len(data),
                            truncated=truncated,
                            content=content,
                        )
    except TimeoutError as exc:
        raise HttpGetError("request_timeout") from exc
    except httpx.TimeoutException as exc:
        raise HttpGetError("request_timeout") from exc
    except httpx.DecodingError as exc:
        raise HttpGetError("unsupported_content_encoding") from exc
    except httpx.HTTPError as exc:
        logger.info("HTTP POST transport failed host=%s", url)
        raise HttpGetError("upstream_http_error") from exc
    raise HttpGetError("upstream_http_error")
