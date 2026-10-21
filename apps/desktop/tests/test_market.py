"""插件市场测试。

覆盖四层：
1. 索引解析与校验（`market.parse_index`，含非法字段、非法地址、重复 id、版本门控）；
2. 索引缓存与开关（`fetch_index` 的 5 分钟缓存、`is_enabled` 的环境变量语义）；
3. 插件包校验（`read_archive_manifest` 的包结构、`install_entry` 的大小/sha256/manifest 一致性）；
4. HTTP 契约（`GET /api/desktop/plugin-market`、`POST /api/desktop/plugin-market/install` 的状态码与副作用）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_zip, seed_plugin
from desktop_app import market
from desktop_app.manager import PluginManager
from desktop_app.plugin_config import PluginConfigStore
from desktop_app.server import create_app


def _write_index(index_path: Path, plugins: list[dict]) -> Path:
    payload = {"version": 1, "plugins": plugins}
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return index_path


def _plugin_zip(tmp_path: Path, plugin_id: str = "market-demo", version: str = "0.1.0") -> Path:
    """构造一个合法插件包（根目录 manifest.json + index.html）。"""
    manifest = {
        "id": plugin_id,
        "name": "市场演示",
        "version": version,
        "description": "从市场安装的演示插件",
        "entry": "index.html",
        "permissions": ["settings"],
    }
    return make_zip(
        tmp_path / f"{plugin_id}-{version}.zip",
        {"manifest.json": json.dumps(manifest, ensure_ascii=False), "index.html": "<h1>market</h1>"},
    )


def _entry(zip_path: Path, plugin_id: str = "market-demo", version: str = "0.1.0", **overrides) -> dict:
    data = zip_path.read_bytes()
    entry = {
        "id": plugin_id,
        "name": "市场演示",
        "version": version,
        "description": "从市场安装的演示插件",
        "download": f"file://{zip_path}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "permissions": ["settings"],
    }
    entry.update(overrides)
    return entry


def _client(env: dict) -> TestClient:
    """隔离环境下的 TestClient：插件目录与配置存储都落在 tmp 目录。"""
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    config = PluginConfigStore(env["state"].parent / "plugin-config")
    return TestClient(create_app(manager, dev_agent_enabled=False, plugin_config=config))


@pytest.fixture(autouse=True)
def isolated_market(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """每个用例都清缓存，并把索引地址指向 tmp 下的 index.json。"""
    market.clear_cache()
    index_path = tmp_path / "index.json"
    monkeypatch.setenv(market.MARKET_ENV, f"file://{index_path}")
    monkeypatch.delenv(market.MARKET_DISABLE_ENV, raising=False)
    yield index_path
    market.clear_cache()


# ---------- 1. 索引解析与校验 ----------


def test_parse_index_valid(tmp_path: Path) -> None:
    zip_path = _plugin_zip(tmp_path)
    entry = _entry(zip_path)
    entry["sha256"] = entry["sha256"].upper()
    entries = market.parse_index(json.dumps({"version": 1, "plugins": [entry]}))
    assert len(entries) == 1
    parsed = entries[0]
    assert parsed.id == "market-demo"
    assert parsed.sha256 == entry["sha256"].lower()
    assert parsed.size == len(zip_path.read_bytes())
    assert parsed.permissions == ("settings",)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda e: {"version": 2, "plugins": [e]}, id="索引版本不支持"),
        pytest.param(lambda e: {"version": 1}, id="缺少plugins"),
        pytest.param(lambda e: {"version": 1, "plugins": "x"}, id="plugins非数组"),
        pytest.param(lambda e: {"version": 1, "plugins": [{**e, "sha256": "zz"}]}, id="sha256非十六进制"),
        pytest.param(lambda e: {"version": 1, "plugins": [{**e, "id": "Bad/Id"}]}, id="插件id非法"),
        pytest.param(lambda e: {"version": 1, "plugins": [{**e, "version": ""}]}, id="版本为空"),
        pytest.param(lambda e: {"version": 1, "plugins": [{**e, "size": True}]}, id="size是布尔"),
        pytest.param(lambda e: {"version": 1, "plugins": [{**e, "permissions": "x"}]}, id="permissions非数组"),
        pytest.param(
            lambda e: {"version": 1, "plugins": [e, {**e, "name": "重复"}]}, id="插件id重复"
        ),
    ],
)
def test_parse_index_rejects_invalid(tmp_path: Path, mutate) -> None:
    zip_path = _plugin_zip(tmp_path)
    payload = mutate(_entry(zip_path))
    with pytest.raises(market.MarketValidationError):
        market.parse_index(json.dumps(payload, ensure_ascii=False))


def test_parse_index_rejects_external_http(tmp_path: Path) -> None:
    zip_path = _plugin_zip(tmp_path)
    entry = _entry(zip_path, download="http://example.com/plugin.zip")
    with pytest.raises(market.MarketValidationError, match="https"):
        market.parse_index(json.dumps({"version": 1, "plugins": [entry]}))


def test_parse_index_allows_loopback_http(tmp_path: Path) -> None:
    zip_path = _plugin_zip(tmp_path)
    entry = _entry(zip_path, download="http://127.0.0.1:9/plugin.zip")
    entries = market.parse_index(json.dumps({"version": 1, "plugins": [entry]}))
    assert entries[0].download == "http://127.0.0.1:9/plugin.zip"


# ---------- 2. 缓存与开关 ----------


def test_fetch_index_uses_cache_until_refresh(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path)])

    assert len(market.fetch_index()) == 1
    _write_index(index_path, [{**_entry(zip_path), "id": "market-demo"}, {**_entry(zip_path), "id": "other-demo"}])
    assert len(market.fetch_index()) == 1, "5 分钟内应命中缓存"
    assert len(market.fetch_index(refresh=True)) == 2


def test_is_enabled_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(market.MARKET_DISABLE_ENV, raising=False)
    assert market.is_enabled() is True
    monkeypatch.setenv(market.MARKET_DISABLE_ENV, "0")
    assert market.is_enabled() is False
    monkeypatch.setenv(market.MARKET_DISABLE_ENV, "off")
    assert market.is_enabled() is False
    monkeypatch.setenv(market.MARKET_DISABLE_ENV, "1")
    assert market.is_enabled() is True


# ---------- 3. 插件包校验 ----------


def test_read_archive_manifest_accepts_root_and_wrapper(tmp_path: Path) -> None:
    root_zip = _plugin_zip(tmp_path, "root-demo")
    assert market.read_archive_manifest(root_zip.read_bytes())["id"] == "root-demo"

    wrapped = make_zip(
        tmp_path / "wrapped.zip",
        {"manifest.json": json.dumps({"id": "Wrapped".lower(), "version": "0.1.0"}), "index.html": "x"},
        wrapper_dir="plugins/wrapped-demo",
    )
    assert market.read_archive_manifest(wrapped.read_bytes())["id"] == "wrapped"


def test_read_archive_manifest_rejects_bad_archive(tmp_path: Path) -> None:
    with pytest.raises(market.MarketValidationError, match="不是有效的 zip"):
        market.read_archive_manifest(b"not a zip")

    no_manifest = make_zip(tmp_path / "no-manifest.zip", {"index.html": "x"})
    with pytest.raises(market.MarketValidationError, match="manifest.json"):
        market.read_archive_manifest(no_manifest.read_bytes())


def test_install_entry_rejects_size_mismatch(plugin_env: dict, tmp_path: Path) -> None:
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    zip_path = _plugin_zip(tmp_path)
    entry = market.MarketEntry(
        id="market-demo",
        name="市场演示",
        version="0.1.0",
        download=f"file://{zip_path}",
        sha256=hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        size=1,
    )
    with pytest.raises(market.MarketValidationError, match="大小与索引不一致"):
        market.install_entry(manager, entry)


# ---------- 4. HTTP 契约 ----------


def test_market_endpoint_lists_entries(plugin_env: dict, tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path)])

    response = _client(plugin_env).get("/api/desktop/plugin-market")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["source"] == f"file://{index_path}"
    assert [item["id"] for item in body["plugins"]] == ["market-demo"]
    assert body["plugins"][0]["size"] == len(zip_path.read_bytes())
    # 内置 hello-world 已安装，市场里的 market-demo 未安装
    assert body["installed"] == {"hello-world": "0.1.0"}


def test_market_endpoint_reports_disabled(plugin_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(market.MARKET_DISABLE_ENV, "0")
    body = _client(plugin_env).get("/api/desktop/plugin-market").json()
    assert body == {"enabled": False, "source": "", "plugins": [], "installed": {"hello-world": "0.1.0"}}


def test_market_endpoint_reports_missing_index(plugin_env: dict) -> None:
    response = _client(plugin_env).get("/api/desktop/plugin-market")
    assert response.status_code == 502
    assert "插件索引" in response.json()["detail"]


def test_market_endpoint_reports_invalid_index(plugin_env: dict, tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text('{"version": 9, "plugins": []}', encoding="utf-8")
    response = _client(plugin_env).get("/api/desktop/plugin-market")
    assert response.status_code == 400
    assert "索引版本" in response.json()["detail"]


def test_market_install_success(plugin_env: dict, tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path)])
    client = _client(plugin_env)

    response = client.post("/api/desktop/plugin-market/install", json={"id": "market-demo"})
    assert response.status_code == 200
    plugin = response.json()["plugin"]
    assert plugin["id"] == "market-demo"
    assert plugin["version"] == "0.1.0"
    assert (plugin_env["user"] / "market-demo" / "manifest.json").is_file()
    # 装完再拉列表，installed 里应出现该插件
    installed = client.get("/api/desktop/plugin-market").json()["installed"]
    assert installed == {"hello-world": "0.1.0", "market-demo": "0.1.0"}


def test_market_install_rejects_sha_mismatch(plugin_env: dict, tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path, sha256="0" * 64)])

    response = _client(plugin_env).post("/api/desktop/plugin-market/install", json={"id": "market-demo"})
    assert response.status_code == 400
    assert "sha256 校验失败" in response.json()["detail"]
    assert not (plugin_env["user"] / "market-demo").exists()


def test_market_install_rejects_manifest_id_mismatch(plugin_env: dict, tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path, plugin_id="other-demo")
    _write_index(index_path, [_entry(zip_path)])

    response = _client(plugin_env).post("/api/desktop/plugin-market/install", json={"id": "market-demo"})
    assert response.status_code == 400
    assert "manifest id" in response.json()["detail"]


def test_market_install_unknown_id(plugin_env: dict, tmp_path: Path) -> None:
    _write_index(tmp_path / "index.json", [])
    response = _client(plugin_env).post("/api/desktop/plugin-market/install", json={"id": "nope"})
    assert response.status_code == 404
    assert "市场里没有插件" in response.json()["detail"]


def test_market_install_twice_returns_conflict(plugin_env: dict, tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path)])
    client = _client(plugin_env)

    assert client.post("/api/desktop/plugin-market/install", json={"id": "market-demo"}).status_code == 200
    second = client.post("/api/desktop/plugin-market/install", json={"id": "market-demo"})
    assert second.status_code == 409


def test_market_install_works_for_disabled_plugin(plugin_env: dict, tmp_path: Path) -> None:
    """装过的插件被停用后不应算「已安装冲突」之外的事，这里只确认列表不受 enabled 影响。"""
    index_path = tmp_path / "index.json"
    zip_path = _plugin_zip(tmp_path)
    _write_index(index_path, [_entry(zip_path)])
    client = _client(plugin_env)
    client.post("/api/desktop/plugin-market/install", json={"id": "market-demo"})
    client.patch("/api/desktop/plugins/market-demo", json={"enabled": False})
    assert client.get("/api/desktop/plugin-market").json()["installed"]["market-demo"] == "0.1.0"


def test_seed_plugin_is_listed_as_installed(plugin_env: dict) -> None:
    """内置 + 用户插件都计入 installed（市场用它判断「已安装」）。"""
    seed_plugin(plugin_env["user"], "market-demo", "市场演示")
    _write_index(
        plugin_env["state"].parent / "index.json",
        [
            {
                "id": "market-demo",
                "name": "市场演示",
                "version": "0.1.0",
                "download": "https://example.com/x.zip",
                "sha256": "a" * 64,
            }
        ],
    )
    body = _client(plugin_env).get("/api/desktop/plugin-market").json()
    assert body["installed"]["market-demo"] == "0.1.0"
