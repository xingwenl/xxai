from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.asset.services import persist_asset
from app.modules.model_registry.resolver import ResolvedModel

logger = get_logger(__name__)


class ImageGenerationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def generate_images(
    arguments: dict,
    *,
    asset_repo,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
    client=None,
    model_config: ResolvedModel | None = None,
) -> list[dict]:
    settings = get_settings()
    # 绑定注册表模型时优先使用其密钥与地址；未绑定时回退全局配置。
    api_key = model_config.api_key if model_config else settings.openai_api_key
    if not api_key:
        raise ImageGenerationError("image_generation_not_configured")
    count = int(arguments.get("n", 1))
    if count > settings.image_max_count:
        raise ImageGenerationError("image_too_many")
    client = client or AsyncOpenAI(
        api_key=api_key,
        base_url=(model_config.base_url if model_config else None)
        or settings.openai_base_url,
        timeout=settings.image_generation_timeout_seconds,
        max_retries=0,
    )
    default_model = (
        model_config.model_name if model_config else settings.openai_image_model
    )
    model = arguments.get("model") or default_model
    params = {
        "model": model,
        "prompt": arguments["prompt"],
        "size": arguments.get("size", "1024x1024"),
        "quality": arguments.get("quality", "auto"),
        "n": count,
    }
    if model.startswith("dall-e"):
        params["response_format"] = "b64_json"
    try:
        response = await client.images.generate(**params)
    except Exception as exc:
        # 对外仅返回稳定错误码；完整异常写入后端日志，便于区分配置、权限和上游故障。
        logger.exception("OpenAI Images API request failed model=%s", model)
        raise ImageGenerationError("image_generation_failed") from exc

    assets: list[dict] = []
    for index, item in enumerate(getattr(response, "data", None) or []):
        encoded = getattr(item, "b64_json", None)
        if not encoded:
            logger.warning("OpenAI Images API returned no b64_json model=%s", model)
            raise ImageGenerationError("image_generation_failed")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            logger.warning(
                "OpenAI Images API returned invalid image data model=%s", model
            )
            raise ImageGenerationError("image_generation_failed") from exc
        if len(payload) > settings.image_max_bytes:
            raise ImageGenerationError("image_too_large")
        temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
        asset = await _write_asset(
            payload,
            temp_dir=temp_dir,
            asset_repo=asset_repo,
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
            index=index,
        )
        assets.append(_asset_payload(asset, len(payload)))
    if not assets:
        logger.warning("OpenAI Images API returned no image assets model=%s", model)
        raise ImageGenerationError("image_generation_failed")
    return assets


async def _write_asset(
    payload: bytes,
    *,
    temp_dir: Path,
    asset_repo,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
    index: int,
):
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix="image-generate-", suffix=".png", dir=temp_dir
    )
    os.close(fd)
    path = Path(raw_path)
    path.write_bytes(payload)
    try:
        return await persist_asset(
            asset_repo,
            path,
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
            filename=f"generated-{uuid4().hex[:8]}-{index + 1}.png",
            content_type="image/png",
            size_bytes=len(payload),
            source_url="openai://images",
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _asset_payload(asset, size_bytes: int) -> dict:
    return {
        "asset_id": asset.asset_id,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "size_bytes": size_bytes,
        "download_url": f"/api/v1/assets/{asset.asset_id}",
    }
