"""本地 mock 智能体网关（ai-agent.v1）：握手、协议版本、工具调用回环测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from desktop_app.manager import PluginManager
from desktop_app.plugin_data import PluginDataStore
from desktop_app.server import create_app


TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "ledger_add_entry",
        "description": "新增一条记账记录",
        "inputSchema": {"type": "object", "properties": {"amount": {"type": "number"}}},
        "sideEffect": "financial",
    },
    {
        "name": "ledger_list_entries",
        "description": "查询记账明细",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ledger_month_summary",
        "description": "统计月度收支",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _client(plugin_env: dict, tmp_path: Path, enabled: bool = True) -> TestClient:
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    app = create_app(
        manager,
        plugin_data=PluginDataStore(root=tmp_path / "plugin-data"),
        dev_agent_enabled=enabled,
    )
    return TestClient(app)


def _envelope(event_type: str, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    frame = {
        "id": f"frame-{event_type}",
        "type": event_type,
        "protocolVersion": 1,
        "timestamp": "2026-10-20T09:00:00+08:00",
        "payload": payload,
    }
    frame.update(extra)
    return frame


def _auth(token: str = "dev-local-token", protocol_version: int = 1) -> dict[str, Any]:
    return _envelope(
        "auth",
        {
            "token": token,
            "platformId": "desktop",
            "agentId": "local",
            "protocolVersion": protocol_version,
            "sdkVersion": "0.2.0",
        },
    )


def _register_tools(ws) -> None:
    ws.send_json(_envelope("host_tools_register", {"tools": TOOL_DEFS}))


def _send_text(ws, text: str, request_id: str) -> None:
    ws.send_json(_envelope("message_send", {"text": text}, id=request_id, requestId=request_id))


def _next_event(ws) -> dict[str, Any]:
    return ws.receive_json()


def _until_completed(ws) -> tuple[list[dict[str, Any]], str]:
    """收集流式事件直到 message_completed，返回事件列表与最终文本。"""
    events: list[dict[str, Any]] = []
    while True:
        event = _next_event(ws)
        events.append(event)
        if event["type"] == "message_completed":
            return events, event["payload"]["content"]
        assert len(events) < 50, "流式事件过多，疑似网关没有收敛"


@pytest.fixture
def client(plugin_env: dict, tmp_path: Path) -> TestClient:
    return _client(plugin_env, tmp_path)


def test_session_payload_exposed_to_host(client: TestClient) -> None:
    data = client.get("/api/desktop/agent-config").json()
    assert data["enabled"] is True
    assert data["mode"] == "dev"
    assert data["endpoint"] == "/api/v1/ws/agents/local"
    assert data["agentId"] == "local"
    assert data["token"]

    session = client.get("/api/desktop/dev-agent/session").json()
    assert session == data


def test_agent_config_hidden_when_disabled(plugin_env: dict, tmp_path: Path) -> None:
    disabled = _client(plugin_env, tmp_path, enabled=False)
    assert disabled.get("/api/desktop/agent-config").json()["enabled"] is False


def test_websocket_handshake(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        ready = _next_event(ws)
        assert ready["type"] == "session_ready"
        assert ready["protocolVersion"] == 1
        assert ready["sequence"] == 1
        assert ready["payload"]["sessionId"].startswith("dev-")
        assert ready["payload"]["agent"]["name"]


def test_websocket_rejects_missing_token(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth(token=""))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            _next_event(ws)
        assert excinfo.value.code == 4401


def test_websocket_rejects_unsupported_protocol(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth(protocol_version=2))
        error = _next_event(ws)
        assert error["type"] == "error"
        assert error["payload"]["code"] == "unsupported_protocol_version"
        with pytest.raises(WebSocketDisconnect) as excinfo:
            _next_event(ws)
        assert excinfo.value.code == 4406


def test_add_entry_tool_roundtrip(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        _register_tools(ws)
        _send_text(ws, "今天午饭花了 35 块", "req-1")

        started = _next_event(ws)
        assert started["type"] == "message_started"
        assert started["requestId"] == "req-1"

        call = _next_event(ws)
        assert call["type"] == "host_tool_call"
        assert call["payload"]["name"] == "ledger_add_entry"
        arguments = call["payload"]["arguments"]
        assert arguments["amount"] == 35
        assert arguments["type"] == "expense"
        assert arguments["category"] == "餐饮"
        assert call["payload"]["requiresConfirmation"] is False
        call_id = call["payload"]["callId"]

        ws.send_json(
            _envelope(
                "host_tool_result",
                {
                    "callId": call_id,
                    "result": {
                        "ok": True,
                        "entry": {
                            "id": "entry-1",
                            "type": "expense",
                            "amount_cents": 3500,
                            "amount_yuan": 35,
                            "category": "餐饮",
                            "note": "今天午饭花了 35 块",
                            "occurred_on": "2026-10-20",
                        },
                        "month_summary": {
                            "month": "2026-10",
                            "expense_yuan": 35,
                            "income_yuan": 0,
                            "balance_yuan": -35,
                        },
                    },
                },
                requestId=call_id,
            )
        )

        events, text = _until_completed(ws)
        assert events[0]["type"] == "message_delta"
        assert "35.00" in text
        assert "餐饮" in text
        assert "本月支出" in text
        sequences = [event["sequence"] for event in events]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)


def test_summary_tool_roundtrip(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        _register_tools(ws)
        _send_text(ws, "本月支出汇总", "req-2")

        assert _next_event(ws)["type"] == "message_started"
        call = _next_event(ws)
        assert call["type"] == "host_tool_call"
        assert call["payload"]["name"] == "ledger_month_summary"
        assert call["payload"]["arguments"] == {}
        call_id = call["payload"]["callId"]

        ws.send_json(
            _envelope(
                "host_tool_result",
                {
                    "callId": call_id,
                    "result": {
                        "month": "2026-10",
                        "expense_yuan": 320.5,
                        "income_yuan": 1000,
                        "balance_yuan": 679.5,
                        "by_category": [
                            {"category": "餐饮", "expense_yuan": 200.5, "income_yuan": 0, "count": 3},
                            {"category": "交通", "expense_yuan": 120, "income_yuan": 0, "count": 2},
                        ],
                    },
                },
                requestId=call_id,
            )
        )

        _, text = _until_completed(ws)
        assert "320.50" in text
        assert "1000.00" in text
        assert "餐饮" in text


def test_tool_error_is_reported_to_user(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        _register_tools(ws)
        _send_text(ws, "今天午饭花了 35 块", "req-3")

        _next_event(ws)  # message_started
        call = _next_event(ws)
        call_id = call["payload"]["callId"]

        ws.send_json(
            _envelope(
                "host_tool_error",
                {"callId": call_id, "code": "host_tool_execution_failed", "message": "金额必须大于 0"},
                requestId=call_id,
            )
        )

        _, text = _until_completed(ws)
        assert "host_tool_execution_failed" in text
        assert "金额必须大于 0" in text


def test_guidance_when_no_tools_registered(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        _send_text(ws, "本月支出汇总", "req-4")
        assert _next_event(ws)["type"] == "message_started"
        _, text = _until_completed(ws)
        assert "记账" in text
        assert "打开" in text


def test_concurrent_turn_replaces_previous(plugin_env: dict, tmp_path: Path) -> None:
    """同一连接上后一条消息会取消前一轮，不会出现两轮回复交错。"""
    client = _client(plugin_env, tmp_path)
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        _register_tools(ws)
        _send_text(ws, "本月支出汇总", "req-a")
        assert _next_event(ws)["type"] == "message_started"
        first = _next_event(ws)
        assert first["type"] == "host_tool_call"
        # 不回复工具调用，直接发下一条消息
        _send_text(ws, "最近的记账明细", "req-b")

        second_started = None
        for _ in range(6):
            event = _next_event(ws)
            if event["type"] == "message_started":
                second_started = event
                break
        assert second_started is not None
        assert second_started["requestId"] == "req-b"
        listing = _next_event(ws)
        assert listing["type"] == "host_tool_call"
        assert listing["payload"]["name"] == "ledger_list_entries"


def test_invalid_json_frame_is_ignored(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
        ws.send_json(_auth())
        _next_event(ws)
        ws.send_text("{not json")
        ws.send_json(_envelope("ping", {}))
        pong = _next_event(ws)
        assert pong["type"] == "pong"
        assert pong["sequence"] == 2
        assert json.loads(json.dumps(pong))["protocolVersion"] == 1
