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
    description="使用后端配置的图片模型生成图片，并返回可展示的受保护图片资源",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "minLength": 1},
            "model": {"type": "string"},
            "size": {"type": "string"},
            "quality": {"type": "string"},
            "n": {"type": "integer", "minimum": 1, "maximum": 4},
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
