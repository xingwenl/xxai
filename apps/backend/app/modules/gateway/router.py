import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import get_session_factory
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import load_runtime_context
from app.modules.conversation.services import retrieve_citations
from app.modules.gateway.runtime import RequestRegistry, stream_embed_chat
from app.modules.gateway.auth import PROTOCOL_SUBPROTOCOL, authenticate_embed_token
from app.modules.gateway.connection import validate_incoming_message
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository

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
        sequence = 1

        def envelope(event_type: str, event_payload: dict) -> str:
            nonlocal sequence
            value = {
                "id": f"evt_{sequence}",
                "type": event_type,
                "protocolVersion": 1,
                "sequence": sequence,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": event_payload,
            }
            sequence += 1
            return json.dumps(value)

        await websocket.send_text(
            envelope("session_ready", {"subject": payload["sub"], "recovered": False})
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
                    if event_type == "message_completed":
                        event_payload = {
                            "content": event["content"],
                            "citations": event["result"].citations,
                            "knowledgeGrounded": event["result"].knowledge_grounded,
                        }
                    await websocket.send_text(envelope(event_type, event_payload))
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
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=4401)
