"""image_generate 业务工具：调基本工具生成图片，结果持久化后返回受保护资源。"""

from __future__ import annotations

import base64
from uuid import uuid4

from app.core.config import get_settings
from app.modules.model_registry.resolver import resolve_agent_model
from app.modules.tools.basic.framework import BasicToolError
from app.modules.tools.basic.registry import get_basic_tool
from app.modules.tools.business.assets import persist_generated_image
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)


@business_tool(
    name="image_generate",
    description=(
        "使用后端配置的图片模型生成图片，返回受保护图片资源列表。"
        "用法：prompt 必填，用自然语言描述要生成的图片；"
        "model、size、quality、n 可选，不填使用后端默认配置，n 为一次生成数量（1-4）。"
        "结果使用：result.assets 为图片资源数组，每个元素含 asset_id 与 download_url；"
        "展示图片必须用 download_url 作为 Markdown 图片地址"
        "（如 ![图片描述](/api/v1/assets/{asset_id})），严禁把 asset_id 直接当作图片地址。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": "图片生成提示词",
            },
            "model": {
                "type": "string",
                "enum": ["gpt-image-1", "dall-e-3"],
                "description": "图片模型，可选",
            },
            "size": {
                "type": "string",
                "enum": [
                    "1024x1024",
                    "1536x1024",
                    "1024x1536",
                    "1792x1024",
                    "1024x1792",
                ],
                "description": "图片尺寸，可选",
            },
            "quality": {
                "type": "string",
                "enum": ["auto", "low", "medium", "high", "standard"],
                "description": "图片质量，可选",
            },
            "n": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4,
                "description": "生成数量，可选",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
    depends_on=("image_gen.generate",),
)
async def image_generate_business(args: dict, ctx: BusinessToolContext) -> dict:
    settings = get_settings()
    model_config = await resolve_agent_model(
        ctx.session,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        role="image_generate",
    )
    api_key = model_config.api_key if model_config else settings.openai_api_key
    tool = get_basic_tool("image_gen.generate")
    try:
        out = await tool.handler(
            {
                "prompt": args["prompt"],
                "model": {
                    "model_name": (
                        model_config.model_name
                        if model_config
                        else settings.openai_image_model
                    ),
                    "base_url": (
                        (model_config.base_url if model_config else None)
                        or settings.openai_base_url
                    ),
                    "api_key": api_key,
                    "options": model_config.options if model_config else {},
                },
                "size": args.get("size"),
                "quality": args.get("quality"),
                "n": args.get("n"),
                "timeout_seconds": settings.image_generation_timeout_seconds,
                "max_count": settings.image_max_count,
                "max_bytes": settings.image_max_bytes,
            }
        )
    except BasicToolError as exc:
        raise BusinessToolError(exc.code) from exc
    assets = []
    for index, item in enumerate(out["images"]):
        payload = base64.b64decode(item["b64"])
        filename = f"generated-{uuid4().hex[:8]}-{index + 1}.png"
        assets.append(await persist_generated_image(payload, ctx, filename=filename))
    return {"kind": "image", "assets": assets}
