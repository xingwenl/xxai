"""image_gen.generate 基本工具：调用图片生成模型，返回生成的图片数据。

单一职责：只负责「生成」；不落库、不鉴权，持久化由上层业务工具完成。
"""

from __future__ import annotations

import base64
import binascii

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.agent.provider_headers import merge_default_headers
from app.modules.tools.basic.framework import BasicToolError, basic_tool

logger = get_logger(__name__)


@basic_tool(
    name="image_gen.generate",
    description="调用图片生成模型，返回 base64 图片数据",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "minLength": 1},
            "model": {
                "type": "object",
                "properties": {
                    "model_name": {"type": "string"},
                    "base_url": {"type": ["string", "null"]},
                    "api_key": {"type": ["string", "null"]},
                    "options": {"type": "object"},
                },
            },
            "size": {"type": "string"},
            "quality": {"type": "string"},
            "n": {"type": "integer"},
            "timeout_seconds": {"type": "number"},
            "max_count": {"type": "integer"},
            "max_bytes": {"type": "integer"},
        },
        "required": ["prompt", "model"],
        "additionalProperties": False,
    },
    side_effect="create",
)
async def generate_images(inputs: dict) -> dict:
    """输入 {prompt, model, size?, quality?, n?} → {images: [{b64, size_bytes}]}。"""
    settings = get_settings()
    model = inputs["model"]
    api_key = model.get("api_key")
    if not api_key:
        raise BasicToolError("image_generation_not_configured")
    count = int(inputs.get("n") or 1)
    max_count = int(inputs.get("max_count", settings.image_max_count))
    if count > max_count:
        raise BasicToolError("image_too_many")
    model_name = model.get("model_name") or settings.openai_image_model
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=model.get("base_url"),
        timeout=float(
            inputs.get("timeout_seconds", settings.image_generation_timeout_seconds)
        ),
        max_retries=0,
        # 生图链路同样没有会话上下文，只补客户端标识与自有 UA。
        default_headers=merge_default_headers(
            model.get("base_url"),
            (model.get("options") or {}).get("default_headers"),
        ),
    )
    params = {
        "model": model_name,
        "prompt": inputs["prompt"],
        "size": inputs.get("size", "1024x1024"),
        "quality": inputs.get("quality", "auto"),
        "n": count,
    }
    if model_name.startswith("dall-e"):
        params["response_format"] = "b64_json"
    try:
        response = await client.images.generate(**params)
    except Exception as exc:
        logger.exception("OpenAI Images API request failed model=%s", model_name)
        raise BasicToolError("image_generation_failed") from exc

    images: list[dict] = []
    max_bytes = int(inputs.get("max_bytes", settings.image_max_bytes))
    for item in getattr(response, "data", None) or []:
        encoded = getattr(item, "b64_json", None)
        if not encoded:
            logger.warning(
                "OpenAI Images API returned no b64_json model=%s", model_name
            )
            raise BasicToolError("image_generation_failed")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            logger.warning(
                "OpenAI Images API returned invalid image data model=%s", model_name
            )
            raise BasicToolError("image_generation_failed") from exc
        if len(payload) > max_bytes:
            raise BasicToolError("image_too_large")
        images.append({"b64": encoded, "size_bytes": len(payload)})
    if not images:
        logger.warning(
            "OpenAI Images API returned no image assets model=%s", model_name
        )
        raise BasicToolError("image_generation_failed")
    return {"images": images}
