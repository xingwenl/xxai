"""子应用数据存储（plugin-data）：磁盘语义与宿主接口测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import seed_plugin
from desktop_app.manager import PluginManager
from desktop_app.plugin_data import (
    MAX_VALUE_BYTES,
    InvalidPluginDataKey,
    PluginDataStore,
    PluginDataTooLarge,
)
from desktop_app.server import create_app


def _store(tmp_path: Path) -> PluginDataStore:
    return PluginDataStore(root=tmp_path / "plugin-data")


def _client(plugin_env: dict, tmp_path: Path, dev_agent_enabled: bool = False) -> TestClient:
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    app = create_app(
        manager,
        plugin_data=_store(tmp_path),
        dev_agent_enabled=dev_agent_enabled,
    )
    return TestClient(app)


# ---------- 存储层 ----------


def test_store_roundtrip_and_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.read_raw("ledger", "ledger") is None

    store.write("ledger", "ledger", {"entries": [], "version": 1})
    assert json.loads(store.read_raw("ledger", "ledger")) == {"entries": [], "version": 1}

    store.write("ledger", "ledger", {"entries": [{"amount_cents": 3500}]})
    assert json.loads(store.read_raw("ledger", "ledger"))["entries"][0]["amount_cents"] == 3500


def test_store_null_value_is_not_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("ledger", "null-key", None)
    raw = store.read_raw("ledger", "null-key")
    assert raw is not None
    assert json.loads(raw) is None


def test_store_isolated_per_plugin(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("ledger", "shared", {"owner": "ledger"})
    store.write("bookmarks-organizer", "shared", {"owner": "bookmarks"})
    assert json.loads(store.read_raw("ledger", "shared"))["owner"] == "ledger"
    assert json.loads(store.read_raw("bookmarks-organizer", "shared"))["owner"] == "bookmarks"
    assert store.keys("ledger") == ["shared"]


def test_store_keys_and_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("ledger", "b", 1)
    store.write("ledger", "a", 2)
    assert store.keys("ledger") == ["a", "b"]
    assert store.delete("ledger", "a") is True
    assert store.delete("ledger", "a") is False
    assert store.keys("ledger") == ["b"]


def test_store_keys_ignores_unrelated_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("ledger", "data", 1)
    plugin_dir = store.plugin_dir("ledger")
    (plugin_dir / "notes.txt").write_text("不是数据文件", encoding="utf-8")
    (plugin_dir / "bad name.json").write_text("{}", encoding="utf-8")
    (plugin_dir / ".hidden.json").write_text("{}", encoding="utf-8")
    assert store.keys("ledger") == ["data"]


def test_store_persists_across_instances(tmp_path: Path) -> None:
    _store(tmp_path).write("ledger", "ledger", {"entries": []})
    reloaded = PluginDataStore(root=tmp_path / "plugin-data")
    assert json.loads(reloaded.read_raw("ledger", "ledger")) == {"entries": []}


@pytest.mark.parametrize("key", ["", " ", ".hidden", "bad key", "../escape", "a" * 65])
def test_store_rejects_invalid_key(tmp_path: Path, key: str) -> None:
    with pytest.raises(InvalidPluginDataKey):
        _store(tmp_path).write("ledger", key, {})


@pytest.mark.parametrize("plugin_id", ["../escape", "Ledger", "记账", ""])
def test_store_rejects_invalid_plugin_id(tmp_path: Path, plugin_id: str) -> None:
    with pytest.raises(InvalidPluginDataKey):
        _store(tmp_path).plugin_dir(plugin_id)


def test_store_rejects_too_large_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(PluginDataTooLarge):
        store.write("ledger", "big", "x" * (MAX_VALUE_BYTES + 1))
    assert store.read_raw("ledger", "big") is None


# ---------- 宿主接口 ----------


def test_plugin_data_requires_storage_permission(plugin_env: dict, tmp_path: Path) -> None:
    # conftest 预置的 hello-world 只声明 notify/settings
    resp = _client(plugin_env, tmp_path).get("/api/desktop/plugin-data/hello-world")
    assert resp.status_code == 403
    assert "storage" in resp.json()["detail"]


def test_plugin_data_api_roundtrip(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "ledger", "记账", permissions=["storage", "tools", "notify"])
    client = _client(plugin_env, tmp_path)

    payload = {"version": 1, "entries": [{"id": "e1", "amount_cents": 3500}]}
    written = client.put("/api/desktop/plugin-data/ledger/ledger", json=payload)
    assert written.status_code == 200
    assert written.json() == {"ok": True}

    read = client.get("/api/desktop/plugin-data/ledger/ledger")
    assert read.status_code == 200
    assert read.headers["content-type"].startswith("application/json")
    assert read.json() == payload

    keys = client.get("/api/desktop/plugin-data/ledger")
    assert keys.status_code == 200
    assert keys.json() == {"keys": ["ledger"]}

    # 落盘位置：<root>/<plugin_id>/<key>.json
    stored = tmp_path / "plugin-data" / "ledger" / "ledger.json"
    assert json.loads(stored.read_text(encoding="utf-8")) == payload


def test_plugin_data_api_missing_key(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "ledger", "记账", permissions=["storage"])
    client = _client(plugin_env, tmp_path)
    resp = client.get("/api/desktop/plugin-data/ledger/nope")
    assert resp.status_code == 404
    assert "数据不存在" in resp.json()["detail"]


def test_plugin_data_api_delete_is_idempotent(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "ledger", "记账", permissions=["storage"])
    client = _client(plugin_env, tmp_path)
    client.put("/api/desktop/plugin-data/ledger/ledger", json={"entries": []})

    assert client.delete("/api/desktop/plugin-data/ledger/ledger").status_code == 204
    assert client.delete("/api/desktop/plugin-data/ledger/ledger").status_code == 204
    assert client.get("/api/desktop/plugin-data/ledger/ledger").status_code == 404


def test_plugin_data_api_rejects_bad_body(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "ledger", "记账", permissions=["storage"])
    client = _client(plugin_env, tmp_path)

    empty = client.put("/api/desktop/plugin-data/ledger/ledger", content=b"")
    assert empty.status_code == 400

    broken = client.put(
        "/api/desktop/plugin-data/ledger/ledger",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert broken.status_code == 400

    too_large = client.put(
        "/api/desktop/plugin-data/ledger/ledger",
        content=json.dumps("x" * (MAX_VALUE_BYTES + 1)).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert too_large.status_code == 400
    assert "上限" in too_large.json()["detail"]


def test_plugin_data_api_rejects_unknown_or_disabled_plugin(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "ledger", "记账", permissions=["storage"])
    client = _client(plugin_env, tmp_path)

    assert client.get("/api/desktop/plugin-data/not-installed").status_code == 404

    client.patch("/api/desktop/plugins/ledger", json={"enabled": False})
    disabled = client.get("/api/desktop/plugin-data/ledger")
    assert disabled.status_code == 403
    assert "已停用" in disabled.json()["detail"]


def test_agent_config_disabled_by_default(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env, tmp_path)
    data = client.get("/api/desktop/agent-config").json()
    assert data["enabled"] is False
    assert "DESKTOP_DEV_AGENT" in data["reason"]
