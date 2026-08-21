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


def test_react_builtin_without_entry_scanned(plugin_env: dict) -> None:
    """react 类型子应用不要求 iframe 入口页面，仍应出现在列表中。"""
    react_dir = plugin_env["builtin"] / "native-app"
    react_dir.mkdir()
    (react_dir / "manifest.json").write_text(
        '{"id": "native-app", "name": "原生应用", "version": "1.0.0", "type": "react"}',
        encoding="utf-8",
    )
    (react_dir / "icon.svg").write_text("<svg/>", encoding="utf-8")
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], {"plugins": {}})
    plugins = {p.id: p for p in registry.scan()}
    assert plugins["native-app"].type == "react"
    assert plugins["native-app"].error is None


def test_iframe_without_entry_rejected(plugin_env: dict) -> None:
    """iframe 类型缺少入口页面仍应视为非法并跳过。"""
    broken_dir = plugin_env["builtin"] / "no-entry"
    broken_dir.mkdir()
    (broken_dir / "manifest.json").write_text(
        '{"id": "no-entry", "name": "缺入口", "version": "1.0.0"}',
        encoding="utf-8",
    )
    registry = PluginRegistry(plugin_env["builtin"], plugin_env["user"], {"plugins": {}})
    ids = [p.id for p in registry.scan()]
    assert "no-entry" not in ids


def test_missing_dirs_scan_empty(tmp_path: Path) -> None:
    registry = PluginRegistry(tmp_path / "no-builtin", tmp_path / "no-user", {"plugins": {}})
    assert registry.scan() == []
