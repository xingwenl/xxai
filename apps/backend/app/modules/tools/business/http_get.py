"""http_get 业务工具：调基本工具取数，文件类内容持久化后包装返回。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.modules.tools.basic.framework import BasicToolError
from app.modules.tools.basic.registry import get_basic_tool
from app.modules.tools.business.assets import persist_fetched_asset
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)


@business_tool(
    name="http_get",
    description="读取公开 HTTP/HTTPS URL",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "minLength": 1}},
        "required": ["url"],
        "additionalProperties": False,
    },
    depends_on=("http.get",),
)
async def http_get_business(args: dict, ctx: BusinessToolContext) -> dict:
    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    tool = get_basic_tool("http.get")
    try:
        result = await tool.handler(
            {
                "url": args["url"],
                "temp_dir": str(temp_dir),
                "total_timeout_seconds": settings.builtin_http_get_timeout_seconds,
                "text_max_bytes": settings.builtin_http_get_text_max_bytes,
                "text_max_chars": settings.builtin_http_get_text_max_chars,
                "file_max_bytes": settings.builtin_http_get_file_max_bytes,
            }
        )
    except BasicToolError as exc:
        raise BusinessToolError(exc.code, status_code=exc.status_code) from exc
    asset_data = await persist_fetched_asset(
        result, ctx, source_url=result.get("final_url", "")
    )
    return {
        "kind": result["kind"],
        "status_code": result["status_code"],
        "content_type": result["content_type"],
        "final_url": result["final_url"],
        "size_bytes": result["size_bytes"],
        "truncated": result["truncated"],
        "content": result.get("content"),
        "asset": asset_data,
    }
