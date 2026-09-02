"""内置工具对外委托层：校验契约后直接执行业务工具 handler，保持旧调用契约不变。"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import ValidationError, validate
from redis.asyncio import Redis

from app.core.config import get_settings
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.schemas import BuiltinToolOutcome
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError


async def _load_shop_context(
    platform_end_user_id: int,
) -> tuple[str | None, str | None]:
    """按 embed 终端用户读取店铺运营平台会话（shop_token / shop_user_id）。

    会话由 shop-agent 会话接口写入 Redis，TTL 跟随店铺系统登录时效；
    未注入或已过期时返回 (None, None)，业务工具按未登录处理。
    """
    settings = get_settings()
    redis = Redis.from_url(settings.celery_broker_url)
    try:
        raw = await redis.get(f"shop-agent:end-user:{platform_end_user_id}")
    finally:
        await redis.aclose()
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    shop_token = data.get("shop_token")
    shop_user_id = data.get("shop_user_id")
    return (
        str(shop_token) if shop_token else None,
        str(shop_user_id) if shop_user_id else None,
    )


async def invoke_builtin_tool(
    builtin_repo,
    asset_repo,
    *,
    tool,
    call: dict,
    platform_id: int,
    agent_id: int,
    conversation_id: int | None,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
    session=None,
) -> BuiltinToolOutcome:
    """旧入口：参数与返回结构不变，直接执行注册表里的业务工具 handler。"""
    definition = get_builtin_tool(tool.name)
    if definition is None or not await builtin_repo.is_enabled(
        platform_id, agent_id, tool.name
    ):
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_not_available"}}
        )
    arguments = call.get("args", {})
    try:
        validate(instance=arguments, schema=definition.input_schema)
    except ValidationError:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "invalid_arguments"}}
        )
    if conversation_id is None:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "conversation_required"}}
        )

    handler = definition.executor
    if handler is None:
        # ask_user 等网关直连工具不会走到这里，防御性兜底
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_not_available"}}
        )
    shop_token = None
    shop_user_id = None
    if platform_end_user_id is not None:
        shop_token, shop_user_id = await _load_shop_context(platform_end_user_id)
    ctx = BusinessToolContext(
        platform_id=platform_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
        session=session,
        asset_repo=asset_repo,
        shop_token=shop_token,
        shop_user_id=shop_user_id,
    )
    try:
        result = await handler(arguments, ctx)
    except BusinessToolError as exc:
        error: dict[str, Any] = {"code": exc.code}
        if exc.message:
            error["message"] = exc.message
        if exc.status_code is not None:
            error["status_code"] = exc.status_code
        return BuiltinToolOutcome(status="failed", result={"error": error})
    except Exception:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_failed"}}
        )
    return BuiltinToolOutcome(status="completed", result=result)
