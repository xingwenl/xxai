"""FastAPI 内嵌服务的路由与静态页测试（扩展桌面管理接口）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_zip
import desktop_app.server as server
from desktop_app.app_config import APP_NAME
from desktop_app import paths
from desktop_app.manager import PluginManager
from desktop_app.server import create_app


requires_front_dist = pytest.mark.skipif(
    not paths.front_dist_dir().is_dir(),
    reason="apps/desktop/front/dist 未构建（先执行 pnpm build）",
)


def _client(env: dict) -> TestClient:
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    return TestClient(create_app(manager))


def test_health(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == APP_NAME


@requires_front_dist
def test_index_page_is_react_host(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/")
    assert resp.status_code == 200
    assert "WW" in resp.text
    assert '<div id="root">' in resp.text
    assert "/assets/" in resp.text


def test_plugin_shared_css_served(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/css/tailwind.css")
    assert resp.status_code == 200
    assert "tailwindcss" in resp.text


def test_static_asset_404(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/favicon.ico")
    assert resp.status_code == 404


def test_list_plugins_includes_builtin(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/api/desktop/plugins")
    assert resp.status_code == 200
    items = resp.json()["items"]
    hello = next(p for p in items if p["id"] == "hello-world")
    assert hello["builtin"] is True
    assert hello["enabled"] is True
    assert hello["entryUrl"] == "/apps/hello-world/index.html"


def test_plugin_static_files(plugin_env: dict) -> None:
    client = _client(plugin_env)
    assert client.get("/apps/hello-world/index.html").status_code == 200
    assert client.get("/apps/hello-world/icon.svg").status_code == 200
    assert client.get("/apps/hello-world/index.html").text == "<h1>hello</h1>"


def test_plugin_static_traversal_rejected(plugin_env: dict) -> None:
    client = _client(plugin_env)
    for path in ["/apps/hello-world/../manager.py", "/apps/hello-world/%2e%2e/manager.py"]:
        resp = client.get(path)
        assert resp.status_code == 404


def test_install_list_patch_delete_roundtrip(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env)
    zip_path = make_zip(
        tmp_path / "demo.zip",
        {
            "manifest.json": '{"id": "demo-app", "name": "演示应用", "version": "1.0.0", "permissions": ["notify"]}',
            "index.html": "<h1>demo</h1>",
        },
        wrapper_dir="demo-app",
    )
    zip_bytes = zip_path.read_bytes()
    resp = client.post(
        "/api/desktop/plugins/install",
        content=zip_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 200
    assert resp.json()["plugin"]["id"] == "demo-app"

    # 重复安装 → 409
    dup = client.post(
        "/api/desktop/plugins/install",
        content=zip_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert dup.status_code == 409

    # 启停
    patch = client.patch("/api/desktop/plugins/demo-app", json={"enabled": False})
    assert patch.status_code == 200
    assert patch.json()["plugin"]["enabled"] is False

    # 非 zip 拒绝
    bad = client.post(
        "/api/desktop/plugins/install",
        content=b"not a zip file",
        headers={"Content-Type": "application/zip"},
    )
    assert bad.status_code == 400

    # 卸载
    assert client.delete("/api/desktop/plugins/demo-app").status_code == 204
    ids = [p["id"] for p in client.get("/api/desktop/plugins").json()["items"]]
    assert "demo-app" not in ids


def test_delete_builtin_forbidden(plugin_env: dict) -> None:
    resp = _client(plugin_env).delete("/api/desktop/plugins/hello-world")
    assert resp.status_code == 403


def test_settings_endpoint(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/api/desktop/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == APP_NAME
    assert data["version"]
    assert data["userDataDir"]


def test_proxy_rejects_non_http(plugin_env: dict) -> None:
    resp = _client(plugin_env).post(
        "/api/desktop/proxy",
        json={"method": "GET", "url": "file:///etc/passwd"},
    )
    assert resp.status_code == 400


def test_proxy_roundtrip(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """代理往返：注入 mock urlopen，避免真实网络与 socket 依赖。"""

    class FakeResponse:
        def __init__(self, body: bytes, content_type: str = "application/json") -> None:
            self._body = body
            self.headers = {"Content-Type": content_type}

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def fake_urlopen(request, timeout=15):  # noqa: ANN001, ANN201
        assert request.full_url == "http://example.com/ping"
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(server, "_urlopen", fake_urlopen)
    resp = _client(plugin_env).post(
        "/api/desktop/proxy",
        json={"method": "GET", "url": "http://example.com/ping"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
