"""AI Base HTTP 同源转发测试。

渲染层（宿主前端）只与宿主同源，SDK 的 REST 调用（附件上传、会话列表等）统一打到
``/api/v1/*``，由宿主转发给 agent.json 里配置的 AI Base 地址。这里用一个记录型
``_urlopen`` 桩验证转发内容与状态码透传，不依赖真实后端。
"""

from __future__ import annotations

import io
import urllib.error
from typing import Any

from fastapi.testclient import TestClient

import desktop_app.server as server
from desktop_app.agent_config import AgentBackendConfig, AgentConfigStore
from desktop_app.manager import PluginManager
from desktop_app.server import create_app


class _FakeResponse:
    """最小化 urlopen 响应对象：read + 上下文管理器 + status/headers。"""

    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json") -> None:
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def _make_config() -> AgentBackendConfig:
    return AgentBackendConfig(
        base_url="http://ai-base.test",
        client_id="client_test",
        client_secret="secret_test",
        agent_id=1,
    )


def _client(
    plugin_env: dict,
    *,
    configured: bool = True,
    tmp_path=None,
    monkeypatch=None,
    responder=None,
) -> tuple[TestClient, list[Any]]:
    """构造挂了桩 ``_urlopen`` 的宿主客户端，返回 (client, 已捕获的上游请求)。"""
    store = AgentConfigStore(tmp_path / "agent.json")
    if configured:
        store.save(_make_config())
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    captured: list[Any] = []

    def fake_urlopen(request, timeout=15):
        captured.append(request)
        if responder is not None:
            return responder(request)
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(server, "_urlopen", fake_urlopen)
    return TestClient(create_app(manager, agent_config_store=store)), captured


def test_forwards_get_with_query_and_authorization(
    plugin_env: dict, tmp_path, monkeypatch
) -> None:
    client, captured = _client(plugin_env, tmp_path=tmp_path, monkeypatch=monkeypatch)
    resp = client.get(
        "/api/v1/embed/conversations?page=1&page_size=20",
        headers={"Authorization": "Bearer tok-123"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(captured) == 1
    upstream = captured[0]
    assert upstream.full_url == "http://ai-base.test/api/v1/embed/conversations?page=1&page_size=20"
    assert upstream.get_method() == "GET"
    # 短期 token 由渲染层带上来，宿主原样透传（secret 不出宿主进程）
    assert upstream.get_header("Authorization") == "Bearer tok-123"


def test_forwards_post_body_and_content_type(plugin_env: dict, tmp_path, monkeypatch) -> None:
    client, captured = _client(plugin_env, tmp_path=tmp_path, monkeypatch=monkeypatch)
    payload = b'--boundary\r\nContent-Disposition: form-data; name="file"\r\n\r\nx\r\n--boundary--\r\n'
    resp = client.post(
        "/api/v1/embed/assets",
        content=payload,
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
    )

    assert resp.status_code == 200
    upstream = captured[0]
    assert upstream.get_method() == "POST"
    assert upstream.data == payload
    assert upstream.get_header("Content-type") == "multipart/form-data; boundary=boundary"


def test_forwards_delete_method(plugin_env: dict, tmp_path, monkeypatch) -> None:
    client, captured = _client(
        plugin_env,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        responder=lambda _req: _FakeResponse(b"", status=204, content_type="application/json"),
    )
    resp = client.delete("/api/v1/embed/conversations/42")

    assert resp.status_code == 204
    assert captured[0].get_method() == "DELETE"


def test_passes_through_upstream_error(plugin_env: dict, tmp_path, monkeypatch) -> None:
    def responder(request):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"message":"\xe4\xb8\x8d\xe6\x94\xaf\xe6\x8c\x81\xe7\x9a\x84\xe6\x96\x87\xe4\xbb\xb6\xe7\xb1\xbb\xe5\x9e\x8b"}'),
        )

    client, _ = _client(
        plugin_env, tmp_path=tmp_path, monkeypatch=monkeypatch, responder=responder
    )
    resp = client.post("/api/v1/embed/assets", content=b"x")

    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["message"]


def test_returns_503_when_backend_not_configured(
    plugin_env: dict, tmp_path, monkeypatch
) -> None:
    client, captured = _client(
        plugin_env, configured=False, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    resp = client.get("/api/v1/embed/conversations")

    assert resp.status_code == 503
    assert "智能体后端" in resp.json()["detail"]
    assert captured == []


def test_rejects_forwarded_path_traversal(plugin_env: dict, tmp_path, monkeypatch) -> None:
    client, captured = _client(plugin_env, tmp_path=tmp_path, monkeypatch=monkeypatch)
    resp = client.get("/api/v1/%2E%2E/admin")

    assert resp.status_code == 400
    assert "非法转发路径" in resp.json()["detail"]
    assert captured == []
