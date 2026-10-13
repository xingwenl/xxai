"""宿主桥（pywebview js_api）能力测试。"""

from __future__ import annotations

import sys

import pytest

from desktop_app.host_api import HostApi
from desktop_app.manager import PluginManager
from desktop_app.windows import AppWindowManager

from conftest import seed_plugin

BASE_URL = "http://127.0.0.1:8765"


def _api(plugin_env: dict, **kwargs) -> tuple[HostApi, list]:
    """构造 HostApi：用替身窗口管理器，避免测试里真开窗口。"""
    created: list = []
    windows = AppWindowManager(create_window=lambda title, **options: created.append((title, options)) or _FakeWindow())
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    return HostApi(manager, base_url=BASE_URL, windows=windows, **kwargs), created


class _FakeWindow:
    """只用于让复用分支拿到一个可调用对象的最小替身。"""

    def show(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def destroy(self) -> None:
        pass


def test_open_urls_filters_non_http(plugin_env: dict, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("desktop_app.host_api.webbrowser.open", lambda url, new: opened.append(url))
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    api = HostApi(manager)

    result = api.open_urls(
        [
            "https://example.com/a",
            "http://example.com/b",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "not-a-url",
            123,
        ]
    )
    assert result == {"opened": 2, "failed": 0}
    assert opened == ["https://example.com/a", "http://example.com/b"]


def test_open_app_defaults_to_inline_without_touching_windows(plugin_env: dict) -> None:
    api, created = _api(plugin_env)

    result = api.open_app("hello-world")

    # inline 由前端自己展开视图，后端只回执，不能抢着建窗
    assert result == {"ok": True, "mode": "inline", "target": None, "reused": False}
    assert created == []


def test_open_app_window_mode_creates_child_window_with_bridge(plugin_env: dict) -> None:
    api, created = _api(plugin_env)

    result = api.open_app("hello-world", "window")

    assert result["ok"] is True
    assert result["mode"] == "window"
    assert result["target"] == f"{BASE_URL}/?child=1#/app/hello-world"
    title, options = created[0]
    assert title == "你好世界"
    assert options["url"] == result["target"]
    # 子窗口必须带上同一个宿主桥，否则壳里的插件拿不到 SDK
    assert options["js_api"] is api


def test_open_app_mode_override_beats_manifest(plugin_env: dict) -> None:
    seed_plugin(plugin_env["builtin"], "native-app", "原生窗口应用", open_mode="window")
    api, created = _api(plugin_env)

    assert api.open_app("native-app")["mode"] == "window"
    assert len(created) == 1
    # 显式 mode 覆盖插件声明
    assert api.open_app("native-app", "inline")["mode"] == "inline"
    assert len(created) == 1


def test_open_app_browser_mode_uses_system_browser(plugin_env: dict, monkeypatch) -> None:
    opened: list[str] = []

    def _browser(url: str, new: int = 0) -> bool:
        opened.append(url)
        return True

    # 非 macOS 平台没有专用启动器（返回 None），走 webbrowser；
    # 真机上真实的 http URL 会真的弹出浏览器标签页，这里整条替换掉
    monkeypatch.setattr("desktop_app.host_api._macos_open", lambda target, timeout=5.0: None)
    monkeypatch.setattr("desktop_app.host_api.webbrowser.open", _browser)
    api, created = _api(plugin_env)

    result = api.open_app("hello-world", "browser")

    assert result["ok"] is True
    assert result["mode"] == "browser"
    # 浏览器标签页不是原生窗口：深链不带 child=1，Esc / 返回 应退回应用列表
    assert opened == [f"{BASE_URL}/#/app/hello-world"]
    assert created == []


def test_open_app_browser_mode_prefers_macos_opener(plugin_env: dict, monkeypatch) -> None:
    calls: list[str] = []

    def _opener(target: str, timeout: float = 5.0) -> bool:
        calls.append(target)
        return True

    monkeypatch.setattr("desktop_app.host_api._macos_open", _opener)
    monkeypatch.setattr(
        "desktop_app.host_api.webbrowser.open",
        lambda url, new: pytest.fail("macOS 启动器已成功时不应再走 webbrowser"),
    )
    api, _created = _api(plugin_env)

    assert api.open_app("hello-world", "browser")["ok"] is True
    assert calls == [f"{BASE_URL}/#/app/hello-world"]


def test_open_app_browser_mode_reports_launch_failure(plugin_env: dict, monkeypatch) -> None:
    opened: list[str] = []

    def _browser(url: str, new: int = 0) -> bool:
        opened.append(url)
        return True

    # macOS 启动器已经明确失败，就不再退到 osascript 实现（它本来就会静默失败）
    monkeypatch.setattr("desktop_app.host_api._macos_open", lambda target, timeout=5.0: False)
    monkeypatch.setattr("desktop_app.host_api.webbrowser.open", _browser)
    api, _created = _api(plugin_env)

    result = api.open_app("hello-world", "browser")

    # 打不开浏览器就不能谎报成功，前端要据此提示用户
    assert result["ok"] is False
    assert result["mode"] == "browser"
    assert result["reason"] == "browser_failed"
    assert opened == []


def test_macos_open_detects_unregistered_scheme(monkeypatch) -> None:
    """真机验证系统启动器：未知协议必须返回 False，而不是静默成功。"""
    if sys.platform != "darwin":
        pytest.skip("仅在 macOS 上验证 open 命令")
    from desktop_app import host_api

    assert host_api._macos_open("dsh-probe://no-such-handler") is False


def test_open_app_remote_plugin_opens_own_url_without_bridge(plugin_env: dict) -> None:
    seed_plugin(plugin_env["builtin"], "remote-app", "远程应用", type="remote", url="https://example.com/app/")
    api, created = _api(plugin_env)

    result = api.open_app("remote-app", "window")

    # 远程插件是外部站点：目标用它自己的 url，并且绝不能拿到宿主桥
    assert result["target"] == "https://example.com/app/"
    assert created[0][1]["url"] == "https://example.com/app/"
    assert created[0][1]["js_api"] is None


def test_open_app_unknown_id_reports_reason(plugin_env: dict) -> None:
    api, created = _api(plugin_env)

    result = api.open_app("not-installed", "window")

    assert result["ok"] is False
    assert result["reason"] == "not_found"
    assert created == []


def test_open_app_requires_base_url_for_deeplink(plugin_env: dict) -> None:
    windows = AppWindowManager(create_window=lambda *a, **kw: _FakeWindow())
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    api = HostApi(manager, base_url="", windows=windows)

    assert api.open_app("hello-world", "window")["reason"] == "no_base_url"


def test_close_current_window_only_affects_child(plugin_env: dict, monkeypatch) -> None:
    api, created = _api(plugin_env)
    api.open_app("hello-world", "window")
    child = api._windows._windows["hello-world"]
    master = _FakeWindow()

    monkeypatch.setattr("desktop_app.host_api.webview.active_window", lambda: master)
    assert api.close_current_window() is False

    # 换回子窗口：closed 事件与真实窗口一致，close 后注册表应清空
    monkeypatch.setattr("desktop_app.host_api.webview.active_window", lambda: child)
    assert api.close_current_window() is True
    assert api._windows.app_ids == []
    assert created  # 至少建过一个窗口
