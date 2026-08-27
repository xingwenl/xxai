"""http_post 业务工具：调基本工具发 POST 并返回内容。"""

from __future__ import annotations

from app.core.config import get_settings
from app.modules.tools.basic.framework import BasicToolError
from app.modules.tools.basic.registry import get_basic_tool
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)


@business_tool(
    name="http_post",
    description="向公开 HTTP/HTTPS URL 发送 POST 请求（可选 JSON 请求体）",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "body": {"type": "object"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    depends_on=("http.post",),
)
async def http_post_business(args: dict, ctx: BusinessToolContext) -> dict:
    settings = get_settings()
    tool = get_basic_tool("http.post")
    try:
        result = await tool.handler(
            {
                "url": args["url"],
                "body": args.get("body"),
                "total_timeout_seconds": settings.builtin_http_get_timeout_seconds,
                "text_max_bytes": settings.builtin_http_get_text_max_bytes,
                "text_max_chars": settings.builtin_http_get_text_max_chars,
            }
        )
    except BasicToolError as exc:
        raise BusinessToolError(exc.code, status_code=exc.status_code) from exc
    return {
        "kind": result["kind"],
        "status_code": result["status_code"],
        "content_type": result["content_type"],
        "final_url": result["final_url"],
        "size_bytes": result["size_bytes"],
        "truncated": result["truncated"],
        "content": result.get("content"),
        "asset": None,
    }
