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
from app.modules.conversation.runtime import load_runtime_context
from app.modules.conversation.services import retrieve_citations
from app.modules.gateway.runtime import RequestRegistry, stream_embed_chat
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
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    canonical_fingerprint,
    redact_sensitive,
    utc_naive_now,
    validate_registration,
)

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
                    context = await load_runtime_context(
                        agent_repo,
                        KnowledgeRepository(session),
                        SkillRepository(session),
                        McpRepository(session),
                        agent_id=agent_id,
                        platform_id=payload["platform_id"],
                    )
                    citations = await retrieve_citations(
                        KnowledgeRepository(session),
                        context.knowledge_bases,
                        message["text"],
                    )

                    async def invoke_host_tool(*, tool, call):
                        """把模型 tool_call 转换为页面可执行的宿主工具调用。

                        先按 callId 查询审计，保证重试/重放不会以不同参数复用同一 ID；
                        新调用写入审计后，通过 Future 等待页面回传结果。
                        """
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
                    # 模型看到的工具集合再次取自连接级注册状态，未注册工具不会进入 bind_tools。
                    logger.info(
                        "Starting embed chat request %s with host tools=%s",
                        request_id,
                        [tool.name for tool in context.host_tools],
                    )
                    async for event in stream_embed_chat(
                        ConversationRepository(session),
                        context,
                        model=build_chat_model(context.version),
                        platform_id=payload["platform_id"],
                        end_user_id=int(payload["sub"]),
                        message=message["text"],
                        conversation_id=message.get("conversationId"),
                        request_id=request_id,
                        citations=[item.model_dump() for item in citations],
                        host_tools=context.host_tools,
                        invoke_host_tool_fn=invoke_host_tool,
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
                        "payload": {
                            "code": "request_failed",
                            "message": str(exc),
                            "retryable": True,
                        },
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
                    if event_type == "message_completed":
                        event_payload = {
                            "content": event["content"],
                            "citations": event["result"].citations,
                            "knowledgeGrounded": event["result"].knowledge_grounded,
                            "usage": event["result"].usage,
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
                                            "message": "message quota unavailable"
                                            if decision.code == "quota_unavailable"
                                            else "message quota exceeded",
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
                            continue
                        try:
                            validate_registration(by_name[item["name"]], item)
                        except ValueError:
                            continue
                        registered_host_tools.add(item["name"])
                        registered_host_policies[item["name"]] = by_name[item["name"]]
                    logger.info(
                        "Host tools active for connection: %s",
                        sorted(registered_host_tools),
                    )
                elif message_type == "confirmation_resolve":
                    # 确认结果必须重新按 token 主体查询审计，不能只信任页面传来的 callId。
                    call_id = message.get("payload", {}).get("callId")
                    approved = message.get("payload", {}).get("approved")
                    if isinstance(call_id, str) and isinstance(approved, bool):
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
        host_session = locals().get("host_tool_session")
        if host_session is not None:
            await host_session.close()
        replay_redis = locals().get("replay_redis")
        if replay_redis is not None:
            await replay_redis.aclose()
