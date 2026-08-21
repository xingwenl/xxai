"""插件管理测试：zip 安装、卸载、启停与状态持久化。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_zip
from desktop_app.manager import PluginError, PluginExistsError, PluginManager


def _manager(env: dict) -> PluginManager:
    return PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )


def test_install_zip_with_wrapped_dir(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    src = make_zip(
        tmp_path / "plugin.zip",
        {
            "manifest.json": '{"id": "demo-app", "name": "演示应用", "version": "1.0.0", "entry": "index.html"}',
            "index.html": "<h1>demo</h1>",
        },
        wrapper_dir="demo-app",
    )
    plugin = manager.install_zip(src)
    assert plugin.id == "demo-app"
    assert plugin.builtin is False
    assert plugin.enabled is True
    assert (plugin_env["user"] / "demo-app" / "index.html").is_file()
    assert plugin_env["state"].is_file()
    # 重新创建 manager（模拟重启）后状态保持
    assert _manager(plugin_env).get("demo-app").enabled is True


def test_install_zip_manifest_at_root(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    src = make_zip(
        tmp_path / "flat.zip",
        {
            "manifest.json": '{"id": "flat-app", "name": "平铺应用", "version": "0.1.0"}',
            "index.html": "<h1>flat</h1>",
        },
    )
    plugin = manager.install_zip(src)
    assert plugin.id == "flat-app"


def test_duplicate_install_rejected(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    # 内置插件 hello-world 已存在，用户再装同 id 应拒绝
    src = make_zip(
        tmp_path / "dup.zip",
        {
            "manifest.json": '{"id": "hello-world", "name": "重复", "version": "0.1.0"}',
            "index.html": "<h1>x</h1>",
        },
        wrapper_dir="hello-world",
    )
    with pytest.raises(PluginExistsError):
        manager.install_zip(src)


def test_install_invalid_manifest_rejected(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    src = make_zip(
        tmp_path / "bad.zip",
        {"manifest.json": '{"id": "bad id", "name": "x", "version": "1"}', "index.html": "<h1>x</h1>"},
        wrapper_dir="bad",
    )
    with pytest.raises(PluginError):
        manager.install_zip(src)


def test_install_missing_manifest_rejected(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    src = make_zip(tmp_path / "no-manifest.zip", {"index.html": "<h1>x</h1>"}, wrapper_dir="x")
    with pytest.raises(PluginError, match="manifest"):
        manager.install_zip(src)


def test_uninstall(plugin_env: dict, tmp_path: Path) -> None:
    manager = _manager(plugin_env)
    src = make_zip(
        tmp_path / "u.zip",
        {"manifest.json": '{"id": "u-app", "name": "U", "version": "1"}', "index.html": "<h1>u</h1>"},
        wrapper_dir="u-app",
    )
    manager.install_zip(src)
    manager.uninstall("u-app")
    assert not (plugin_env["user"] / "u-app").exists()
    ids = [p.id for p in manager.list_plugins()]
    assert "u-app" not in ids


def test_uninstall_builtin_rejected(plugin_env: dict) -> None:
    manager = _manager(plugin_env)
    with pytest.raises(PluginError, match="内置"):
        manager.uninstall("hello-world")


def test_set_enabled_persists(plugin_env: dict) -> None:
    manager = _manager(plugin_env)
    manager.set_enabled("hello-world", False)
    assert manager.get("hello-world").enabled is False
    # 新实例（模拟重启）读取 state 后仍为停用
    assert _manager(plugin_env).get("hello-world").enabled is False


def test_install_broken_user_dir_listed(plugin_env: dict) -> None:
    broken = plugin_env["user"] / "broken-app"
    broken.mkdir()
    (broken / "index.html").write_text("x")
    manager = _manager(plugin_env)
    plugin = manager.get("broken-app")
    assert plugin.error is not None
    assert plugin.enabled is False  # 异常插件不可用
