import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_app
from app.modules.embed.security import create_embed_token


def test_websocket_rejects_missing_protocol_subprotocol():
    client = TestClient(create_app())

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/api/v1/ws/agents/11", headers={"origin": "https://app.acme.test"}
        ):
            pass

    assert error.value.code == 4406


def test_websocket_requires_auth_as_first_message():
    client = TestClient(create_app())

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/api/v1/ws/agents/11",
            headers={"origin": "https://app.acme.test"},
            subprotocols=["ai-agent.v1"],
        ) as websocket:
            websocket.send_json({"type": "ping", "payload": {}})
            websocket.receive_text()

    assert error.value.code == 4401


def test_websocket_auth_failure_sends_embed_token_error_then_closes():
    client = TestClient(create_app())
    # token 的 agent_id 与连接路径不一致，authenticate_embed_token 必然抛
    # UnauthorizedException，验证网关会先发 error 事件再关闭连接。
    token, _ = create_embed_token(
        subject="22",
        platform_id=7,
        agent_id=12,
        client_id="client_acme",
        origin="https://app.acme.test",
        expires_in=600,
    )

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/api/v1/ws/agents/11",
            headers={"origin": "https://app.acme.test"},
            subprotocols=["ai-agent.v1"],
        ) as websocket:
            websocket.send_json({"type": "auth", "payload": {"token": token}})
            event = json.loads(websocket.receive_text())
            assert event["type"] == "error"
            assert event["payload"]["code"] == "embed_token"
            assert event["payload"]["retryable"] is False
            # 错误事件发出后网关应主动关闭连接。
            websocket.receive_text()

    assert error.value.code == 4401
