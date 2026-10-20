"""内置工具对外委托层：校验契约后直接执行业务工具 handler，保持旧调用契约不变。

审批闸口就在这一层：它是**所有**内置工具调用的必经之路（REST 分派、无人值守
任务、网关 WS 都经此执行）。闸口放在契约校验之后，避免为一次参数非法的调用
弹确认卡；放在 handler 之前，保证未获批准时 handler 一次都不会被调用。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from jsonschema import ValidationError, validate
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.schemas import BuiltinToolOutcome
from app.modules.memory.services import SELF_SCOPED_WRITE_TOOLS
from app.modules.tool_approval.contracts import (
    REJECTED_BY_POLICY,
    ConfirmationDecision,
    no_channel_decision,
)
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.tools.side_effects import coerce_side_effect


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
    loop_run_id: int | None = None,
    confirmation_decider=None,
    unattended: bool = False,
) -> BuiltinToolOutcome:
    """旧入口：参数与返回结构不变，直接执行注册表里的业务工具 handler。

    新增的 ``confirmation_decider`` 只在工具有副作用时被调用（``side_effect``
    非 none）。未传时不是「放行」而是「拒绝」：这代表当前通路没有任何可以问
    用户的入口（REST 流式对话、微信助手、交互式运行的委派子运行）。
    """
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

    # 审批闸口：只对声明有副作用的工具生效（none/navigation 直接执行）。
    # 以注册表定义为准，而不是运行时传进来的 tool 对象，避免旁路。
    side_effect = coerce_side_effect(getattr(definition, "side_effect", "none"))

    # 白名单直通：用户记忆的读写只作用于**当前用户本人**（读的是自己的记忆，
    # 写的是自己的记忆，不改变任何他人可见的状态），交互会话里为它弹确认卡
    # 只会让「记一下我的城市」多一步无意义的点击。代价是模型可能在用户没要求
    # 时写入，因此配套三件事：写入有白名单与敏感类别限制、写后回显原值、用户
    # 可随时删除。白名单不覆盖无人值守与端用户会话——那两条通路没有在场的人
    # 能看见这件事发生。
    self_scoped_write = (
        side_effect != "none"
        and definition.name in SELF_SCOPED_WRITE_TOOLS
        and not unattended
        and user_id is not None
    )
    if side_effect != "none" and not self_scoped_write:
        decision = await _decide_confirmation(
            confirmation_decider, definition=definition, call=call
        )
        if decision.defer:
            # 裁决器已经把确认记录落库，本次不执行 handler：运行在上层挂起，
            # 由解决端点拿到用户决定后续跑（见 ADR 0010）。
            return _deferred_outcome(definition.name, side_effect, decision)
        if not decision.approved:
            return _rejected_outcome(definition.name, side_effect, decision)

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
        loop_run_id=loop_run_id,
        session=session,
        asset_repo=asset_repo,
        shop_token=shop_token,
        shop_user_id=shop_user_id,
        confirmation_decider=confirmation_decider,
        unattended=unattended,
    )
    # 流式 AgentRuntime 会在独立的模型任务中执行工具；复用 Gateway 正在
    # flush/commit 的 AsyncSession 会触发 asyncpg 的并发操作错误。诊断类
    # runtime_info 只读，因此使用请求级 session 之外的独立连接，保证查询
    # 不与消息/loop 持久化竞争同一个连接。
    if tool.name == "get_runtime_info":
        async with get_session_factory()() as isolated_session:
            ctx = replace(ctx, session=isolated_session)
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
    else:
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
    return _outcome_from_result(result)


async def _decide_confirmation(
    confirmation_decider,
    *,
    definition,
    call: dict,
) -> ConfirmationDecision:
    """执行写工具前征求批准；没有可问的人时按「无确认通道」拒绝。"""

    if confirmation_decider is None:
        return no_channel_decision(definition.name)
    decision = await confirmation_decider(definition, call)
    if decision is None:
        # 裁决器表示「不由本层处理」：本层没有别的确认入口，仍然拒绝而不是放行。
        return no_channel_decision(definition.name)
    return decision


def _rejected_outcome(
    tool_name: str, side_effect: str, decision: ConfirmationDecision
) -> BuiltinToolOutcome:
    """把拒绝裁决包装成工具结果。

    结构与 ``unattended.skipped_result`` 对齐（status/auto_approved/reason/message），
    让模型与落库链路对「被拒绝」只有一种读法。
    """

    return BuiltinToolOutcome(
        status="rejected",
        result={
            "status": "rejected",
            "auto_approved": False,
            "reason": decision.reason or REJECTED_BY_POLICY,
            "side_effect": side_effect,
            "message": decision.message or f"工具 {tool_name} 需要用户确认，本次未执行。",
        },
    )


def _deferred_outcome(
    tool_name: str, side_effect: str, decision: ConfirmationDecision
) -> BuiltinToolOutcome:
    """把「已挂起等待确认」包装成工具结果。

    ``status`` 用 ``confirmation_required``：AgentLoop 见到它就不再请求模型，
    整条运行停在等待态。确认记录的主键与过期时间放在 ``metadata`` 里——它随
    TOOL_COMPLETED 事件流到 SSE 映射层，最终成为确认卡上的 ``confirmationId``
    与 ``expiresAt``（``result`` 里的同名字段是给模型看的摘要，两者用途不同）。
    """

    payload = _confirmation_payload(decision)
    return BuiltinToolOutcome(
        status="confirmation_required",
        confirmation_id=payload.get("confirmation_id"),
        result={
            "status": "confirmation_required",
            "side_effect": side_effect,
            "message": decision.message
            or f"工具 {tool_name} 需要用户确认，已暂停等待你的决定。",
            **{key: value for key, value in payload.items() if value is not None},
        },
        metadata={
            "side_effect": side_effect,
            "expires_at": payload.get("expires_at"),
            "confirmation_id": payload.get("confirmation_id"),
        },
    )


def _confirmation_payload(decision: ConfirmationDecision) -> dict[str, Any]:
    """取出裁决器挂在 ``message`` 之外的结构化结果。

    交互式裁决器（``conversation/approval.py``）把确认记录主键与过期时间放在
    ``decision.details`` 里；无人值守裁决器不产生挂起，因此这里允许为空。
    """

    details = getattr(decision, "details", None)
    if isinstance(details, dict):
        return dict(details)
    return {}


def _outcome_from_result(result: Any) -> BuiltinToolOutcome:
    """把 handler 结果包装成统一 outcome，并摘出保留键 ``_metadata``。

    ``_metadata`` 是工具与落库链路之间的私有通道（目前只用于回传派生子运行的
    ID），必须在这里摘掉：否则它会随 result 一起被摘要回填给模型。
    """
    if isinstance(result, dict) and isinstance(result.get("_metadata"), dict):
        payload = dict(result)
        metadata = payload.pop("_metadata")
        return BuiltinToolOutcome(status="completed", result=payload, metadata=metadata)
    return BuiltinToolOutcome(status="completed", result=result)
