from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

from app.core.config import get_settings
from app.modules.asset.services import persist_asset, resolve_asset_path
from app.modules.builtin_tool.http_get import HttpGetError, fetch_http_get

logger = logging.getLogger(__name__)


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


async def _describe_image(asset) -> str | None:
    """配置视觉模型时生成图片文字描述；未配置或调用失败返回 None。"""
    settings = get_settings()
    if not settings.read_image_model:
        return None
    if not (settings.read_image_base_url or settings.openai_base_url):
        return None
    if not (settings.read_image_api_key or settings.openai_api_key):
        return None
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        path = resolve_asset_path(asset.storage_key)
        data = await asyncio.to_thread(path.read_bytes)
        data_url = (
            f"data:{asset.content_type};base64,"
            f"{base64.b64encode(data).decode('ascii')}"
        )
        model = ChatOpenAI(
            model=settings.read_image_model,
            base_url=settings.read_image_base_url or settings.openai_base_url,
            api_key=settings.read_image_api_key or settings.openai_api_key,
            timeout=settings.read_image_timeout_seconds,
            max_retries=0,
        )
        response = await model.ainvoke(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                "请用中文详细描述这张图片的内容、"
                                "可辨识的文字和关键信息。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ]
                )
            ]
        )
        text = getattr(response, "content", "") or ""
        return str(text)[:2000]
    except Exception as exc:
        logger.warning(
            "read image description failed asset_id=%s: %s",
            getattr(asset, "asset_id", None),
            exc,
        )
        return None


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
        return {
            "kind": "image",
            "asset": asset_payload(asset),
            "description": await _describe_image(asset),
        }

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
    return {
        "kind": "image",
        "asset": asset_payload(asset),
        "description": await _describe_image(asset),
    }
