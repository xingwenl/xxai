from __future__ import annotations

from pathlib import Path

from jsonschema import ValidationError, validate

from app.core.config import get_settings
from app.modules.asset.services import persist_asset
from app.modules.builtin_tool.http_get import HttpGetError, fetch_http_get
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.schemas import BuiltinToolOutcome


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

    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    try:
        fetched = await fetch_http_get(
            arguments["url"],
            temp_dir=temp_dir,
            total_timeout_seconds=settings.builtin_http_get_timeout_seconds,
            text_max_bytes=settings.builtin_http_get_text_max_bytes,
            text_max_chars=settings.builtin_http_get_text_max_chars,
            file_max_bytes=settings.builtin_http_get_file_max_bytes,
        )
        asset_data = None
        if fetched.temp_path is not None:
            try:
                asset = await persist_asset(
                    asset_repo,
                    fetched.temp_path,
                    platform_id=platform_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    platform_end_user_id=platform_end_user_id,
                    filename=fetched.filename or "download",
                    content_type=fetched.content_type,
                    size_bytes=fetched.size_bytes,
                    source_url=fetched.final_url,
                )
            except Exception:
                fetched.temp_path.unlink(missing_ok=True)
                raise
            asset_data = {
                "asset_id": asset.asset_id,
                "filename": asset.filename,
                "content_type": asset.content_type,
                "size_bytes": asset.size_bytes,
                "download_url": f"/api/v1/assets/{asset.asset_id}",
            }
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
    except HttpGetError as exc:
        error = {"code": exc.code}
        if exc.status_code is not None:
            error["status_code"] = exc.status_code
        return BuiltinToolOutcome(status="failed", result={"error": error})
    except Exception:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "storage_failed"}}
        )
