"""Embed Agent 的 WebSocket 网关。

一条连接的主流程是：协议协商 -> token 认证 -> 事件恢复 -> 页面工具注册 ->
接收用户消息 -> 调用模型 -> 等待页面工具结果 -> 回传最终回答。网关同时负责
连接级 requestId 幂等、宿主工具 callId 审计和 Redis 事件重放。
"""

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    build_agent_error_payload,
    load_runtime_context,
)
from app.modules.conversation.services import retrieve_citations
from app.modules.embed.repositories import EmbedRepository
from app.modules.gateway.runtime import (
    RequestRegistry,
    filter_conflicting_runtime_tools,
    stream_embed_chat,
)
from app.modules.gateway.replay import ReplayStore
from app.modules.gateway.auth import (
    CAPABILITIES,
    MINIMUM_SDK_VERSION,
    SERVER_VERSION,
    PROTOCOL_SUBPROTOCOL,
    authenticate_embed_token,
    check_client_compatibility,
)
from app.modules.gateway.connection import (
    normalize_conversation_id,
    validate_incoming_message,
)
from app.modules.gateway.schemas import AttachmentRef
from app.modules.observability.metrics import (
    record_authentication,
    record_connection,
    record_error,
    record_message,
    record_quota_rejection,
)
from app.modules.quota.service import (
    QuotaDimensions,
    QuotaService,
    RedisQuotaStore,
)
from app.modules.skill.repositories import SkillRepository
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    build_temporary_host_tool_policy,
    canonical_fingerprint,
    redact_sensitive,
    validate_registration,
)
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.gateway.dispatcher import RuntimeToolDispatcher
from app.modules.gateway.events import build_error, event_to_protocol_payload
from app.modules.agent_runtime.errors import cancellation_error
from app.modules.agent_runtime.runtime import cancel_and_join_tasks
from app.modules.agent_runtime.adapters import tool_call_from_legacy
from app.modules.agent_runtime.tools import ToolDispatcher
from app.modules.agent_runtime.composition import build_runtime_tools
from app.shared.exceptions import UnauthorizedException

router = APIRouter()
logger = get_logger(__name__)


async def _send_protocol_error(
    websocket: WebSocket,
    envelope,
    *,
    code: str,
    message: str,
    retryable: bool,
    request_id: str | None = None,
    details: dict[str, str] | None = None,
) -> None:
    """发送协议错误事件，统一错误 payload 结构与关联 ID。"""
    payload: dict = {"code": code, "message": message, "retryable": retryable}
    if details is not None:
        payload["details"] = details
    await websocket.send_text(envelope("error", payload, request_id=request_id))


def _numeric_sequence_floor(value: object) -> int:
    """把重放的 ``latestSequence`` 归一到可安全参与 max 计算的整数。

    正常路径返回的是协议序号；旧客户端用 Redis Stream ID（形如
    ``1789749522980-0``）作游标时，重放会原样返回 stream ID。此处直接
    ``int()`` 会抛 ``ValueError`` 并让整个连接在建连阶段失败，因此非数字值
    降级为 0 并留下告警日志，供排查「连接建不起来」类问题。
    """

    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            logger.warning(
                "Replay latest sequence is not numeric, fallback to 0: value=%s",
                value,
            )
    return 0


def _cancel_pending_request_futures(
    *future_maps: dict[str, asyncio.Future],
) -> None:
    """取消请求取消后仍在等待外部输入的 Future。

    模型 Task 被取消并不一定会自动清理连接级 Future；如果不主动处理，迟到的
    页面回调可能唤醒一个已经不存在的请求，Future 也会一直占用内存直到连接
    关闭。当前连接对请求串行执行，因此这里可以安全清理全部待处理 Future。
    """

    for futures in future_maps:
        for future in futures.values():
            if not future.done():
                future.cancel()
        futures.clear()

