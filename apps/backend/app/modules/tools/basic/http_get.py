"""http.get 基本工具：GET 一个公开 URL，返回内容或临时文件引用。

单一职责：只取数据，不鉴权、不落库，结果如何处置由上层业务工具决定。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import tempfile
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.asset.services import sanitize_filename
from app.modules.tools.basic.framework import BasicToolError, basic_tool

logger = get_logger(__name__)

_TEXT_MEDIA_TYPES = {
    "application/javascript",
    "application/sql",
    "application/xml",
    "application/x-www-form-urlencoded",
    "image/svg+xml",
}
_SAFE_FILE_MEDIA_TYPES = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_FILENAME_STAR = re.compile(r"filename\*=UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)


def sanitized_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))


def validate_public_url(url: str) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise BasicToolError("invalid_url")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise BasicToolError("invalid_url") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise BasicToolError("invalid_url")
    try:
        parsed.hostname.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BasicToolError("invalid_url") from exc
    return url


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def validate_public_target(url: str) -> None:
    validate_public_url(url)
    host = urlsplit(url).hostname
    assert host is not None
    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise BasicToolError("invalid_url") from exc
    resolved = {item[4][0] for item in addresses}
    if not resolved or any(not _is_public_ip(item) for item in resolved):
        raise BasicToolError("target_not_public")


def _media_type(headers: httpx.Headers) -> str:
    return (
        headers.get("content-type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )


def _response_kind(media_type: str) -> str:
    if media_type == "application/json" or media_type.endswith("+json"):
        return "json"
    if media_type.startswith("text/") or media_type in _TEXT_MEDIA_TYPES:
        return "text"
    if media_type.startswith("image/"):
        return "image"
    return "file"


def _safe_content_type(kind: str, media_type: str) -> str:
    if kind == "image":
        return media_type
    if media_type in _SAFE_FILE_MEDIA_TYPES or media_type.startswith(
        ("audio/", "video/")
    ):
        return media_type
    return "application/octet-stream"


def _filename_from_response(response: httpx.Response) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = _FILENAME_STAR.search(disposition)
    if match:
        return sanitize_filename(unquote(match.group(1)))
    match = _FILENAME.search(disposition)
    if match:
        return sanitize_filename(match.group(1))
    return sanitize_filename(Path(urlsplit(str(response.url)).path).name)


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise BasicToolError("response_too_large")
    return bytes(data)


async def _stream_to_temp(
    response: httpx.Response, *, temp_dir: Path, max_bytes: int
) -> tuple[Path, int]:
    await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix="http-get-", dir=temp_dir, delete=False)
    path = Path(handle.name)
    size = 0
    try:
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise BasicToolError("response_too_large")
            await asyncio.to_thread(handle.write, chunk)
        await asyncio.to_thread(handle.flush)
        await asyncio.to_thread(handle.close)
        return path, size
    except BaseException:
        handle.close()
        path.unlink(missing_ok=True)
        raise


@basic_tool(
    name="http.get",
    description="GET 一个公开 HTTP/HTTPS URL",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "temp_dir": {"type": "string"},
            "total_timeout_seconds": {"type": "number"},
            "text_max_bytes": {"type": "integer"},
            "text_max_chars": {"type": "integer"},
            "file_max_bytes": {"type": "integer"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    side_effect="none",
)
async def http_get(inputs: dict) -> dict:
    """输入 {url, temp_dir?, 限流参数?} → 输出 {kind, content?, temp_path?, ...}。"""
    settings = get_settings()
    temp_dir = Path(
        inputs.get("temp_dir")
        or Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    )
    total_timeout_seconds = float(
        inputs.get("total_timeout_seconds", settings.builtin_http_get_timeout_seconds)
    )
    text_max_bytes = int(
        inputs.get("text_max_bytes", settings.builtin_http_get_text_max_bytes)
    )
    text_max_chars = int(
        inputs.get("text_max_chars", settings.builtin_http_get_text_max_chars)
    )
    file_max_bytes = int(
        inputs.get("file_max_bytes", settings.builtin_http_get_file_max_bytes)
    )
    transport = inputs.get("transport")

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
                    async with client.stream("GET", current_url) as response:
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
                        final_url = sanitized_url(str(response.url))
                        content_length = response.headers.get("content-length")
                        if content_length and content_length.isdigit():
                            declared_size = int(content_length)
                            limit = (
                                text_max_bytes
                                if kind in {"json", "text"}
                                else file_max_bytes
                            )
                            if declared_size > limit:
                                raise BasicToolError("response_too_large")
                        if kind in {"json", "text"}:
                            data = await _read_limited(response, text_max_bytes)
                            try:
                                text = data.decode(response.encoding or "utf-8")
                            except (LookupError, UnicodeDecodeError) as exc:
                                raise BasicToolError(
                                    "unsupported_content_encoding"
                                ) from exc
                            truncated = len(text) > text_max_chars
                            text = text[:text_max_chars]
                            content: object = text
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
                                "final_url": final_url,
                                "size_bytes": len(data),
                                "truncated": truncated,
                                "content": content,
                                "temp_path": None,
                                "filename": None,
                            }
                        path, size = await _stream_to_temp(
                            response,
                            temp_dir=temp_dir,
                            max_bytes=file_max_bytes,
                        )
                        return {
                            "kind": kind,
                            "status_code": response.status_code,
                            "content_type": _safe_content_type(kind, media_type),
                            "final_url": final_url,
                            "size_bytes": size,
                            "truncated": False,
                            "content": None,
                            "temp_path": str(path),
                            "filename": _filename_from_response(response),
                        }
    except TimeoutError as exc:
        raise BasicToolError("request_timeout") from exc
    except httpx.TimeoutException as exc:
        raise BasicToolError("request_timeout") from exc
    except httpx.DecodingError as exc:
        raise BasicToolError("unsupported_content_encoding") from exc
    except httpx.HTTPError as exc:
        logger.info(
            "HTTP GET transport failed host=%s", urlsplit(inputs["url"]).hostname
        )
        raise BasicToolError("upstream_http_error") from exc
    raise BasicToolError("upstream_http_error")
