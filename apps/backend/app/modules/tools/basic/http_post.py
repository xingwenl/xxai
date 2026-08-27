"""http.post 基本工具：POST 一个公开 URL，返回 JSON/文本内容。

单一职责：只发送请求并返回数据，不鉴权、不落库。
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.tools.basic.framework import BasicToolError, basic_tool
from app.modules.tools.basic.http_get import (
    _media_type,
    _read_limited,
    _response_kind,
    sanitized_url,
    validate_public_target,
    validate_public_url,
)

logger = get_logger(__name__)


@basic_tool(
    name="http.post",
    description="向公开 HTTP/HTTPS URL 发送 POST 请求（可选 JSON 请求体）",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "body": {"type": "object"},
            "temp_dir": {"type": "string"},
            "total_timeout_seconds": {"type": "number"},
            "text_max_bytes": {"type": "integer"},
            "text_max_chars": {"type": "integer"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    side_effect="none",
)
async def http_post(inputs: dict) -> dict:
    """输入 {url, body?, 限流参数?} → 输出 {kind, content?, ...}。"""
    settings = get_settings()
    total_timeout_seconds = float(
        inputs.get("total_timeout_seconds", settings.builtin_http_get_timeout_seconds)
    )
    text_max_bytes = int(
        inputs.get("text_max_bytes", settings.builtin_http_get_text_max_bytes)
    )
    text_max_chars = int(
        inputs.get("text_max_chars", settings.builtin_http_get_text_max_chars)
    )
    transport = inputs.get("transport")
    payload = inputs.get("body") if isinstance(inputs.get("body"), dict) else {}

    current_url = validate_public_url(inputs["url"])
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
                                raise BasicToolError("too_many_redirects")
                            location = response.headers.get("location")
                            if not location:
                                raise BasicToolError("invalid_redirect")
                            current_url = validate_public_url(
                                urljoin(current_url, location)
                            )
                            continue
                        if not 200 <= response.status_code < 300:
                            raise BasicToolError(
                                "upstream_http_error",
                                status_code=response.status_code,
                            )
                        media_type = _media_type(response.headers)
                        kind = _response_kind(media_type)
                        if kind not in {"json", "text"}:
                            raise BasicToolError(
                                "unsupported_response_type",
                                status_code=response.status_code,
                            )
                        data = await _read_limited(response, text_max_bytes)
                        try:
                            text = data.decode(response.encoding or "utf-8")
                        except (LookupError, UnicodeDecodeError) as exc:
                            raise BasicToolError(
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
                        return {
                            "kind": kind,
                            "status_code": response.status_code,
                            "content_type": media_type,
                            "final_url": sanitized_url(str(response.url)),
                            "size_bytes": len(data),
                            "truncated": truncated,
                            "content": content,
                            "temp_path": None,
                            "filename": None,
                        }
    except TimeoutError as exc:
        raise BasicToolError("request_timeout") from exc
    except httpx.TimeoutException as exc:
        raise BasicToolError("request_timeout") from exc
    except httpx.DecodingError as exc:
        raise BasicToolError("unsupported_content_encoding") from exc
    except httpx.HTTPError as exc:
        logger.info("HTTP POST transport failed host=%s", inputs["url"])
        raise BasicToolError("upstream_http_error") from exc
    raise BasicToolError("upstream_http_error")
