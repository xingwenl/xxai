from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from app.core.config import get_settings
from app.modules.asset.services import persist_asset
from app.modules.builtin_tool.http_get import (
    HttpGetError,
    HttpGetResult,
    fetch_http_get,
)
from app.modules.builtin_tool.http_post import fetch_http_post
from app.modules.builtin_tool.image_generate import (
    ImageGenerationError,
    generate_images,
)
from app.modules.builtin_tool.image_read import ImageReadError, read_image
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.schemas import BuiltinToolOutcome
from app.modules.model_registry.resolver import resolve_agent_model


@dataclass(frozen=True)
class BuiltinToolContext:
    """一次内置工具调用共享的执行上下文。"""

    asset_repo: Any
    platform_id: int
    agent_id: int
    conversation_id: int
    user_id: int | None = None
    platform_end_user_id: int | None = None
    session: Any | None = None


_ToolHandler = Callable[[dict, BuiltinToolContext], Awaitable[BuiltinToolOutcome]]


def _http_fetch_options(temp_dir: Path) -> dict[str, Any]:
    """聚合 HTTP 工具的公共限流与临时目录参数。"""
    settings = get_settings()
    return {
        "temp_dir": temp_dir,
        "total_timeout_seconds": settings.builtin_http_get_timeout_seconds,
        "text_max_bytes": settings.builtin_http_get_text_max_bytes,
        "text_max_chars": settings.builtin_http_get_text_max_chars,
        "file_max_bytes": settings.builtin_http_get_file_max_bytes,
    }


async def _persist_fetched_asset(
    fetched: HttpGetResult, ctx: BuiltinToolContext
) -> dict | None:
    """将下载的临时文件持久化为受保护资源；纯文本/JSON 响应返回 None。"""
    if fetched.temp_path is None:
        return None
    try:
        asset = await persist_asset(
            ctx.asset_repo,
            fetched.temp_path,
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            platform_end_user_id=ctx.platform_end_user_id,
            filename=fetched.filename or "download",
            content_type=fetched.content_type,
            size_bytes=fetched.size_bytes,
            source_url=fetched.final_url,
        )
    except Exception:
        fetched.temp_path.unlink(missing_ok=True)
        raise
    return {
        "asset_id": asset.asset_id,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "download_url": f"/api/v1/assets/{asset.asset_id}",
    }


def _http_outcome(
    fetched: HttpGetResult, asset_data: dict | None
) -> BuiltinToolOutcome:
    return BuiltinToolOutcome(
        status="completed",
        result={
            "kind": fetched.kind,
            "status_code": fetched.status_code,
            "content_type": fetched.content_type,
            "final_url": fetched.final_url,
            "size_bytes": fetched.size_bytes,
            "truncated": fetched.truncated,
            "content": fetched.content,
            "asset": asset_data,
        },
    )


async def _handle_image_generate(
    arguments: dict, ctx: BuiltinToolContext
) -> BuiltinToolOutcome:
    model_config = await resolve_agent_model(
        ctx.session,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        role="image_generate",
    )
    assets = await generate_images(
        arguments,
        asset_repo=ctx.asset_repo,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        conversation_id=ctx.conversation_id,
        user_id=ctx.user_id,
        platform_end_user_id=ctx.platform_end_user_id,
        model_config=model_config,
    )
    return BuiltinToolOutcome(
        status="completed", result={"kind": "image", "assets": assets}
    )


async def _handle_image_read(
    arguments: dict, ctx: BuiltinToolContext
) -> BuiltinToolOutcome:
    model_config = await resolve_agent_model(
        ctx.session,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        role="image_read",
    )
    result = await read_image(
        arguments,
        asset_repo=ctx.asset_repo,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        conversation_id=ctx.conversation_id,
        user_id=ctx.user_id,
        platform_end_user_id=ctx.platform_end_user_id,
        model_config=model_config,
    )
    return BuiltinToolOutcome(status="completed", result=result)


async def _handle_http_get(
    arguments: dict, ctx: BuiltinToolContext
) -> BuiltinToolOutcome:
    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    fetched = await fetch_http_get(arguments["url"], **_http_fetch_options(temp_dir))
    return _http_outcome(fetched, await _persist_fetched_asset(fetched, ctx))


async def _handle_http_post(
    arguments: dict, ctx: BuiltinToolContext
) -> BuiltinToolOutcome:
    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    fetched = await fetch_http_post(
        arguments["url"],
        body=arguments.get("body") or None,
        **_http_fetch_options(temp_dir),
    )
    return _http_outcome(fetched, await _persist_fetched_asset(fetched, ctx))


# 执行器注册表：key 与 registry 中 BuiltinToolDefinition.executor 一一对应，
# 新增内置工具只需在此追加一条 handler 映射，无需改动主分发逻辑。
_TOOL_HANDLERS: dict[str, _ToolHandler] = {
    "image_generate": _handle_image_generate,
    "image_read": _handle_image_read,
    "http_get": _handle_http_get,
    "http_post": _handle_http_post,
}


async def invoke_builtin_tool(
    builtin_repo,
    asset_repo,
    *,
    tool,
    call: dict,
    platform_id: int,
    agent_id: int,
    conversation_id: int | None,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
    session=None,
) -> BuiltinToolOutcome:
    definition = get_builtin_tool(tool.name)
    if definition is None or not await builtin_repo.is_enabled(
        platform_id, agent_id, tool.name
    ):
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_not_available"}}
        )
    arguments = call.get("args", {})
    try:
        validate(instance=arguments, schema=definition.input_schema)
    except ValidationError:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "invalid_arguments"}}
        )
    if conversation_id is None:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "conversation_required"}}
        )

    handler = _TOOL_HANDLERS.get(definition.executor)
    if handler is None:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_not_available"}}
        )
    ctx = BuiltinToolContext(
        asset_repo=asset_repo,
        platform_id=platform_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
        session=session,
    )
    try:
        return await handler(arguments, ctx)
    except (ImageGenerationError, ImageReadError) as exc:
        return BuiltinToolOutcome(status="failed", result={"error": {"code": exc.code}})
    except HttpGetError as exc:
        error = {"code": exc.code}
        if exc.status_code is not None:
            error["status_code"] = exc.status_code
        return BuiltinToolOutcome(status="failed", result={"error": error})
    except Exception:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "storage_failed"}}
        )