async def _handle_host_tools_register(
    *,
    websocket: WebSocket,
    envelope,
    message: dict,
    payload: dict,
    agent_id: int,
    host_tool_repo: HostToolRepository,
    registered_host_tools: set[str],
    registered_host_policies: dict[str, object],
) -> None:
    """处理页面宿主工具注册，仅采纳 token 与后台策略都允许的能力。"""
    # 页面提交的只是候选能力，最终可用集合必须是：
    # token claim ∩ Agent 后台绑定 ∩ 当前页面注册，并且 Schema 完全一致。
    registrations = message.get("payload", {}).get("tools", [])
    if not isinstance(registrations, list):
        await _send_protocol_error(
            websocket,
            envelope,
            code="invalid_host_tools",
            message="tools must be a list",
            retryable=False,
        )
        return
    token_names = set(payload.get("host_tools", []))
    if payload.get("temporary_tools") is True:
        for item in registrations:
            try:
                policy = build_temporary_host_tool_policy(item)
            except ValueError as exc:
                logger.warning(
                    "Temporary host tool registration rejected: reason=%s",
                    str(exc),
                )
                continue
            registered_host_tools.add(policy.name)
            registered_host_policies[policy.name] = policy
        logger.warning(
            "Temporary host tools enabled for connection: %s",
            sorted(registered_host_tools),
        )
        return
    agent_names = await host_tool_repo.list_agent_tool_names(
        int(payload["platform_id"]), agent_id
    )
    names = {
        item.get("name")
        for item in registrations
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    allowed = allowed_host_tool_names(
        token_names=token_names,
        agent_names=agent_names,
        registered_names=names,
    )
    policies = await host_tool_repo.list_authorized_policies(
        int(payload["platform_id"]), agent_id, allowed
    )
    logger.info(
        "Host tool registration: token=%s agent=%s registered=%s allowed=%s",
        sorted(token_names),
        sorted(agent_names),
        sorted(names),
        sorted(allowed),
    )
    by_name = {item.name: item for item in policies}
    for item in registrations:
        if not isinstance(item, dict) or item.get("name") not in by_name:
            if isinstance(item, dict):
                logger.warning(
                    "Host tool registration skipped: name=%s policy_found=%s",
                    item.get("name"),
                    item.get("name") in by_name,
                )
            continue
        try:
            validate_registration(by_name[item["name"]], item)
        except ValueError as exc:
            policy = by_name[item["name"]]
            logger.warning(
                "Host tool registration rejected: name=%s reason=%s policy_schema=%s registration_schema=%s",
                item["name"],
                str(exc),
                policy.schema_fingerprint,
                canonical_fingerprint(
                    item.get("inputSchema") or item.get("input_schema") or {}
                ),
            )
            continue
        registered_host_tools.add(item["name"])
        registered_host_policies[item["name"]] = by_name[item["name"]]
        logger.info(
            "Host tool registration accepted: name=%s schema=%s",
            item["name"],
            by_name[item["name"]].schema_fingerprint,
        )
    logger.info(
        "Host tools active for connection: %s",
        sorted(registered_host_tools),
    )


async def _handle_confirmation_resolve(
    *,
    message: dict,
    payload: dict,
    agent_id: int,
    host_tool_repo: HostToolRepository,
    pending_mcp_confirmations: dict[str, asyncio.Future],
    pending_host_results: dict[str, asyncio.Future],
) -> None:
    """处理页面确认结果，并重新按 token 主体校验审计归属。"""
    # 确认结果必须重新按 token 主体查询审计，不能只信任页面传来的 callId。
    call_id = message.get("payload", {}).get("callId")
    approved = message.get("payload", {}).get("approved")
    if not isinstance(call_id, str) or not isinstance(approved, bool):
        return
    mcp_decision = pending_mcp_confirmations.get(call_id)
    if mcp_decision is not None:
        if not mcp_decision.done():
            mcp_decision.set_result(approved)
        return
    audit = await host_tool_repo.get_call(
        call_id,
        platform_id=int(payload["platform_id"]),
        agent_id=agent_id,
        end_user_id=int(payload["sub"]),
    )
    if audit is not None and audit.status == "awaiting_confirmation":
        await host_tool_repo.transition_call(
            audit, "running" if approved else "rejected"
        )
        logger.info(
            "Host tool confirmation resolved call_id=%s tool=%s approved=%s",
            call_id,
            getattr(audit, "tool_name", None),
            approved,
        )
        if not approved:
            future = pending_host_results.get(call_id)
            if future is not None and not future.done():
                future.set_result({"error": "host_tool_rejected"})
    else:
        logger.warning(
            "Host tool confirmation ignored call_id=%s approved=%s audit_status=%s",
            call_id,
            approved,
            getattr(audit, "status", None),
        )


async def _handle_question_answer(
    *,
    message: dict,
    pending_questions: dict[str, asyncio.Future],
) -> None:
    """处理用户对 AI 问题的答复，唤醒对应挂起的模型循环。

    入站 ``requestId`` 由客户端填成问题 ID（见 SDK ``sendQuestionAnswer``），
    因此这里不能用它反查聊天请求；请求归属由 ``pending_questions`` 的存活
    状态保证：请求结束或取消后容器会被清空，找不到 Future 即为 no-op。
    """
    question_id = message.get("payload", {}).get("questionId")
    if not isinstance(question_id, str):
        return
    future = pending_questions.get(question_id)
    if future is None or future.done():
        return
    # 只接受选项 ID 与自由文本两类答案；两者都缺时视为无效答复。
    answer: dict[str, str] = {}
    selected_option_id = message.get("payload", {}).get("selectedOptionId")
    free_text = message.get("payload", {}).get("freeText")
    if isinstance(selected_option_id, str):
        answer["selectedOptionId"] = selected_option_id
    if isinstance(free_text, str):
        answer["freeText"] = free_text
    if not answer:
        return
    future.set_result(answer)


async def _handle_host_tool_result(
    *,
    message: dict,
    message_type: str,
    payload: dict,
    agent_id: int,
    host_tool_repo: HostToolRepository,
    pending_host_results: dict[str, asyncio.Future],
) -> None:
    """处理页面宿主工具执行结果，仅接受当前主体的 running 状态调用。"""
    # 只接受当前主体下、状态为 running 的调用结果；重复或越权结果会被忽略。
    call_id = message.get("payload", {}).get("callId")
    if not isinstance(call_id, str):
        logger.warning(
            "Host tool result ignored reason=missing_call_id message_type=%s",
            message_type,
        )
        return
    # 等待中的 Future 是"该调用仍属于当前请求"的唯一权威信号：请求结束或
    # 取消后容器会被清空、Future 会被取消，此时迟到的结果必须整体 no-op，
    # 不能改写已经不属于当前请求的审计行。入站 requestId 由客户端填成
    # callId（见 SDK sendHostToolResult），不能用于反查聊天请求。
    future = pending_host_results.get(call_id)
    if future is None or future.done():
        # 迟到结果不能改写审计，但必须留痕：页面在请求结束后才回传时，
        # 只看到“执行失败”而没有任何服务端记录会极难定位。
        # 同时打印当前连接仍在等待的 callId：如果 keys 里是另一个 callId，
        # 说明页面回传的 callId 与下发的不一致；如果 keys 为空，说明请求已经
        # 结束（超时/异常/取消）并释放了 Future，属于迟到结果。
        logger.warning(
            "Host tool result ignored reason=no_pending_future call_id=%s message_type=%s future_found=%s future_done=%s pending_keys=%s",
            call_id,
            message_type,
            future is not None,
            bool(future is not None and future.done()),
            sorted(pending_host_results),
        )
        return
    audit = await host_tool_repo.get_call(
        call_id,
        platform_id=int(payload["platform_id"]),
        agent_id=agent_id,
        end_user_id=int(payload["sub"]),
    )
    if audit is None or audit.status != "running":
        logger.warning(
            "Host tool result ignored reason=audit_not_running call_id=%s message_type=%s audit_status=%s",
            call_id,
            message_type,
            getattr(audit, "status", None),
        )
        return
    if message_type == "host_tool_result":
        result = redact_sensitive(message.get("payload", {}).get("result"))
        result_size = len(json.dumps(result, ensure_ascii=False, default=str))
        if result_size > 32 * 1024:
            logger.warning(
                "Host tool result too large call_id=%s tool=%s result_bytes=%s limit=%s",
                call_id,
                getattr(audit, "tool_name", None),
                result_size,
                32 * 1024,
            )
            await host_tool_repo.transition_call(
                audit, "failed", error="host_tool_result_too_large"
            )
        else:
            logger.info(
                "Host tool result received call_id=%s tool=%s result_bytes=%s",
                call_id,
                getattr(audit, "tool_name", None),
                result_size,
            )
            await host_tool_repo.transition_call(
                audit, "succeeded", result=result
            )
            future.set_result(result)
    else:
        code = str(message.get("payload", {}).get("code", "host_tool_failed"))
        message_text = str(
            message.get("payload", {}).get("message", "host tool failed")
        )
        # 页面执行失败（如 page_unavailable / page_tool_budget_exceeded /
        # host_tool_result_too_large）只有这一行日志能还原，前端展示统一是
        # “执行失败”，因此这里必须把错误码和原因完整写出来。
        logger.warning(
            "Host tool error received call_id=%s tool=%s code=%s message=%s",
            call_id,
            getattr(audit, "tool_name", None),
            code,
            message_text,
        )
        await host_tool_repo.transition_call(
            audit,
            "failed",
            error=message_text,
        )
        future.set_result(
            {"error": "host_tool_failed", "code": code, "message": message_text}
        )


async def _handle_message_send(
    *,
    websocket: WebSocket,
    envelope,
    message: dict,
    request_id: object,
    payload: dict,
    agent_id: int,
    quota_service,
    registry: RequestRegistry,
    active_task: asyncio.Task | None,
    active_request: str | None,
    event_queue: asyncio.Queue,
    pending_mcp_confirmations: dict[str, asyncio.Future],
    pending_host_results: dict[str, asyncio.Future],
    pending_questions: dict[str, asyncio.Future],
    host_tool_repo: HostToolRepository,
    registered_host_tools: set[str],
    registered_host_policies: dict[str, object],
) -> tuple[str | None, asyncio.Task | None]:
    """启动一次聊天请求，返回更新后的活跃请求与任务状态。"""
    record_message("message_send")
    # 同一连接串行处理聊天请求；重复 requestId 做幂等处理，
    # 不同 requestId 在前一个完成前返回 request_in_progress。
    if not isinstance(request_id, str):
        await _send_protocol_error(
            websocket,
            envelope,
            code="request_id_required",
            message="requestId is required",
            retryable=False,
        )
        return active_request, active_task
    if active_task is not None and active_request != request_id:
        await _send_protocol_error(
            websocket,
            envelope,
            code="request_in_progress",
            message="request already running",
            retryable=True,
        )
        return active_request, active_task
    if active_request == request_id:
        return active_request, active_task

    message_payload = message.get("payload", {})
    if not isinstance(message_payload, dict):
        message_payload = {}
    raw_conversation_id = message_payload.get(
        "conversationId", message.get("conversationId")
    )
    try:
        conversation_id = normalize_conversation_id(raw_conversation_id)
    except ValueError:
        await _send_protocol_error(
            websocket,
            envelope,
            code="invalid_conversation_id",
            message="conversationId must be a positive integer",
            retryable=False,
            request_id=request_id,
        )
        return active_request, active_task
    message_payload = {
        **message_payload,
        "conversationId": conversation_id,
    }
    logger.info(
        "Embed message received request_id=%s raw_conversation_id=%s normalized_conversation_id=%s",
        request_id,
        raw_conversation_id,
        conversation_id,
    )
    # 校验 attachments 格式和会话权限
    raw_attachments = message_payload.get("attachments")
    if raw_attachments is not None:
        if not isinstance(raw_attachments, list) or len(raw_attachments) > 10:
            await _send_protocol_error(
                websocket,
                envelope,
                code="invalid_attachments",
                message="附件格式无效或数量超过限制",
                retryable=False,
            )
            return active_request, active_task
        try:
            validated_attachments = [
                AttachmentRef.model_validate(att) for att in raw_attachments
            ]
        except Exception:
            await _send_protocol_error(
                websocket,
                envelope,
                code="invalid_attachments",
                message="附件字段格式无效",
                retryable=False,
            )
            return active_request, active_task
        message_payload["attachments"] = [
            att.model_dump(by_alias=True) for att in validated_attachments
        ]

    if not isinstance(message_payload.get("text"), str):
        await _send_protocol_error(
            websocket,
            envelope,
            code="text_required",
            message="text is required",
            retryable=False,
        )
        return active_request, active_task
    # 思考开关只接受布尔：SDK 侧已归一为布尔，这里拒绝字符串等歧义取值，
    # 避免 "false" 被当作真值而意外开启思考。
    raw_thinking = message_payload.get("thinking")
    if raw_thinking is not None and not isinstance(raw_thinking, bool):
        await _send_protocol_error(
            websocket,
            envelope,
            code="invalid_thinking",
            message="thinking must be a boolean",
            retryable=False,
        )
        return active_request, active_task
    if quota_service is not None:
        decision = await quota_service.check(
            "message",
            QuotaDimensions(
                platform_id=str(payload["platform_id"]),
                client_id=str(payload["client_id"]),
                agent_id=str(agent_id),
                end_user_id=str(payload["sub"]),
            ),
        )
        if not decision.allowed:
            record_quota_rejection("message", decision.code)
            await _send_protocol_error(
                websocket,
                envelope,
                code=decision.code,
                message=(
                    "message quota unavailable"
                    if decision.code == "quota_unavailable"
                    else "message quota exceeded"
                ),
                retryable=decision.retryable,
                details={
                    "retryAfterSeconds": str(decision.retry_after_seconds or 0)
                },
            )
            return active_request, active_task
        model_tokens_decision = await quota_service.peek(
            "model_tokens",
            QuotaDimensions(
                platform_id=str(payload["platform_id"]),
                client_id=str(payload["client_id"]),
                agent_id=str(agent_id),
                end_user_id=str(payload["sub"]),
            ),
        )
        if not model_tokens_decision.allowed:
            record_quota_rejection("model_tokens", model_tokens_decision.code)
            await _send_protocol_error(
                websocket,
                envelope,
                code=model_tokens_decision.code,
                message=(
                    "model token quota unavailable"
                    if model_tokens_decision.code == "quota_unavailable"
                    else "model token quota exceeded"
                ),
                retryable=model_tokens_decision.retryable,
                details={
                    "retryAfterSeconds": str(
                        model_tokens_decision.retry_after_seconds or 0
                    )
                },
            )
            return active_request, active_task
    new_task = asyncio.create_task(
        produce_embed_request(
            request_id=request_id,
            message=message_payload,
            agent_id=agent_id,
            payload=payload,
            event_queue=event_queue,
            pending_mcp_confirmations=pending_mcp_confirmations,
            pending_host_results=pending_host_results,
            pending_questions=pending_questions,
            registered_host_tools=registered_host_tools,
            registered_host_policies=registered_host_policies,
        )
    )
    registry.register(request_id, new_task)
    return request_id, new_task


async def produce_embed_request(
    *,
    request_id: str,
    message: dict,
    agent_id: int,
    payload: dict,
    event_queue: asyncio.Queue,
    pending_mcp_confirmations: dict[str, asyncio.Future],
    pending_host_results: dict[str, asyncio.Future],
    pending_questions: dict[str, asyncio.Future],
    registered_host_tools: set[str],
    registered_host_policies: dict[str, object],
) -> None:
    """执行一次模型请求，并把中间事件放入连接级队列。

    该函数运行在独立 Task 中，并持有请求级与工具两个数据库 Session；
    连接级宿主工具 Session 只由外层 WebSocket 循环使用。模型等待页面
    工具期间，外层 WebSocket 循环仍能处理结果消息并设置对应 Future。
    """
    try:
        # 请求级 Session 只服务本任务内的会话/消息落库；工具执行使用独立的
        # 工具 Session，避免模型 Task 与消费本任务并发操作同一个 AsyncSession。
        async with (
            get_session_factory()() as session,
            get_session_factory()() as tool_session,
        ):
            # 模型 Task 由 runtime 内部启动，必须登记后在 Session 关闭前 join。
            model_tasks: set[asyncio.Task] = set()
            agent_repo = AgentRepository(session)
            skill_repo = SkillRepository(session)
            builtin_tool_repo = BuiltinToolRepository(session)
            context = await load_runtime_context(
                agent_repo,
                KnowledgeRepository(session),
                skill_repo,
                McpRepository(session),
                builtin_tool_repo,
                agent_id=agent_id,
                platform_id=payload["platform_id"],
            )
            citations = await retrieve_citations(
                KnowledgeRepository(session),
                context.knowledge_bases,
                message["text"],
            )
            dispatcher = RuntimeToolDispatcher(
                session=tool_session,
                context=context,
                request_id=request_id,
                agent_id=agent_id,
                platform_id=int(payload["platform_id"]),
                end_user_id=int(payload["sub"]),
                event_queue=event_queue,
                pending_mcp_confirmations=pending_mcp_confirmations,
                pending_host_results=pending_host_results,
                pending_questions=pending_questions,
                host_tool_repo=HostToolRepository(tool_session),
            )
            tool_dispatcher = ToolDispatcher([dispatcher])

            async def invoke_runtime_tool(**kwargs):
                """把旧 Graph 回调桥接到统一 ToolDispatcher。

                MCP 的 server_id 调用没有完整 tool 对象，继续交给原 dispatcher
                的专用分支；其余调用统一经过 ToolCall/ToolExecutor seam。
                """
                if kwargs.get("server_id") is not None:
                    return await dispatcher.invoke(**kwargs)
                tool = kwargs.get("tool")
                call = kwargs.get("call")
                if tool is None or not isinstance(call, dict):
                    return await dispatcher.invoke(**kwargs)
                typed_call = tool_call_from_legacy(call, name=tool.name)
                return await tool_dispatcher.execute(tool, typed_call)

            context.host_tools = [
                registered_host_policies[name]
                for name in registered_host_tools
                if name in registered_host_policies
            ]
            # 关键排障日志：请求开始时连接级已注册/已授权的宿主工具集合，
            # 与后续 "Model tools bound" 行对照即可判断是注册被拒还是未绑定。
            logger.info(
                "Embed request host tools request_id=%s registered=%s bound=%s",
                request_id,
                sorted(registered_host_tools),
                [tool.name for tool in context.host_tools],
            )
            runtime_tools = build_runtime_tools(
                builtin_tools=context.builtin_tools,
                mcp_tools=context.mcp_tools,
                skill_script_tools=context.skill_script_tools,
                skill_instruction_tool=context.skill_instruction_tool,
            )
            runtime_tools = filter_conflicting_runtime_tools(runtime_tools)
            # 模型看到的工具集合再次取自连接级注册状态，未注册工具不会进入 bind_tools。
            logger.info(
                "Starting embed chat request %s runtime_tools=%s host_tools=%s",
                request_id,
                [tool.name for tool in runtime_tools],
                [tool.name for tool in context.host_tools],
            )
            try:
                async for event in stream_embed_chat(
                    ConversationRepository(session),
                    context,
                    # 会话在 stream_embed_chat 内解析后才写入 context，因此延迟求值。
                    model=build_chat_model(
                        context.version,
                        session_id_provider=lambda: getattr(
                            context, "conversation_id", None
                        ),
                        thinking=message.get("thinking")
                        if isinstance(message.get("thinking"), bool)
                        else None,
                    ),
                    platform_id=payload["platform_id"],
                    client_id=str(payload["client_id"]),
                    end_user_id=int(payload["sub"]),
                    message=message["text"],
                    system_prompt=message.get("systemPrompt")
                    if isinstance(message.get("systemPrompt"), str)
                    else None,
                    conversation_id=message.get("conversationId"),
                    request_id=request_id,
                    citations=[item.model_dump() for item in citations],
                    host_tools=context.host_tools,
                    runtime_tools=runtime_tools,
                    invoke_host_tool_fn=invoke_runtime_tool,
                    on_model_task_started=model_tasks.add,
                    attachments=message.get("attachments"),
                ):
                    await event_queue.put(event)
            finally:
                # 无论正常结束、异常还是被取消，都必须在请求级 Session 关闭前
                # 等内层模型 Task 收尾；否则工具写库会与 close() 撞车。
                await cancel_and_join_tasks(model_tasks)
    except asyncio.CancelledError:
        # task.cancel() 不会经过 AgentLoop 的 cancel_event 检查，因此这里补发
        # 同一份稳定错误语义。前端可据此结束发送态，连接层随后仍会完成
        # Future 清理和 request registry 的终态收敛。
        await event_queue.put(
            build_error(
                request_id=request_id,
                payload=cancellation_error().as_payload(),
            )
        )
        raise
    except Exception as exc:
        # 后台 Task 不能静默失败，否则前端会永久停留在发送中；详细堆栈只写服务端日志。
        logger.exception("Embed chat request failed: %s", request_id)
        await event_queue.put(
            build_error(
                request_id=request_id,
                payload=build_agent_error_payload(exc),
            )
        )
        # 让连接层通过 Task.exception() 感知失败，而不是把已经发送 error
        # 事件的任务误判为正常 completed。
        raise
    finally:
        await event_queue.put(None)


async def build_session_info(
    payload: dict,
    *,
    agent_id: int,
    settings,
    quota_service: QuotaService | None,
    session_factory=get_session_factory,
) -> dict:
    """组装 ``session_ready`` 的 client/agent/quota 快照。

    token 认证已验证 client 与 agent 的作用域，这里只做信息读取；任何一段
    读取失败都降级为 ``null``，绝不阻塞连接建立。quota 是当前时间窗口的
    快照，仅供 SDK 展示使用，不参与网关拦截逻辑。
    """
    info: dict = {"client": None, "agent": None, "quota": None}
    try:
        async with session_factory()() as session:
            embed_repo = EmbedRepository(session)
            client = await embed_repo.get_client(
                int(payload["platform_id"]), str(payload["client_id"])
            )
            agent = await AgentRepository(session).get_agent(
                agent_id, int(payload["platform_id"])
            )
            if client is not None:
                info["client"] = {
                    "clientId": client.client_id,
                    "name": client.name,
                    "tokenTtlSeconds": client.token_ttl_seconds,
                    "maxTokensPerMinute": client.max_tokens_per_minute,
                    "maxConnections": client.max_connections,
                }
            if agent is not None:
                info["agent"] = {
                    "agentId": agent.id,
                    "name": agent.name,
                    "slug": agent.slug,
                    "description": agent.description,
                }
            if client is not None and quota_service is not None:
                info["quota"] = await _build_quota_snapshot(
                    client,
                    payload=payload,
                    agent_id=agent_id,
                    settings=settings,
                    quota_service=quota_service,
                )
    except Exception:
        # 只读快照失败不影响连接；详细堆栈写服务端日志便于排查。
        logger.exception("Failed to build session info for agent %s", agent_id)
    return info


async def _build_quota_snapshot(
    client,
    *,
    payload: dict,
    agent_id: int,
    settings,
    quota_service: QuotaService,
) -> dict | None:
    """读取当前时间窗口四个资源的 limit/current；Redis 不可用时返回 None。"""
    dimensions = QuotaDimensions(
        platform_id=str(payload["platform_id"]),
        client_id=str(payload["client_id"]),
        agent_id=str(agent_id),
        end_user_id=str(payload["sub"]),
    )
    resources: dict = {}
    for resource in ("connection", "message", "model_tokens"):
        decision = await quota_service.peek(resource, dimensions)
        if decision.code == "quota_unavailable":
            return None
        resources[resource] = {"limit": decision.limit, "current": decision.current}
    # token_issue 的 limit 与签发逻辑一致（见 embed/services.build_token_quota_service），
    # current 用与签发时相同的维度（不含 end_user）探查同一窗口计数器。
    token_issue_limit = (
        client.max_tokens_per_minute
        if client.max_tokens_per_minute is not None
        else settings.quota_token_issue_limit
    )
    token_service = QuotaService(
        quota_service.counter,
        limits={"token_issue": token_issue_limit},
        window_seconds={"token_issue": settings.quota_window_seconds},
        clock=quota_service.clock,
    )
    token_decision = await token_service.peek(
        "token_issue",
        QuotaDimensions(
            platform_id=str(payload["platform_id"]),
            client_id=str(payload["client_id"]),
            agent_id=str(agent_id),
        ),
    )
    if token_decision.code == "quota_unavailable":
        return None
    resources["token_issue"] = {
        "limit": token_decision.limit,
        "current": token_decision.current,
    }
    return {
        "windowSeconds": settings.quota_window_seconds,
        "resources": resources,
    }


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: int):
    """处理一个完整的 Embed WebSocket 连接。

    认证成功后，函数进入双路事件循环：一边等待浏览器入站消息，一边等待
    模型任务产生的出站事件。这样模型在等待页面工具时，主循环仍能接收
    ``host_tool_result`` 或 ``confirmation_resolve``，避免连接层死锁。
    """
    origin = websocket.headers.get("origin")
    subprotocols = websocket.scope.get("subprotocols", [])
    # 子协议是 SDK 与网关版本协商的第一道门禁，不支持当前协议就不进入认证流程。
    if PROTOCOL_SUBPROTOCOL not in subprotocols:
        await websocket.close(code=4406)
        return
    await websocket.accept(subprotocol=PROTOCOL_SUBPROTOCOL)
    # envelope 必须先于认证错误处理定义，否则认证失败路径会在定义前
    # 引用它而触发 UnboundLocalError，被外层 except Exception 吞掉后
    # 只会关闭连接，前端永远收不到 error 事件。
    sequence = 1

    def envelope(
        event_type: str,
        event_payload: dict,
        *,
        conversation_id: int | None = None,
        request_id: str | None = None,
    ) -> str:
        """生成带单调 sequence 的协议事件，并统一附加关联 ID。"""
        nonlocal sequence
        value = {
            "id": f"evt_{sequence}",
            "type": event_type,
            "protocolVersion": 1,
            "sequence": sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": event_payload,
        }
        if conversation_id is not None:
            value["conversationId"] = str(conversation_id)
        if request_id is not None:
            value["requestId"] = request_id
        sequence += 1
        return json.dumps(value)

    try:
        # 握手后必须在短时间内收到 auth，防止未认证连接长期占用资源。
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        message = validate_incoming_message(raw)
        if message.get("type") != "auth":
            await websocket.close(code=4401)
            return
        auth_payload = message.get("payload", {})
        compatibility = check_client_compatibility(
            protocol_version=auth_payload.get("protocolVersion", 1),
            sdk_version=auth_payload.get("sdkVersion", "0.1.0"),
        )
        if not compatibility.allowed:
            await websocket.close(code=4406)
            return
        token = message.get("payload", {}).get("token")

        if not isinstance(token, str):
            await websocket.close(code=4401)
            return
        try:
            payload = await authenticate_embed_token(
                token, agent_id=agent_id, origin=origin or ""
            )
        except UnauthorizedException as err:
            logger.warning(
                "Embed auth rejected: agent_id=%s message=%s", agent_id, err.message
            )
            await _send_protocol_error(
                websocket,
                envelope,
                code="embed_token",
                message=err.message,
                retryable=False,
            )
            # 认证被拒属于会话终结，错误事件发出后主动关闭连接，
            # 避免该连接悬挂占用网关资源。
            await websocket.close(code=4401)
            return
        record_authentication("success")
        # 客户端带上次的会话和 sequence 时，先从 Redis Stream 补发缺失事件。
        replay_redis = Redis.from_url(get_settings().celery_broker_url)
        replay_store = ReplayStore(replay_redis)
        settings = get_settings()
        quota_service = None
        if settings.quota_enabled:
            quota_service = QuotaService(
                RedisQuotaStore(replay_redis),
                limits={
                    "connection": settings.quota_connection_limit,
                    "message": settings.quota_message_limit,
                    "model_tokens": settings.quota_model_tokens_limit,
                },
                window_seconds={
                    "connection": settings.quota_window_seconds,
                    "message": settings.quota_window_seconds,
                    "model_tokens": settings.quota_window_seconds,
                },
            )
            connection_decision = await quota_service.check(
                "connection",
                QuotaDimensions(
                    platform_id=str(payload["platform_id"]),
                    client_id=str(payload["client_id"]),
                    agent_id=str(agent_id),
                    end_user_id=str(payload["sub"]),
                ),
            )
            if not connection_decision.allowed:
                record_quota_rejection("connection", connection_decision.code)
                await websocket.close(code=4429)
                return
        record_connection("accepted")
        replay_conversation_id = auth_payload.get("conversationId")
        replay_cursor = auth_payload.get("lastSequence")
        normalized_replay_cursor = (
            str(replay_cursor)
            if isinstance(replay_cursor, (str, int)) and not isinstance(replay_cursor, bool)
            else None
        )
        if (
            isinstance(replay_conversation_id, str)
            and normalized_replay_cursor is not None
        ):
            try:
                replay_result = await replay_store.replay(
                    replay_conversation_id, normalized_replay_cursor
                )
            except Exception as exc:
                # 重放只是断线续传的增强能力：Redis 抖动、Stream 过期等异常
                # 不能让整个连接在建连阶段失败（否则页面会表现为连不上、
                # 注册页面工具等后续流程全部不发生），降级为「不重放」。
                logger.warning(
                    "Replay skipped conversation_id=%s cursor=%s error=%s",
                    replay_conversation_id,
                    normalized_replay_cursor,
                    exc,
                )
                replay_result = None
        else:
            replay_result = None
        # sequence 属于会话事件流，而不是单条 TCP/WS 连接。连接重建后必须
        # 从客户端游标或 replay 最新序号继续递增，否则 SDK 会把新连接的
        # message_started(sequence=2) 误判为已处理事件并丢弃。
        cursor_sequence = (
            int(normalized_replay_cursor)
            if normalized_replay_cursor and normalized_replay_cursor.isdigit()
            else 0
        )
        replay_latest = replay_result.latest_sequence if replay_result else 0
        sequence = max(
            sequence, cursor_sequence + 1, _numeric_sequence_floor(replay_latest) + 1
        )
        host_tool_session = get_session_factory()()
        host_tool_repo = HostToolRepository(host_tool_session)
        # 这些容器只属于当前连接：记录页面已注册的工具、对应后台策略，
        # 以及模型正在等待的页面工具结果 Future。
        registered_host_tools: set[str] = set()
        registered_host_policies: dict[str, object] = {}
        pending_host_results: dict[str, asyncio.Future] = {}
        pending_mcp_confirmations: dict[str, asyncio.Future] = {}
        pending_questions: dict[str, asyncio.Future] = {}

        session_info = await build_session_info(
            payload,
            agent_id=agent_id,
            settings=settings,
            quota_service=quota_service,
        )
        await websocket.send_text(
            envelope(
                "session_ready",
                {
                    "subject": payload["sub"],
                    "serverVersion": SERVER_VERSION,
                    "minimumSdkVersion": MINIMUM_SDK_VERSION,
                    "capabilities": sorted(CAPABILITIES),
                    "recovered": replay_result.recovered if replay_result else False,
                    "latestSequence": (
                        replay_result.latest_sequence if replay_result else None
                    ),
                    "client": session_info["client"],
                    "agent": session_info["agent"],
                    "quota": session_info["quota"],
                },
            )
        )
        if replay_result and replay_result.recovered:
            # 重放时发送原始 envelope，不能重新生成 sequence，否则客户端会重复消费。
            for recovered_event in replay_result.events:
                await websocket.send_text(
                    json.dumps(recovered_event, ensure_ascii=False)
                )
            # 新连接的 envelope 序号必须接在已重放事件之后；否则 SDK 已经记录
            # lastSequence=12，而新事件从 2 开始会被客户端按重复事件丢弃。
            recovered_sequences = [
                event.get("sequence")
                for event in replay_result.events
                if isinstance(event.get("sequence"), int)
            ]
            if recovered_sequences:
                sequence = max(sequence, max(recovered_sequences) + 1)
        registry = RequestRegistry()
        active_request: str | None = None
        active_task: asyncio.Task | None = None
        event_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        receive_task: asyncio.Task | None = None
        while True:
            # 每轮同时等待浏览器入站、模型/工具出站和当前请求结束。
            # FIRST_COMPLETED 让页面工具结果可以在模型等待期间及时进入处理流程。
            if receive_task is None:
                receive_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(event_queue.get())
            wait_set = {receive_task, queue_task}
            if active_task is not None:
                wait_set.add(active_task)
            done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
            if queue_task in done:
                event = queue_task.result()
                if event is not None:
                    # 业务侧事件已带协议 payload；dispatcher 等内部来源事件
                    # 仍由 events 注册表转换为协议 payload。最后统一附加
                    # sequence、会话和请求 ID。
                    event_type = event["type"]
                    if event_type == "message_completed" and quota_service is not None:
                        usage = event["payload"].get("usage") or {}
                        total_tokens = usage.get("total_tokens")
                        if isinstance(total_tokens, int) and total_tokens > 0:
                            consume = await quota_service.consume_capped(
                                "model_tokens",
                                QuotaDimensions(
                                    platform_id=str(payload["platform_id"]),
                                    client_id=str(payload["client_id"]),
                                    agent_id=str(agent_id),
                                    end_user_id=str(payload["sub"]),
                                ),
                                amount=total_tokens,
                            )
                            if not consume.available:
                                logger.warning(
                                    "model token quota accounting unavailable request_id=%s",
                                    event.get("request_id"),
                                )
                            elif consume.exceeded:
                                record_quota_rejection(
                                    "model_tokens", "quota_exceeded"
                                )
                                logger.warning(
                                    "model token quota exceeded request_id=%s amount=%s current=%s limit=%s",
                                    event.get("request_id"),
                                    total_tokens,
                                    consume.current,
                                    consume.limit,
                                )
                    event_payload = event.get("payload")
                    if event_payload is None:
                        event_payload = event_to_protocol_payload(event_type, event)
                    conversation_id = event.get("conversation_id")
                    request_id = event.get("request_id")
                    encoded = envelope(
                        event_type,
                        event_payload,
                        conversation_id=conversation_id,
                        request_id=request_id,
                    )
                    if conversation_id is not None:
                        await replay_store.append(conversation_id, json.loads(encoded))
                    await websocket.send_text(encoded)
                else:
                    # produce 以 None 标记事件流结束；释放 active request 后才能接收下一条消息。
                    active_task = None
                    active_request = None
                queue_task = None
            else:
                queue_task.cancel()
                await asyncio.gather(queue_task, return_exceptions=True)
            if active_task is not None and active_task in done:
                if active_request is not None:
                    task_error = active_task.exception()
                    if task_error is None:
                        registry.complete(active_request)
                    else:
                        registry.fail(
                            active_request,
                            build_agent_error_payload(task_error),
                        )
                active_task = None
                active_request = None
            if receive_task in done:
                message = validate_incoming_message(receive_task.result())
                receive_task = None
                message_type = message.get("type")
                request_id = message.get("requestId") or message.get("id")
                if message_type == "ping":
                    # ping 不进入模型任务，只返回 pong 维持连接活性。
                    await websocket.send_text(envelope("pong", {}))
                elif message_type == "message_cancel" and isinstance(request_id, str):
                    # 取消只作用于当前 requestId，不影响已完成或其他请求。
                    if await registry.cancel(request_id):
                        _cancel_pending_request_futures(
                            pending_mcp_confirmations,
                            pending_host_results,
                            pending_questions,
                        )
                        active_task = None
                        active_request = None
                elif message_type == "message_send":
                    active_request, active_task = await _handle_message_send(
                        websocket=websocket,
                        envelope=envelope,
                        message=message,
                        request_id=request_id,
                        payload=payload,
                        agent_id=agent_id,
                        quota_service=quota_service,
                        registry=registry,
                        active_task=active_task,
                        active_request=active_request,
                        event_queue=event_queue,
                        pending_mcp_confirmations=pending_mcp_confirmations,
                        pending_host_results=pending_host_results,
                        pending_questions=pending_questions,
                        host_tool_repo=host_tool_repo,
                        registered_host_tools=registered_host_tools,
                        registered_host_policies=registered_host_policies,
                    )
                elif message_type == "host_tools_register":
                    await _handle_host_tools_register(
                        websocket=websocket,
                        envelope=envelope,
                        message=message,
                        payload=payload,
                        agent_id=agent_id,
                        host_tool_repo=host_tool_repo,
                        registered_host_tools=registered_host_tools,
                        registered_host_policies=registered_host_policies,
                    )
                elif message_type == "confirmation_resolve":
                    await _handle_confirmation_resolve(
                        message=message,
                        payload=payload,
                        agent_id=agent_id,
                        host_tool_repo=host_tool_repo,
                        pending_mcp_confirmations=pending_mcp_confirmations,
                        pending_host_results=pending_host_results,
                    )
                elif message_type == "question_answer":
                    await _handle_question_answer(
                        message=message,
                        pending_questions=pending_questions,
                    )
                elif message_type in {"host_tool_result", "host_tool_error"}:
                    await _handle_host_tool_result(
                        message=message,
                        message_type=message_type,
                        payload=payload,
                        agent_id=agent_id,
                        host_tool_repo=host_tool_repo,
                        pending_host_results=pending_host_results,
                    )
    except asyncio.TimeoutError:
        # auth 超时使用独立关闭码，便于 SDK 区分“未及时认证”和普通断线。
        await websocket.close(code=4408)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("Embed WebSocket request failed during connection lifecycle")
        record_authentication("failure")
        record_error("websocket_failure")
        await websocket.close(code=4401)
    finally:
        # 无论认证、模型或客户端哪一层失败，都释放数据库和 Redis 连接。
        active = locals().get("active_task")
        active_request_id = locals().get("active_request")
        active_registry = locals().get("registry")
        if (
            active_registry is not None
            and isinstance(active_request_id, str)
            and active is not None
            and not active.done()
        ):
            # 不能只取消 asyncio Task：RequestRegistry 还需要进入 cancelled
            # 终态并释放 requestId，否则下一次连接/请求可能看到残留 in-progress。
            await active_registry.cancel(active_request_id)
        elif active is not None and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        for future in locals().get("pending_mcp_confirmations", {}).values():
            if not future.done():
                future.cancel()
        for future in locals().get("pending_questions", {}).values():
            if not future.done():
                future.cancel()
        for future in locals().get("pending_host_results", {}).values():
            if not future.done():
                future.cancel()
        host_session = locals().get("host_tool_session")
        if host_session is not None:
            await host_session.close()
        replay_redis = locals().get("replay_redis")
        if replay_redis is not None:
            await replay_redis.aclose()
