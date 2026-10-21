"""开发热重载指纹与 dashboard 权限白名单测试。

覆盖三层：
1. `dev_reload` 的开关解析与插件目录指纹（只受文件路径/mtime/大小影响）；
2. `GET /api/desktop/plugin-revision` 的开关门控与按插件定位；
3. `manifest.permissions` 的 `dashboard` 白名单。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import seed_plugin
from desktop_app import dev_reload
from desktop_app.manager import PluginManager
from desktop_app.protocol import KNOWN_PERMISSIONS, PluginManifest
from desktop_app.server import create_app


def _client(env: dict) -> TestClient:
    """用隔离的插件目录构造测试客户端（与 test_plugin_config 同形态）。"""
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    return TestClient(create_app(manager))


def _touch_forward(path: Path) -> None:
    """把文件 mtime 显式推后 1 毫秒，避免同一次写入内 mtime 分辨率不足导致指纹不变。"""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_is_enabled_accepts_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, value)
    assert dev_reload.is_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no"])
def test_is_enabled_rejects_other_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, value)
    assert dev_reload.is_enabled() is False


def test_is_enabled_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(dev_reload.DEV_RELOAD_ENV, raising=False)
    assert dev_reload.is_enabled() is False


def test_revision_endpoint_disabled_by_default(monkeypatch: pytest.MonkeyPatch, plugin_env: dict) -> None:
    """未开启开发热重载时端点只返回 enabled=false，不暴露插件清单与指纹。"""
    monkeypatch.delenv(dev_reload.DEV_RELOAD_ENV, raising=False)
    response = _client(plugin_env).get("/api/desktop/plugin-revision")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "revision": "", "plugins": {}}


def test_revision_endpoint_lists_plugins_when_enabled(
    monkeypatch: pytest.MonkeyPatch, plugin_env: dict
) -> None:
    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, "1")
    seed_plugin(plugin_env["user"], "second", "第二插件")
    body = _client(plugin_env).get("/api/desktop/plugin-revision").json()

    assert body["enabled"] is True
    assert set(body["plugins"]) == {"hello-world", "second"}
    assert body["revision"]
    assert all(len(digest) == dev_reload.DIGEST_LENGTH for digest in body["plugins"].values())


def test_revision_changes_only_for_touched_plugin(monkeypatch: pytest.MonkeyPatch, plugin_env: dict) -> None:
    """改一个插件的文件只让该插件的指纹变化，其它插件与整体 revision 则各自更新。"""
    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, "1")
    seed_plugin(plugin_env["user"], "second", "第二插件")
    client = _client(plugin_env)

    before = client.get("/api/desktop/plugin-revision").json()
    index = plugin_env["builtin"] / "hello-world" / "index.html"
    index.write_text("<h1>changed</h1>", encoding="utf-8")
    _touch_forward(index)
    after = client.get("/api/desktop/plugin-revision").json()

    assert after["plugins"]["hello-world"] != before["plugins"]["hello-world"]
    assert after["plugins"]["second"] == before["plugins"]["second"]
    assert after["revision"] != before["revision"]


def test_ignored_dirs_do_not_change_revision(monkeypatch: pytest.MonkeyPatch, plugin_env: dict) -> None:
    """依赖、字节码、版本库与构建产物目录里的改动不算插件变更。"""
    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, "1")
    client = _client(plugin_env)
    before = client.get("/api/desktop/plugin-revision").json()

    plugin_dir = plugin_env["builtin"] / "hello-world"
    for relative in ("node_modules/pkg/index.js", "__pycache__/x.pyc", ".git/HEAD", "dist/bundle.js"):
        target = plugin_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("noise", encoding="utf-8")

    after = client.get("/api/desktop/plugin-revision").json()
    assert after["revision"] == before["revision"]


def test_settings_exposes_dev_reload_flag(monkeypatch: pytest.MonkeyPatch, plugin_env: dict) -> None:
    client = _client(plugin_env)

    monkeypatch.delenv(dev_reload.DEV_RELOAD_ENV, raising=False)
    assert client.get("/api/desktop/settings").json()["devReload"] is False

    monkeypatch.setenv(dev_reload.DEV_RELOAD_ENV, "1")
    assert client.get("/api/desktop/settings").json()["devReload"] is True


def test_dashboard_is_known_permission() -> None:
    """dashboard 进入权限白名单后，声明它的 manifest 不再产生未知权限警告。"""
    assert "dashboard" in KNOWN_PERMISSIONS
    manifest = PluginManifest.model_validate(
        {
            "id": "demo",
            "name": "演示",
            "version": "0.1.0",
            "description": "",
            "icon": "icon.svg",
            "entry": "index.html",
            "permissions": ["dashboard", "notify"],
        }
    )
    assert manifest.unknown_permissions() == []
