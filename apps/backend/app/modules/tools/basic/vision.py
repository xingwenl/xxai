"""vision.describe 基本工具：用指定模型描述一张图片。

单一职责：只做「读图 -> 描述」；图片来源（file/base64/url）由调用方给出，
模型配置（model）也由调用方传入，本工具不做绑定解析与回退决策。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from pathlib import Path

from app.modules.agent.provider_headers import merge_default_headers
from app.modules.tools.basic.framework import BasicToolError, basic_tool

logger = logging.getLogger(__name__)

_SUFFIX_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _guess_content_type(path: Path) -> str:
    return _SUFFIX_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


async def _resolve_image_url(image: dict) -> str:
    """把 image 输入归一化为可直接给模型的图片 URL（本地内容转 data URL）。"""
    if "file_path" in image:
        path = Path(image["file_path"])
        data = await asyncio.to_thread(path.read_bytes)
        content_type = image.get("content_type") or _guess_content_type(path)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    if "base64" in image:
        try:
            data = base64.b64decode(image["base64"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise BasicToolError("invalid_image") from exc
        content_type = image.get("content_type") or "image/png"
        return f"data:{content_type};base64,{image['base64']}"
    if "url" in image:
        return image["url"]
    raise BasicToolError("invalid_image")


@basic_tool(
    name="vision.describe",
    description="用指定视觉模型描述图片：url / base64 / file_path 三选一",
    input_schema={
        "type": "object",
        "properties": {
            "image": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "base64": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content_type": {"type": "string"},
                },
                "oneOf": [
                    {"required": ["url"]},
                    {"required": ["base64"]},
                    {"required": ["file_path"]},
                ],
            },
            "model": {
                "type": "object",
                "properties": {
                    "model_name": {"type": "string"},
                    "base_url": {"type": ["string", "null"]},
                    "api_key": {"type": ["string", "null"]},
                    "options": {"type": "object"},
                },
                "required": ["model_name"],
            },
            "timeout_seconds": {"type": "number"},
        },
        "required": ["image", "model"],
        "additionalProperties": False,
    },
    side_effect="none",
)
async def describe_image(inputs: dict) -> dict:
    """输入 {image: {file_path|base64|url}, model, timeout_seconds?} → {description}。"""
    model = inputs["model"]
    model_name = model.get("model_name")
    if not model_name:
        raise BasicToolError("model_not_configured")
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        image_url = await _resolve_image_url(inputs["image"])
        chat = ChatOpenAI(
            model=model_name,
            base_url=model.get("base_url"),
            api_key=model.get("api_key"),
            timeout=float(inputs.get("timeout_seconds", 60)),
            max_retries=0,
            # 读图链路没有会话上下文，只补客户端标识与自有 UA；OpenCode 端点
            # 之外返回 None，不改变既有请求头。
            default_headers=merge_default_headers(
                model.get("base_url"),
                (model.get("options") or {}).get("default_headers"),
            ),
        )
        response = await chat.ainvoke(
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
                            "image_url": {"url": image_url},
                        },
                    ]
                )
            ]
        )
        text = getattr(response, "content", "") or ""
        return {"description": str(text)[:2000]}
    except BasicToolError:
        raise
    except Exception as exc:
        detail = str(exc)
        if "model_dump" in detail:
            detail = (
                "上游返回非 JSON 响应（检查模型 base_url 是否以 /v1 结尾、"
                f"模型是否支持图片输入）: {detail}"
            )
        logger.warning("vision.describe failed: %s", detail)
        raise BasicToolError("vision_call_failed", detail) from exc
