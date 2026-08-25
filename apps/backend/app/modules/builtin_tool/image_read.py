from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.modules.asset.services import persist_asset
from app.modules.builtin_tool.http_get import HttpGetError, fetch_http_get


class ImageReadError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def asset_payload(asset) -> dict:
    return {
        "asset_id": asset.asset_id,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "download_url": f"/api/v1/assets/{asset.asset_id}",
    }


async def read_image(
    arguments: dict,
    *,
    asset_repo,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
) -> dict:
    settings = get_settings()
    asset_id = arguments.get("asset_id")
    if asset_id:
        if user_id is not None:
            asset = await asset_repo.get_for_user_conversation(
                asset_id, user_id, conversation_id
            )
        else:
            asset = await asset_repo.get_for_embed_conversation(
                asset_id,
                platform_id=platform_id,
                agent_id=agent_id,
                end_user_id=platform_end_user_id,
                conversation_id=conversation_id,
            )
        if asset is None or not asset.content_type.startswith("image/"):
            raise ImageReadError("asset_not_found")
        return {"kind": "image", "asset": asset_payload(asset)}

    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    try:
        fetched = await fetch_http_get(
            arguments["url"],
            temp_dir=temp_dir,
            total_timeout_seconds=settings.builtin_http_get_timeout_seconds,
            text_max_bytes=settings.builtin_http_get_text_max_bytes,
            text_max_chars=settings.builtin_http_get_text_max_chars,
            file_max_bytes=settings.image_max_bytes,
        )
    except HttpGetError as exc:
        raise ImageReadError(exc.code) from exc
    if fetched.kind != "image" or fetched.temp_path is None:
        if fetched.temp_path is not None:
            fetched.temp_path.unlink(missing_ok=True)
        raise ImageReadError("image_required")
    try:
        asset = await persist_asset(
            asset_repo,
            fetched.temp_path,
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
            filename=fetched.filename or "image",
            content_type=fetched.content_type,
            size_bytes=fetched.size_bytes,
            source_url=fetched.final_url,
        )
    except Exception:
        fetched.temp_path.unlink(missing_ok=True)
        raise
    return {"kind": "image", "asset": asset_payload(asset)}
