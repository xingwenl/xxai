"""智能体后端配置与 token 换发测试。

覆盖三块：
1. ``AgentBackendConfig`` 的归一化与校验（base_url、ws 端点、来源限制）；
2. ``AgentConfigStore`` 的落盘、权限与半配置报错；
3. 宿主的 agent-config / agent-token 路由，含可注入 token 签发函数。
"""

from __future__ import annotations

import base64
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from desktop_app import agent_config
from desktop_app.agent_config import (
    AgentBackendConfig,
    AgentConfigError,
    AgentConfigNotConfigured,
    AgentConfigStore,
    issue_agent_token,
    validate_local_origin,
)
from desktop_app.server import create_app


def _make_config(**overrides) -> AgentBackendConfig:
    params = {
        "base_url": "http://127.0.0.1:8000",
        "client_id": "client_test",
        "client_secret": "secret_test",
        "agent_id": 1,
    }
    params.update(overrides)
    return AgentBackendConfig(**params)


def _fake_jwt(platform_id: int) -> str:
    """构造一个只含 payload 的假 JWT，供 ``_platform_id_from_token`` 解析。"""

    def encode(payload: dict) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'platform_id': platform_id})}.sig"


# ── AgentBackendConfig ──────────────────────────────────────────────────────


def test_config_derives_token_url_and_ws_endpoint() -> None:
    config = _make_config()
    assert config.token_url == "http://127.0.0.1:8000/api/v1/embed/tokens"
    assert config.ws_endpoint == "ws://127.0.0.1:8000/api/v1/ws/agents/1"
    assert config.ws_origin == "http://127.0.0.1:8000"


def test_config_uses_wss_for_https_base() -> None:
    config = _make_config(base_url="https://ai.example.com")
    assert config.ws_endpoint == "wss://ai.example.com/api/v1/ws/agents/1"


def test_config_normalizes_base_url_and_tool_names() -> None:
    config = _make_config(
        base_url="http://127.0.0.1:8000/",
        host_tool_names=("  ledger_add_entry ", "", "ledger_list_entries"),
    )
    assert config.base_url == "http://127.0.0.1:8000"
    assert config.host_tool_names == ("ledger_add_entry", "ledger_list_entries")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"base_url": "ftp://127.0.0.1:8000"}, "AI Base 地址"),
        ({"base_url": "http://"}, "AI Base 地址"),
        ({"client_id": "  "}, "Embed Client ID"),
        ({"client_secret": ""}, "Embed Client Secret"),
        ({"agent_id": 0}, "Agent ID"),
    ],
)
def test_config_rejects_invalid_values(overrides: dict, message: str) -> None:
    with pytest.raises(AgentConfigError, match=message):
        _make_config(**overrides)


def test_redacted_config_hides_secret() -> None:
    redacted = _make_config().redacted()
    assert "clientSecret" not in redacted
    assert redacted["hasSecret"] is True


def test_config_roundtrip_through_dict() -> None:
    config = _make_config(host_tool_names=("ledger_add_entry",))
    restored = AgentBackendConfig.from_dict(config.to_dict())
    assert restored == config


# ── AgentConfigStore ────────────────────────────────────────────────────────


def test_store_roundtrip_and_clear(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    assert store.load() is None

    store.save(_make_config())
    loaded = store.load()
    assert loaded is not None
    assert loaded.client_id == "client_test"
    # secret 是敏感信息，文件权限必须是仅本人可读写
    assert (tmp_path / "agent.json").stat().st_mode & 0o777 == 0o600

    assert store.clear() is True
    assert store.load() is None
    assert store.clear() is False


def test_store_reports_missing_secret(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({"baseUrl": "http://127.0.0.1:8000", "clientId": "c", "agentId": 1}), encoding="utf-8")
    with pytest.raises(AgentConfigError, match="Secret"):
        AgentConfigStore(path).load()


def test_store_reports_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentConfigError, match="读取智能体配置失败"):
        AgentConfigStore(path).load()


# ── validate_local_origin ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8765", "http://localhost:8443/", "https://127.0.0.1:8443"],
)
def test_validate_local_origin_accepts_loopback(origin: str) -> None:
    assert validate_local_origin(origin) == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    ["https://example.com", "http://0.0.0.0:8765", "http://localhost", "file:///tmp/index.html", ""],
)
def test_validate_local_origin_rejects_others(origin: str) -> None:
    with pytest.raises(AgentConfigError, match="仅支持本机页面来源"):
        validate_local_origin(origin)


# ── issue_agent_token ───────────────────────────────────────────────────────


def test_issue_token_requires_config(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    with pytest.raises(AgentConfigNotConfigured):
        issue_agent_token(store, "http://127.0.0.1:8765")


def test_issue_token_posts_expected_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.save(_make_config())
    captured: dict = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"data": {"access_token": _fake_jwt(7), "expires_in": 600}}).encode()

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(agent_config.urllib.request, "urlopen", fake_urlopen)
    result = issue_agent_token(store, "http://127.0.0.1:8765")

    assert captured["url"] == "http://127.0.0.1:8000/api/v1/embed/tokens"
    assert captured["body"]["host_tool_names"] == list(agent_config.DEFAULT_HOST_TOOL_NAMES)
    assert captured["body"]["origin"] == "http://127.0.0.1:8765"
    assert result["platformId"] == 7
    assert result["endpoint"] == "ws://127.0.0.1:8000/api/v1/ws/agents/1"
    assert result["mode"] == "remote"
    assert result["expiresIn"] == 600


