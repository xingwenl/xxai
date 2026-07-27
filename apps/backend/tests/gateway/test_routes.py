import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_app


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
