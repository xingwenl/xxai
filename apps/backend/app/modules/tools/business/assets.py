"""业务层共享：资产持久化与结果包装（业务层唯一落库点）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.modules.asset.services import persist_asset


def asset_payload(asset) -> dict:
    return {
        "asset_id": asset.asset_id,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "download_url": f"/api/v1/assets/{asset.asset_id}",
    }


async def persist_fetched_asset(result: dict, ctx, *, source_url: str) -> dict | None:
    """下载类结果：文件类内容持久化为会话受保护资源；纯文本/JSON 返回 None。"""
    temp_path = result.get("temp_path")
    if not temp_path:
        return None
    path = Path(temp_path)
    try:
        asset = await persist_asset(
            ctx.asset_repo,
            path,
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            platform_end_user_id=ctx.platform_end_user_id,
            filename=result.get("filename") or "download",
            content_type=result.get("content_type", "application/octet-stream"),
            size_bytes=result.get("size_bytes", 0),
            source_url=source_url,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return asset_payload(asset)


async def persist_generated_image(payload: bytes, ctx, *, filename: str) -> dict:
    """生成类结果：图片字节落库为会话受保护资源。"""
    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix="image-generate-", suffix=".png", dir=temp_dir
    )
    os.close(fd)
    path = Path(raw_path)
    path.write_bytes(payload)
    try:
        asset = await persist_asset(
            ctx.asset_repo,
            path,
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            platform_end_user_id=ctx.platform_end_user_id,
            filename=filename,
            content_type="image/png",
            size_bytes=len(payload),
            source_url="openai://images",
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return asset_payload(asset)
