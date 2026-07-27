import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.modules.gateway.auth import PROTOCOL_SUBPROTOCOL, authenticate_embed_token
from app.modules.gateway.connection import validate_incoming_message

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
        while True:
            message = validate_incoming_message(await websocket.receive_text())
            if message.get("type") == "ping":
                await websocket.send_text(envelope("pong", {}))
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=4401)
