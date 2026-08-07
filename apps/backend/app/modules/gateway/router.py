"""Embed Agent 的 WebSocket 网关。

一条连接的主流程是：协议协商 -> token 认证 -> 事件恢复 -> 页面工具注册 ->
接收用户消息 -> 调用模型 -> 等待页面工具结果 -> 回传最终回答。网关同时负责
连接级 requestId 幂等、宿主工具 callId 审计和 Redis 事件重放。
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
from app.modules.gateway.connection import validate_incoming_message
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
from app.modules.skill_runner.client import SkillRunnerClient
from app.modules.skill_runner.services import execute_skill_script
from app.modules.skill.services import load_bound_skill_instruction
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.mcp.runtime import RepositoryMcpExecutor
from app.modules.mcp.services import (
    expire_tool_confirmation,
    invoke_tool,
    resolve_tool_confirmation,
)
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    build_temporary_host_tool_policy,
    canonical_fingerprint,
    redact_sensitive,
    utc_naive_now,
    validate_registration,
)
from app.modules.asset.repositories import AssetRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.builtin_tool.services import invoke_builtin_tool

router = APIRouter()
logger = get_logger(__name__)


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
        payload = await authenticate_embed_token(
            token, agent_id=agent_id, origin=origin or ""
        )
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
        replay_result = (
            await replay_store.replay(replay_conversation_id, replay_cursor)
            if isinstance(replay_conversation_id, str)
            and isinstance(replay_cursor, str)
            else None
        )
        host_tool_session = get_session_factory()()
        host_tool_repo = HostToolRepository(host_tool_session)
        # 这些容器只属于当前连接：记录页面已注册的工具、对应后台策略，
        # 以及模型正在等待的页面工具结果 Future。
        registered_host_tools: set[str] = set()
        registered_host_policies: dict[str, object] = {}
        pending_host_results: dict[str, asyncio.Future] = {}
        pending_mcp_confirmations: dict[str, asyncio.Future] = {}
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
                },
            )
        )
        if replay_result and replay_result.recovered:
            # 重放时发送原始 envelope，不能重新生成 sequence，否则客户端会重复消费。
            for recovered_event in replay_result.events:
                await websocket.send_text(
                    json.dumps(recovered_event, ensure_ascii=False)
                )
        registry = RequestRegistry()
        active_request: str | None = None
        active_task: asyncio.Task | None = None
        event_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def produce(request_id: str, message: dict) -> None:
            """执行一次模型请求，并把中间事件放入连接级队列。

            该函数运行在独立 Task 中，使用独立数据库 session。模型等待页面
            工具期间，外层 WebSocket 循环仍能处理结果消息并设置对应 Future。
            """
            try:
                async with get_session_factory()() as session:
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
                    loaded_skill_cache = {}
                    mcp_tools_by_key = {
                        (tool.server_id, tool.name): tool
                        for tool in context.mcp_tools
                    }

                    mcp_repo = McpRepository(session)
                    mcp_call_sequence = 0

                    async def invoke_runtime_tool(
                        *,
                        tool=None,
                        call=None,
                        server_id=None,
                        tool_name=None,
                        arguments=None,
                    ):
                        """按工具来源分流，并在 MCP 确认后恢复同一模型循环。"""
                        nonlocal mcp_call_sequence
                        if tool is None and server_id is not None and tool_name is not None:
                            tool = mcp_tools_by_key.get((server_id, tool_name))
                            mcp_call_sequence += 1
                            call = {
                                "id": f"{request_id}_mcp_{mcp_call_sequence}",
                                "args": arguments or {},
                            }
                        if tool is None or call is None:
                            raise ValueError("runtime tool context is missing")
                        if hasattr(tool, "server_id"):
                            call_id = str(call.get("id") or f"{request_id}_{tool.name}")
                            arguments = call.get("args", {})
                            outcome = await invoke_tool(
                                mcp_repo,
                                RepositoryMcpExecutor(mcp_repo),
                                platform_id=int(payload["platform_id"]),
                                agent_id=agent_id,
                                platform_end_user_id=int(payload["sub"]),
                                server_id=tool.server_id,
                                tool_name=tool.name,
                                arguments=arguments,
                            )
                            if outcome.status != "confirmation_required":
                                return outcome

                            decision = asyncio.get_running_loop().create_future()
                            pending_mcp_confirmations[call_id] = decision
                            expires_at = outcome.expires_at
                            timeout_seconds = 600.0
                            if expires_at is not None:
                                timeout_seconds = max(
                                    0.0,
                                    (expires_at - datetime.now(UTC)).total_seconds(),
                                )
                            await event_queue.put(
                                {
                                    "type": "confirmation_required",
                                    "conversation": None,
                                    "request_id": request_id,
                                    "call_id": call_id,
                                    "name": tool.name,
                                    "tool_type": "mcp_tool",
                                    "side_effect": tool.side_effect,
                                    "arguments": redact_sensitive(arguments),
                                    "expires_at": (
                                        expires_at.isoformat() if expires_at else None
                                    ),
                                }
                            )
                            try:
                                approved = await asyncio.wait_for(
                                    decision, timeout=timeout_seconds
                                )
                                resolved = await resolve_tool_confirmation(
                                    mcp_repo,
                                    RepositoryMcpExecutor(mcp_repo),
                                    confirmation_id=outcome.confirmation_id,
                                    platform_id=int(payload["platform_id"]),
                                    platform_end_user_id=int(payload["sub"]),
                                    approved=bool(approved),
                                )
                            except asyncio.TimeoutError:
                                resolved = await expire_tool_confirmation(
                                    mcp_repo,
                                    confirmation_id=outcome.confirmation_id,
                                    platform_id=int(payload["platform_id"]),
                                    platform_end_user_id=int(payload["sub"]),
                                )
                            finally:
                                pending_mcp_confirmations.pop(call_id, None)

                            if resolved.status in {"rejected", "expired"}:
                                resolved.result = {
                                    "status": resolved.status,
                                    "message": (
                                        "用户拒绝执行该工具，请勿自动重试"
                                        if resolved.status == "rejected"
                                        else "工具确认已超时，工具未执行"
                                    ),
                                }
                            return resolved

                        if getattr(tool, "kind", None) == "builtin":
                            return await invoke_builtin_tool(
                                builtin_tool_repo,
                                AssetRepository(session),
                                tool=tool,
                                call=call,
                                platform_id=int(payload["platform_id"]),
                                agent_id=agent_id,
                                conversation_id=context.conversation_id,
                                platform_end_user_id=int(payload["sub"]),
                            )
                        if getattr(tool, "kind", None) == "skill_script":
                            return await execute_skill_script(
                                skill_repo,
                                SkillRunnerClient(),
                                tool=tool,
                                call=call,
                                platform_id=int(payload["platform_id"]),
                                agent_id=agent_id,
                                platform_end_user_id=int(payload["sub"]),
                                request_id=request_id,
                            )
                        if getattr(tool, "kind", None) == "skill_instruction":
                            slug = call.get("args", {}).get("slug")
                            if isinstance(slug, str) and slug in loaded_skill_cache:
                                return loaded_skill_cache[slug]
                            outcome = await load_bound_skill_instruction(
                                skill_repo,
                                int(payload["platform_id"]),
                                agent_id,
                                slug,
                            )
                            if isinstance(slug, str) and outcome.status == "completed":
                                loaded_skill_cache[slug] = outcome
                            return outcome
                        call_id = str(call.get("id") or f"{request_id}_{tool.name}")
                        arguments = call.get("args", {})
                        existing = await host_tool_repo.get_call(
                            call_id,
                            platform_id=int(payload["platform_id"]),
                            agent_id=agent_id,
                            end_user_id=int(payload["sub"]),
                        )
                        if existing is not None:
                            # 终态调用直接复用历史结果，避免页面函数被重复执行。
                            if existing.arguments_fingerprint != canonical_fingerprint(
                                arguments
                            ):
                                raise ValueError(
                                    "host tool call id reused with different arguments"
                                )
                            if existing.status in {
                                "succeeded",
                                "failed",
                                "rejected",
                                "expired",
                            }:
                                return SimpleNamespace(
                                    status="completed", result=existing.result
                                )
                        else:
                            # 有副作用且策略要求 always 时先进入确认态；无副作用工具
                            # 可直接进入 running，由页面执行后回传结果。
                            requires_confirmation = (
                                tool.side_effect != "none"
                                and tool.confirmation_policy == "always"
                            )
                            existing = await host_tool_repo.create_audit(
                                call_id=call_id,
                                platform_id=int(payload["platform_id"]),
                                agent_id=agent_id,
                                platform_end_user_id=int(payload["sub"]),
                                conversation_id=None,
                                request_id=request_id,
                                tool_name=tool.name,
                                arguments=redact_sensitive(arguments),
                                arguments_fingerprint=canonical_fingerprint(arguments),
                                status=(
                                    "awaiting_confirmation"
                                    if requires_confirmation
                                    else "running"
                                ),
                                expires_at=utc_naive_now() + timedelta(minutes=10),
                            )
                        future = pending_host_results.get(call_id)
                        if future is None:
                            future = asyncio.get_running_loop().create_future()
                            pending_host_results[call_id] = future
                        await event_queue.put(
                            {
                                "type": "host_tool_call",
                                "conversation": None,
                                "request_id": request_id,
                                "call_id": call_id,
                                "name": tool.name,
                                "arguments": arguments,
                                "side_effect": tool.side_effect,
                                "requires_confirmation": existing.status
                                == "awaiting_confirmation",
                            }
                        )
                        # 此处只暂停模型 Task；WebSocket 主循环仍可接收结果并唤醒 Future。
                        result = await future
                        pending_host_results.pop(call_id, None)
                        if isinstance(result, dict) and "error" in result:
                            return SimpleNamespace(status="completed", result=result)
                        return SimpleNamespace(status="completed", result=result)

                    context.host_tools = [
                        registered_host_policies[name]
                        for name in registered_host_tools
                        if name in registered_host_policies
                    ]
                    runtime_tools = [
                        *context.builtin_tools,
                        *context.mcp_tools,
                        *context.host_tools,
                        *context.skill_script_tools,
                        *(
                            [context.skill_instruction_tool]
                            if context.skill_instruction_tool
                            else []
                        ),
                    ]
                    runtime_tools = filter_conflicting_runtime_tools(runtime_tools)
                    # 模型看到的工具集合再次取自连接级注册状态，未注册工具不会进入 bind_tools。
                    logger.info(
                        "Starting embed chat request %s with host tools=%s",
                        request_id,
                        [tool.name for tool in runtime_tools],
                    )
                    async for event in stream_embed_chat(
                        ConversationRepository(session),
                        context,
                        model=build_chat_model(context.version),
                        platform_id=payload["platform_id"],
                        client_id=str(payload["client_id"]),
                        end_user_id=int(payload["sub"]),
                        message=message["text"],
                        conversation_id=message.get("conversationId"),
                        request_id=request_id,
                        citations=[item.model_dump() for item in citations],
                        host_tools=context.host_tools,
                        runtime_tools=runtime_tools,
                        invoke_host_tool_fn=invoke_runtime_tool,
                    ):
                        await event_queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 后台 Task 不能静默失败，否则前端会永久停留在发送中；详细堆栈只写服务端日志。
                logger.exception("Embed chat request failed: %s", request_id)
                await event_queue.put(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "conversation": None,
                        "payload": build_agent_error_payload(exc),
                    }
                )
            finally:
                await event_queue.put(None)

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
                    # 先把内部事件转换为协议 payload，再统一附加 sequence、会话和请求 ID。
                    event_type = event["type"]
                    if event_type == "message_completed" and quota_service is not None:
                        usage = getattr(event.get("result"), "usage", None) or {}
                        total_tokens = usage.get("total_tokens")
                        if isinstance(total_tokens, int) and total_tokens > 0:
                            model_decision = await quota_service.check(
                                "model_tokens",
                                QuotaDimensions(
                                    platform_id=str(payload["platform_id"]),
                                    client_id=str(payload["client_id"]),
                                    agent_id=str(agent_id),
                                    end_user_id=str(payload["sub"]),
                                ),
                                amount=total_tokens,
                            )
                            if not model_decision.allowed:
                                record_quota_rejection(
                                    "model_tokens", model_decision.code
                                )
                                event_type = "error"
                                event["payload"] = {
                                    "code": model_decision.code,
                                    "message": "model token quota exceeded",
                                    "retryable": model_decision.retryable,
                                }
                    event_payload = (
                        {"content": event["content"]}
                        if event_type == "message_delta"
                        else {}
                    )
                    if event_type == "citation":
                        event_payload = event["citation"]
                    if event_type == "error":
                        event_payload = event["payload"]
                    if event_type == "host_tool_call":
                        event_payload = {
                            "callId": event["call_id"],
                            "name": event["name"],
                            "arguments": redact_sensitive(event["arguments"]),
                            "sideEffect": event["side_effect"],
                            "requiresConfirmation": event["requires_confirmation"],
                        }
                    if event_type == "confirmation_required":
                        event_payload = {
                            "callId": event["call_id"],
                            "name": event["name"],
                            "toolType": event["tool_type"],
                            "sideEffect": event["side_effect"],
                            "summary": {
                                "arguments": redact_sensitive(event["arguments"])
                            },
                            "expiresAt": event.get("expires_at"),
                        }
                    if event_type in {
                        "agent_loop_started",
                        "agent_step_started",
                        "agent_step_completed",
                        "agent_loop_completed",
                    }:
                        event_payload = event.get("payload", {})
                    if event_type == "message_completed":
                        event_payload = {
                            "content": event["content"],
                            "contentBlocks": event.get("content_blocks", []),
                            "citations": event["result"].citations,
                            "knowledgeGrounded": event["result"].knowledge_grounded,
                            "usage": event["result"].usage,
                            "loop": (
                                {
                                    "id": str(event.get("loop_run_id")),
                                    "requestId": event.get("request_id"),
                                    "status": "completed",
                                    "summary": "已完成回答",
                                    "steps": [],
                                }
                                if event.get("loop_run_id")
                                else None
                            ),
                        }
                    conversation_id = getattr(event.get("conversation"), "id", None)
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
                    registry.complete(active_request)
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
                        active_task = None
                        active_request = None
                elif message_type == "message_send":
                    record_message("message_send")
                    # 同一连接串行处理聊天请求；重复 requestId 做幂等处理，
                    # 不同 requestId 在前一个完成前返回 request_in_progress。
                    if not isinstance(request_id, str):
                        await websocket.send_text(
                            envelope(
                                "error",
                                {
                                    "code": "request_id_required",
                                    "message": "requestId is required",
                                    "retryable": False,
                                },
                            )
                        )
                    elif active_task is not None and active_request != request_id:
                        await websocket.send_text(
                            envelope(
                                "error",
                                {
                                    "code": "request_in_progress",
                                    "message": "request already running",
                                    "retryable": True,
                                },
                            )
                        )
                    elif active_request == request_id:
                        continue
                    else:
                        message_payload = message.get("payload", {})
                        if not isinstance(message_payload.get("text"), str):
                            await websocket.send_text(
                                envelope(
                                    "error",
                                    {
                                        "code": "text_required",
                                        "message": "text is required",
                                        "retryable": False,
                                    },
                                )
                            )
                            continue
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
                                await websocket.send_text(
                                    envelope(
                                        "error",
                                        {
                                            "code": decision.code,
                                            "message": (
                                                "message quota unavailable"
                                                if decision.code == "quota_unavailable"
                                                else "message quota exceeded"
                                            ),
                                            "retryable": decision.retryable,
                                            "details": {
                                                "retryAfterSeconds": str(
                                                    decision.retry_after_seconds or 0
                                                )
                                            },
                                        },
                                    )
                                )
                                continue
                        active_request = request_id
                        active_task = asyncio.create_task(
                            produce(request_id, message_payload)
                        )
                        registry.register(request_id, active_task)
                elif message_type == "host_tools_register":
                    # 页面提交的只是候选能力，最终可用集合必须是：
                    # token claim ∩ Agent 后台绑定 ∩ 当前页面注册，并且 Schema 完全一致。
                    registrations = message.get("payload", {}).get("tools", [])
                    if not isinstance(registrations, list):
                        await websocket.send_text(
                            envelope(
                                "error",
                                {
                                    "code": "invalid_host_tools",
                                    "message": "tools must be a list",
                                    "retryable": False,
                                },
                            )
                        )
                        continue
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
                        continue
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
                        if (
                            not isinstance(item, dict)
                            or item.get("name") not in by_name
                        ):
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
                                    item.get("inputSchema")
                                    or item.get("input_schema")
                                    or {}
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
                elif message_type == "confirmation_resolve":
                    # 确认结果必须重新按 token 主体查询审计，不能只信任页面传来的 callId。
                    call_id = message.get("payload", {}).get("callId")
                    approved = message.get("payload", {}).get("approved")
                    if isinstance(call_id, str) and isinstance(approved, bool):
                        mcp_decision = pending_mcp_confirmations.get(call_id)
                        if mcp_decision is not None:
                            if not mcp_decision.done():
                                mcp_decision.set_result(approved)
                            continue
                        audit = await host_tool_repo.get_call(
                            call_id,
                            platform_id=int(payload["platform_id"]),
                            agent_id=agent_id,
                            end_user_id=int(payload["sub"]),
                        )
                        if (
                            audit is not None
                            and audit.status == "awaiting_confirmation"
                        ):
                            await host_tool_repo.transition_call(
                                audit, "running" if approved else "rejected"
                            )
                            if not approved:
                                future = pending_host_results.get(call_id)
                                if future is not None and not future.done():
                                    future.set_result({"error": "host_tool_rejected"})
                elif message_type in {"host_tool_result", "host_tool_error"}:
                    # 只接受当前主体下、状态为 running 的调用结果；重复或越权结果会被忽略。
                    call_id = message.get("payload", {}).get("callId")
                    if not isinstance(call_id, str):
                        continue
                    audit = await host_tool_repo.get_call(
                        call_id,
                        platform_id=int(payload["platform_id"]),
                        agent_id=agent_id,
                        end_user_id=int(payload["sub"]),
                    )
                    if audit is None or audit.status != "running":
                        continue
                    if message_type == "host_tool_result":
                        result = redact_sensitive(
                            message.get("payload", {}).get("result")
                        )
                        if len(json.dumps(result, ensure_ascii=False)) > 32 * 1024:
                            await host_tool_repo.transition_call(
                                audit, "failed", error="host_tool_result_too_large"
                            )
                        else:
                            await host_tool_repo.transition_call(
                                audit, "succeeded", result=result
                            )
                            future = pending_host_results.get(call_id)
                            if future is not None and not future.done():
                                future.set_result(result)
                    else:
                        await host_tool_repo.transition_call(
                            audit,
                            "failed",
                            error=str(
                                message.get("payload", {}).get(
                                    "message", "host tool failed"
                                )
                            ),
                        )
                        future = pending_host_results.get(call_id)
                        if future is not None and not future.done():
                            future.set_result({"error": "host_tool_failed"})
    except asyncio.TimeoutError:
        # auth 超时使用独立关闭码，便于 SDK 区分“未及时认证”和普通断线。
        await websocket.close(code=4408)
    except WebSocketDisconnect:
        return
    except Exception:
        record_authentication("failure")
        record_error("websocket_failure")
        await websocket.close(code=4401)
    finally:
        # 无论认证、模型或客户端哪一层失败，都释放数据库和 Redis 连接。
        active = locals().get("active_task")
        if active is not None and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        for future in locals().get("pending_mcp_confirmations", {}).values():
            if not future.done():
                future.cancel()
        host_session = locals().get("host_tool_session")
        if host_session is not None:
            await host_session.close()
        replay_redis = locals().get("replay_redis")
        if replay_redis is not None:
            await replay_redis.aclose()
