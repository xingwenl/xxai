"""宿主桥（pywebview js_api）能力测试。"""

from __future__ import annotations

from desktop_app.host_api import HostApi
from desktop_app.manager import PluginManager


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
