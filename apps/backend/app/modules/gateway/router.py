import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import load_runtime_context
from app.modules.conversation.services import retrieve_citations
from app.modules.gateway.runtime import RequestRegistry, stream_embed_chat
from app.modules.gateway.replay import ReplayStore
from app.modules.gateway.auth import PROTOCOL_SUBPROTOCOL, authenticate_embed_token
from app.modules.gateway.connection import validate_incoming_message
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    canonical_fingerprint,
    redact_sensitive,
    validate_registration,
)

router = APIRouter()


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: int):
    origin = websocket.headers.get("origin")
    subprotocols = websocket.scope.get("subprotocols", [])
    if PROTOCOL_SUBPROTOCOL not in subprotocols:
        await websocket.close(code=4406)
        return
    await websocket.accept(subprotocol=PROTOCOL_SUBPROTOCOL)
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        message = validate_incoming_message(raw)
        if message.get("type") != "auth":
            await websocket.close(code=4401)
            return
        token = message.get("payload", {}).get("token")
        if not isinstance(token, str):
            await websocket.close(code=4401)
            return
        payload = await authenticate_embed_token(
            token, agent_id=agent_id, origin=origin or ""
        )
        auth_payload = message.get("payload", {})
        replay_redis = Redis.from_url(get_settings().celery_broker_url)
        replay_store = ReplayStore(replay_redis)
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
                    "recovered": replay_result.recovered if replay_result else False,
                    "latestSequence": (
                        replay_result.latest_sequence if replay_result else None
                    ),
                },
            )
        )
        if replay_result and replay_result.recovered:
            for recovered_event in replay_result.events:
                await websocket.send_text(
                    json.dumps(recovered_event, ensure_ascii=False)
                )
        registry = RequestRegistry()
        active_request: str | None = None
        active_task: asyncio.Task | None = None
        event_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def produce(request_id: str, message: dict) -> None:
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
                    call_id = str(call.get("id") or f"{request_id}_{tool.name}")
                    arguments = call.get("args", {})
                    existing = await host_tool_repo.get_call(
                        call_id,
                        platform_id=int(payload["platform_id"]),
                        agent_id=agent_id,
                        end_user_id=int(payload["sub"]),
                    )
                    if existing is not None:
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
                            expires_at=datetime.now(UTC) + timedelta(minutes=10),
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
            await event_queue.put(None)

        receive_task: asyncio.Task | None = None
        while True:
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
                    event_type = event["type"]
                    event_payload = (
                        {"content": event["content"]}
                        if event_type == "message_delta"
                        else {}
                    )
                    if event_type == "citation":
                        event_payload = event["citation"]
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
                    await websocket.send_text(envelope("pong", {}))
                elif message_type == "message_cancel" and isinstance(request_id, str):
                    if await registry.cancel(request_id):
                        active_task = None
                        active_request = None
                elif message_type == "message_send":
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
                        active_request = request_id
                        active_task = asyncio.create_task(
                            produce(request_id, message_payload)
                        )
                        registry.register(request_id, active_task)
                elif message_type == "host_tools_register":
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
                elif message_type == "confirmation_resolve":
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
        await websocket.close(code=4408)
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=4401)
    finally:
        host_session = locals().get("host_tool_session")
        if host_session is not None:
            await host_session.close()
        replay_redis = locals().get("replay_redis")
        if replay_redis is not None:
            await replay_redis.aclose()
