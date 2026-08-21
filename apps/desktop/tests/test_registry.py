"""插件注册表扫描测试：内置/用户合并、内置优先与状态合并。"""

from __future__ import annotations

from pathlib import Path

from conftest import seed_plugin
from desktop_app.registry import PluginRegistry


def test_builtin_and_user_merged(plugin_env: dict) -> None:
    seed_plugin(plugin_env["user"], "user-app", "用户应用")
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], {"plugins": {}})
    ids = [p.id for p in registry.scan()]
    assert "hello-world" in ids
    assert "user-app" in ids


def test_builtin_wins_on_conflict(plugin_env: dict) -> None:
    seed_plugin(plugin_env["user"], "hello-world", "用户版")
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], {"plugins": {}})
    plugins = {p.id: p for p in registry.scan()}
    assert plugins["hello-world"].builtin is True
    assert plugins["hello-world"].name == "你好世界"


def test_state_merged(plugin_env: dict) -> None:
    seed_plugin(plugin_env["user"], "user-app", "用户应用")
    state = {"plugins": {"user-app": {"enabled": False, "installedAt": "2026-08-20T00:00:00+00:00"}}}
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], state)
    plugins = {p.id: p for p in registry.scan()}
    assert plugins["user-app"].enabled is False
    assert plugins["user-app"].installed_at == "2026-08-20T00:00:00+00:00"


def test_broken_builtin_skipped(plugin_env: dict) -> None:
    (plugin_env["builtin"] / "bad-builtin").mkdir()
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], {"plugins": {}})
    ids = [p.id for p in registry.scan()]
    assert "bad-builtin" not in ids


def test_missing_dirs_scan_empty(tmp_path: Path) -> None:
    registry = PluginRegistry(tmp_path / "no-builtin", tmp_path / "no-user", {"plugins": {}})
    assert registry.scan() == []
