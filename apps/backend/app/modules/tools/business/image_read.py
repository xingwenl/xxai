"""image_read 业务工具：解析图片来源 -> 调 vision.describe -> 包装结果。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.modules.asset.services import persist_asset, resolve_asset_path
from app.modules.model_registry.resolver import resolve_agent_model
from app.modules.tools.basic.framework import BasicToolError
from app.modules.tools.basic.registry import get_basic_tool
from app.modules.tools.business.assets import asset_payload
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)


async def _resolve_asset(args: dict, ctx: BusinessToolContext):
    """解析图片来源：asset_id 查库取文件，或 url 下载并持久化。"""
    asset_id = args.get("asset_id")
    if asset_id:
        if ctx.user_id is not None:
            asset = await ctx.asset_repo.get_for_user_conversation(
                asset_id, ctx.user_id, ctx.conversation_id
            )
        else:
            asset = await ctx.asset_repo.get_for_embed_conversation(
                asset_id,
                platform_id=ctx.platform_id,
                agent_id=ctx.agent_id,
                end_user_id=ctx.platform_end_user_id,
                conversation_id=ctx.conversation_id,
            )
        if asset is None or not asset.content_type.startswith("image/"):
            raise BusinessToolError("asset_not_found")
        return asset, str(resolve_asset_path(asset.storage_key)), asset.content_type

    settings = get_settings()
    temp_dir = Path(settings.agent_file_storage_path) / "assets" / ".tmp"
    tool = get_basic_tool("http.get")
    try:
        fetched = await tool.handler(
            {
                "url": args["url"],
                "temp_dir": str(temp_dir),
                "total_timeout_seconds": settings.builtin_http_get_timeout_seconds,
                "text_max_bytes": settings.builtin_http_get_text_max_bytes,
                "text_max_chars": settings.builtin_http_get_text_max_chars,
                "file_max_bytes": settings.image_max_bytes,
            }
        )
    except BasicToolError as exc:
        raise BusinessToolError(exc.code, status_code=exc.status_code) from exc
    temp_path = fetched.get("temp_path")
    if fetched.get("kind") != "image" or not temp_path:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        raise BusinessToolError("image_required")
    try:
        asset = await persist_asset(
            ctx.asset_repo,
            Path(temp_path),
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            platform_end_user_id=ctx.platform_end_user_id,
            filename=fetched.get("filename") or "image",
            content_type=fetched.get("content_type", "image/png"),
            size_bytes=fetched.get("size_bytes", 0),
            source_url=fetched.get("final_url", ""),
        )
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
    return asset, temp_path, fetched.get("content_type", "image/png")


def _build_vision_model_spec(model_config, settings) -> dict | None:
    """模型绑定优先，未绑定回退全局配置；缺密钥或地址时返回 None（跳过描述）。"""
    if model_config is not None:
        spec = {
            "model_name": model_config.model_name,
            "base_url": model_config.base_url,
            "api_key": model_config.api_key,
            "options": model_config.options or {},
        }
    else:
        model_name = settings.read_image_model
        if not model_name:
            return None
        spec = {
            "model_name": model_name,
            "base_url": settings.read_image_base_url or settings.openai_base_url,
            "api_key": settings.read_image_api_key or settings.openai_api_key,
            "options": {},
        }
    if not spec["base_url"] or not spec["api_key"]:
        return None
    return spec


@business_tool(
    name="image_read",
    description=(
        "读取一张图片，返回受保护图片资源（可附带图片内容的文字描述）。"
        "用法：参数二选一——url 传公开图片地址，或 asset_id 传当前会话中已有的图片资源；"
        "必须且只能提供一个，两者都不传或都传会校验失败。"
        "结果使用：result.asset 含 asset_id 与 download_url，"
        "展示图片必须用 download_url 作为 Markdown 图片地址"
        "（如 ![图片描述](/api/v1/assets/{asset_id})），严禁把 asset_id 直接当作图片地址；"
        "result.description 为可选的图片内容描述，可直接引用。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
                "description": "公开 HTTPS 图片地址",
            },
            "asset_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": "当前会话图片资源标识",
            },
        },
        "oneOf": [{"required": ["url"]}, {"required": ["asset_id"]}],
        "additionalProperties": False,
    },
    depends_on=("http.get", "vision.describe"),
)
async def image_read_business(args: dict, ctx: BusinessToolContext) -> dict:
    settings = get_settings()
    model_config = await resolve_agent_model(
        ctx.session,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        role="image_read",
    )
    asset, file_path, content_type = await _resolve_asset(args, ctx)
    description = None
    model_spec = _build_vision_model_spec(model_config, settings)
    if model_spec is not None:
        vision_tool = get_basic_tool("vision.describe")
        try:
            out = await vision_tool.handler(
                {
                    "image": {"file_path": file_path, "content_type": content_type},
                    "model": model_spec,
                    "timeout_seconds": settings.read_image_timeout_seconds,
                }
            )
            description = out.get("description")
        except BasicToolError:
            # 基本工具已输出告警；保持业务行为：描述为空不视为失败
            description = None
    return {
        "kind": "image",
        "asset": asset_payload(asset),
        "description": description,
    }
