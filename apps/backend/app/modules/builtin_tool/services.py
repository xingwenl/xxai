"""内置工具对外委托层：校验后委托给业务工具注册表，保持旧调用契约不变。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.schemas import BuiltinToolOutcome
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.tools.business.registry import get_business_tool


@dataclass(frozen=True)
class BuiltinToolContext:
    """一次内置工具调用共享的执行上下文（兼容旧入口签名）。"""

    asset_repo: Any
    platform_id: int
    agent_id: int
    conversation_id: int
    user_id: int | None = None
    platform_end_user_id: int | None = None
    session: Any | None = None


_ToolHandler = Callable[[dict, BuiltinToolContext], Awaitable[BuiltinToolOutcome]]


def _delegate(
    executor: str,
) -> Callable[[dict, BuiltinToolContext], Awaitable[BuiltinToolOutcome]]:
    """按执行器名委托业务工具注册表（定义与 handler 同页，注册表只做收集）。"""

    async def invoke(arguments: dict, ctx: BuiltinToolContext) -> BuiltinToolOutcome:
        tool = get_business_tool(executor)
        if tool is None:
            return BuiltinToolOutcome(
                status="failed", result={"error": {"code": "tool_not_available"}}
            )
        business_ctx = BusinessToolContext(
            asset_repo=ctx.asset_repo,
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            platform_end_user_id=ctx.platform_end_user_id,
            session=ctx.session,
        )
        try:
            result = await tool.handler(arguments, business_ctx)
        except BusinessToolError as exc:
            error: dict[str, Any] = {"code": exc.code}
            if exc.status_code is not None:
                error["status_code"] = exc.status_code
            return BuiltinToolOutcome(status="failed", result={"error": error})
        except Exception:
            return BuiltinToolOutcome(
                status="failed", result={"error": {"code": "tool_failed"}}
            )
        return BuiltinToolOutcome(status="completed", result=result)

    return invoke


# 执行器委托表：key 与 registry 中 BuiltinToolDefinition.executor 一一对应；
# 新增内置工具 = 在 business 目录新增一个文件（公共注册页收集）+ 在此追加一行。
_TOOL_HANDLERS: dict[str, _ToolHandler] = {
    "http_get": _delegate("http_get"),
    "http_post": _delegate("http_post"),
    "image_generate": _delegate("image_generate"),
    "image_read": _delegate("image_read"),
}


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
    """旧入口：参数与返回结构不变，实现委托给业务工具注册表。"""
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

    handler = _TOOL_HANDLERS.get(definition.executor)
    if handler is None:
        return BuiltinToolOutcome(
            status="failed", result={"error": {"code": "tool_not_available"}}
        )
    ctx = BuiltinToolContext(
        asset_repo=asset_repo,
        platform_id=platform_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
        session=session,
    )
    return await handler(arguments, ctx)