def test_issue_token_wraps_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.save(_make_config())

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            None,
        )

    monkeypatch.setattr(agent_config.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AgentConfigError, match="HTTP 401"):
        issue_agent_token(store, "http://127.0.0.1:8765")


# ── create_app 路由 ────────────────────────────────────────────────────────


def _client(tmp_path: Path, **kwargs) -> tuple[TestClient, AgentConfigStore]:
    store = AgentConfigStore(tmp_path / "agent.json")
    app = create_app(agent_config_store=store, dev_agent_enabled=False, **kwargs)
    return TestClient(app), store


def _valid_payload() -> dict:
    return {
        "baseUrl": "http://127.0.0.1:8000",
        "clientId": "client_test",
        "clientSecret": "secret_test",
        "agentId": 1,
    }


def test_agent_config_initially_disabled(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = client.get("/api/desktop/agent-config").json()
    assert payload["enabled"] is False
    assert "设置页" in payload["reason"]


def test_save_agent_config_requires_secret_on_first_save(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = _valid_payload()
    body.pop("clientSecret")
    response = client.put("/api/desktop/agent-config", json=body)
    assert response.status_code == 400
    assert "Secret" in response.json()["detail"]


def test_save_and_read_agent_config_redacts_secret(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    response = client.put("/api/desktop/agent-config", json=_valid_payload())
    assert response.status_code == 200
    assert response.json()["config"]["hasSecret"] is True
    assert "clientSecret" not in response.json()["config"]

    payload = client.get("/api/desktop/agent-config").json()
    assert payload["enabled"] is True
    assert payload["mode"] == "remote"
    assert payload["agentId"] == 1
    assert payload["baseUrl"] == "http://127.0.0.1:8000"
    assert payload["hostToolNames"] == list(agent_config.DEFAULT_HOST_TOOL_NAMES)
    assert store.load() is not None


def test_second_save_keeps_previous_secret(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    client.put("/api/desktop/agent-config", json=_valid_payload())
    body = _valid_payload()
    body.pop("clientSecret")
    body["agentId"] = 2
    assert client.put("/api/desktop/agent-config", json=body).status_code == 200
    config = store.load()
    assert config is not None
    assert config.agent_id == 2
    assert config.client_secret == "secret_test"


def test_corrupt_config_is_reported(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    (tmp_path / "agent.json").write_text("{broken", encoding="utf-8")
    payload = client.get("/api/desktop/agent-config").json()
    assert payload["enabled"] is False
    assert "读取智能体配置失败" in payload["reason"]


def test_clear_agent_config(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.put("/api/desktop/agent-config", json=_valid_payload())
    assert client.delete("/api/desktop/agent-config").json()["removed"] is True
    assert client.delete("/api/desktop/agent-config").json()["removed"] is False
    assert client.get("/api/desktop/agent-config").json()["enabled"] is False


def test_agent_token_rejects_non_local_origin(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.put("/api/desktop/agent-config", json=_valid_payload())
    response = client.post("/api/desktop/agent-token", json={"origin": "https://evil.example.com"})
    assert response.status_code == 400


def test_agent_token_requires_config(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post("/api/desktop/agent-token", json={"origin": "http://127.0.0.1:8765"})
    assert response.status_code == 400
    assert "尚未配置" in response.json()["detail"]


def test_agent_token_uses_injected_issuer(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_issuer(store: AgentConfigStore, origin: str) -> dict:
        calls.append(origin)
        return {
            "token": "token-from-issuer",
            "expiresIn": 600,
            "endpoint": "ws://127.0.0.1:8000/api/v1/ws/agents/1",
            "platformId": 1,
            "agentId": 1,
            "mode": "remote",
        }

    client, store = _client(tmp_path, agent_token_issuer=fake_issuer)
    client.put("/api/desktop/agent-config", json=_valid_payload())
    payload = client.post(
        "/api/desktop/agent-token", json={"origin": "http://127.0.0.1:8765"}
    ).json()
    assert payload["token"] == "token-from-issuer"
    assert calls == ["http://127.0.0.1:8765"]


def test_agent_token_maps_issuer_errors(tmp_path: Path) -> None:
    def not_configured(store: AgentConfigStore, origin: str) -> dict:
        raise AgentConfigNotConfigured("尚未配置 AI Base 智能体后端")

    client, _ = _client(tmp_path, agent_token_issuer=not_configured)
    assert client.post(
        "/api/desktop/agent-token", json={"origin": "http://127.0.0.1:8765"}
    ).status_code == 400

    def upstream_failure(store: AgentConfigStore, origin: str) -> dict:
        raise AgentConfigError("AI Base 拒绝签发 token（HTTP 401）")

    client2, _ = _client(tmp_path, agent_token_issuer=upstream_failure)
    response = client2.post("/api/desktop/agent-token", json={"origin": "http://127.0.0.1:8765"})
    assert response.status_code == 502
    assert "HTTP 401" in response.json()["detail"]


def test_dev_agent_is_fallback_only_when_not_configured(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    client = TestClient(create_app(agent_config_store=store, dev_agent_enabled=True))
    dev = client.get("/api/desktop/agent-config").json()
    assert dev["enabled"] is True
    assert dev["mode"] == "dev"

    client.put("/api/desktop/agent-config", json=_valid_payload())
    remote = client.get("/api/desktop/agent-config").json()
    assert remote["mode"] == "remote"
