from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

from app.core.config import get_settings
from app.modules.asset.services import persist_asset, resolve_asset_path
from app.modules.builtin_tool.http_get import HttpGetError, fetch_http_get
from app.modules.model_registry.resolver import ResolvedModel

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


async def _describe_image(
    asset, model_config: ResolvedModel | None = None
) -> str | None:
    """配置视觉模型时生成图片文字描述；未配置或调用失败返回 None。

    绑定 ``image_read`` 注册表模型时优先使用其配置，未绑定时回退
    全局 ``READ_IMAGE_*`` 与 ``OPENAI_*`` 配置。
    """
    settings = get_settings()
    if model_config is not None:
        model_name = model_config.model_name
        base_url = model_config.base_url
        api_key = model_config.api_key
    else:
        model_name = settings.read_image_model
        base_url = settings.read_image_base_url
        api_key = settings.read_image_api_key
    if not model_name:
        return None
    if not (base_url or settings.openai_base_url):
        return None
    if not (api_key or settings.openai_api_key):
        return None
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        path = resolve_asset_path(asset.storage_key)
        data = await asyncio.to_thread(path.read_bytes)
        data_url = (
            f"data:{asset.content_type};base64,{base64.b64encode(data).decode('ascii')}"
        )
        model = ChatOpenAI(
            model=model_name,
            base_url=base_url or settings.openai_base_url,
            api_key=api_key or settings.openai_api_key,
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
        detail = str(exc)
        if "model_dump" in detail:
            detail = (
                "上游返回非 JSON 响应（检查模型 base_url 是否以 /v1 结尾、"
                f"模型是否支持图片输入）: {detail}"
            )
        logger.warning(
            "read image description failed asset_id=%s: %s",
            getattr(asset, "asset_id", None),
            detail,
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
    model_config: ResolvedModel | None = None,
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
            "description": await _describe_image(asset, model_config),
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
        "description": await _describe_image(asset, model_config),
    }
