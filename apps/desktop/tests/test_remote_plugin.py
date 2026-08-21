"""remote 插件测试：manager 安装/编辑/刷新与宿主接口契约。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import desktop_app.metadata as metadata
from desktop_app.manager import PluginExistsError, PluginManager, PluginError
from desktop_app.server import create_app

PUBLIC = "https://93.184.216.34"
EXAMPLE_HTML = (
    "<html><head><title>Example</title>"
    f'<meta property="og:title" content="Example Site"/>'
    f'<meta property="og:description" content="示例站点描述"/>'
    f'<meta property="og:image" content="{PUBLIC}/icon.png"/></head></html>'
)


class FakeResponse:
    def __init__(self, status: int = 200, headers: dict | None = None, body: bytes = b"", url: str = "") -> None:
        self._status = status
        self.headers = headers or {}
        self._body = body
        self._url = url

    def getcode(self) -> int:
        return self._status

    def geturl(self) -> str:
        return self._url

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._body
        chunk = self._body[:n]
        self._body = self._body[n:]
        return chunk


def make_fetcher(routes: dict[tuple[str, str], FakeResponse | Exception]):
    def fetcher(request, timeout: float | None = None):  # noqa: ARG001
        hit = routes.get((request.get_method(), request.full_url))
        if hit is None:
            return FakeResponse(404, url=request.full_url)
        if isinstance(hit, Exception):
            raise hit
        return FakeResponse(hit._status, dict(hit.headers), bytes(hit._body), hit._url)

    return fetcher


def example_routes() -> dict[tuple[str, str], FakeResponse]:
    """模拟一个可抓取的示例站点：og 元数据 + 图标 + 无嵌入限制。"""
    return {
        ("GET", f"{PUBLIC}/"): FakeResponse(
            headers={"Content-Type": "text/html"}, body=EXAMPLE_HTML.encode(), url=f"{PUBLIC}/"
        ),
        ("HEAD", f"{PUBLIC}/"): FakeResponse(headers={}, url=f"{PUBLIC}/"),
        ("GET", f"{PUBLIC}/icon.png"): FakeResponse(
            headers={"Content-Type": "image/png"}, body=b"\x89PNG", url=f"{PUBLIC}/icon.png"
        ),
    }


def _manager(plugin_env: dict) -> PluginManager:
    return PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )


def _client(plugin_env: dict) -> TestClient:
    return TestClient(create_app(_manager(plugin_env)))


# ---------- manager：安装 ----------


def test_install_from_url(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/")
    assert plugin.type == "remote"
    assert plugin.url == f"{PUBLIC}/"
    assert plugin.name == "Example Site"
    assert plugin.permissions == []
    info = plugin.to_dict()
    assert info["entryUrl"] == f"{PUBLIC}/"
    assert info["iconUrl"] == "/apps/93-184-216-34/icon.png"
    manifest = json.loads((plugin.dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["type"] == "remote"
    assert manifest["url"] == f"{PUBLIC}/"
    assert manifest["permissions"] == []
    assert (plugin.dir / "icon.png").read_bytes() == b"\x89PNG"


def test_install_conflict_appends_suffix(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    routes = example_routes()
    routes[("GET", f"{PUBLIC}/other")] = FakeResponse(
        headers={"Content-Type": "text/html"}, body=EXAMPLE_HTML.encode(), url=f"{PUBLIC}/other"
    )
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(routes))
    manager = _manager(plugin_env)
    first = manager.install_from_url(f"{PUBLIC}/")
    second = manager.install_from_url(f"{PUBLIC}/other")
    assert first.id == "93-184-216-34"
    assert second.id == "93-184-216-34-2"


def test_install_duplicate_rejected(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    manager = _manager(plugin_env)
    manager.install_from_url(f"{PUBLIC}/")
    with pytest.raises(PluginExistsError):
        manager.install_from_url(f"{PUBLIC}/")


def test_install_manual_name_when_fetch_fails(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher({}))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/", name="手动应用", description="手动描述")
    assert plugin.name == "手动应用"
    assert plugin.description == "手动描述"
    # 抓取失败时图标缺失，回退到占位 SVG
    assert (plugin.dir / plugin.icon).read_text(encoding="utf-8").startswith("<svg")


def test_install_without_name_when_fetch_fails(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher({}))
    manager = _manager(plugin_env)
    with pytest.raises(PluginError, match="手动填写"):
        manager.install_from_url(f"{PUBLIC}/")


def test_install_localhost_with_manual_name(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """回环地址允许安装（本地开发服务），抓取由注入 fetcher 提供。"""
    local = "http://127.0.0.1:3000/"
    routes = {
        ("GET", f"{local}/"): FakeResponse(
            headers={"Content-Type": "text/html"},
            body="<html><head><title>本地服务</title></head></html>".encode("utf-8"),
            url=f"{local}/",
        ),
        ("HEAD", f"{local}/"): FakeResponse(headers={}, url=f"{local}/"),
    }
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(routes))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(local, name="本地服务")
    assert plugin.type == "remote"
    assert plugin.url == local
    assert plugin.id == "127-0-0-1"


def test_install_rejects_link_local_url(plugin_env: dict) -> None:
    manager = _manager(plugin_env)
    with pytest.raises(PluginError, match="不可访问"):
        manager.install_from_url("http://169.254.169.254/")


def test_install_manual_icon_url(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    routes = example_routes()
    routes[("GET", f"{PUBLIC}/custom.png")] = FakeResponse(
        headers={"Content-Type": "image/png"}, body=b"custom", url=f"{PUBLIC}/custom.png"
    )
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(routes))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/", icon_url=f"{PUBLIC}/custom.png")
    assert (plugin.dir / "icon.png").read_bytes() == b"custom"


# ---------- manager：编辑与刷新 ----------


def test_update_metadata_keeps_url(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/")
    updated = manager.update_metadata(plugin.id, name="新名字", description="新描述")
    assert updated.name == "新名字"
    assert updated.description == "新描述"
    assert updated.url == f"{PUBLIC}/"
    assert updated.type == "remote"


def test_refresh_metadata(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/", name="旧名字")
    refreshed = manager.refresh_metadata(plugin.id)
    assert refreshed.name == "Example Site"
    assert refreshed.id == plugin.id
    assert refreshed.url == plugin.url


def test_refresh_metadata_failure_keeps_data(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    manager = _manager(plugin_env)
    plugin = manager.install_from_url(f"{PUBLIC}/", name="保留我")
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher({}))
    with pytest.raises(PluginError, match="保留原数据"):
        manager.refresh_metadata(plugin.id)
    assert manager.get(plugin.id).name == "保留我"


def test_update_metadata_rejects_iframe_plugin(plugin_env: dict) -> None:
    manager = _manager(plugin_env)
    with pytest.raises(PluginError, match="remote"):
        manager.update_metadata("hello-world", name="x")


# ---------- 宿主接口 ----------


def test_install_from_url_endpoint(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    client = _client(plugin_env)
    resp = client.post("/api/desktop/plugins/install-from-url", json={"url": f"{PUBLIC}/"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plugin"]["type"] == "remote"
    assert data["plugin"]["permissions"] == []
    assert data["frameable"] is True


def test_install_from_url_rejects_link_local(plugin_env: dict) -> None:
    client = _client(plugin_env)
    resp = client.post("/api/desktop/plugins/install-from-url", json={"url": "http://169.254.169.254/"})
    assert resp.status_code == 400
    assert "不可访问" in resp.json()["detail"]


def test_patch_remote_metadata(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    client = _client(plugin_env)
    install = client.post("/api/desktop/plugins/install-from-url", json={"url": f"{PUBLIC}/"}).json()["plugin"]
    resp = client.patch(f"/api/desktop/plugins/{install['id']}", json={"name": "接口改名"})
    assert resp.status_code == 200
    assert resp.json()["plugin"]["name"] == "接口改名"


def test_patch_metadata_on_iframe_rejected(plugin_env: dict) -> None:
    client = _client(plugin_env)
    resp = client.patch("/api/desktop/plugins/hello-world", json={"name": "x"})
    assert resp.status_code == 400


def test_refresh_metadata_endpoint(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    client = _client(plugin_env)
    install = client.post("/api/desktop/plugins/install-from-url", json={"url": f"{PUBLIC}/"}).json()["plugin"]
    resp = client.post(f"/api/desktop/plugins/{install['id']}/refresh-metadata")
    assert resp.status_code == 200
    assert resp.json()["plugin"]["url"] == f"{PUBLIC}/"


def test_remote_plugin_in_list(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher(example_routes()))
    client = _client(plugin_env)
    client.post("/api/desktop/plugins/install-from-url", json={"url": f"{PUBLIC}/"})
    items = client.get("/api/desktop/plugins").json()["items"]
    remote = next(p for p in items if p["type"] == "remote")
    assert remote["url"] == f"{PUBLIC}/"
    assert remote["entryUrl"] == f"{PUBLIC}/"
    assert remote["permissions"] == []
    assert remote["builtin"] is False
