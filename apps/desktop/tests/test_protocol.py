"""插件 manifest 协议校验测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from desktop_app.protocol import PluginManifest


def _manifest(**overrides) -> dict:
    base = {
        "id": "hello-world",
        "name": "你好世界",
        "version": "0.1.0",
        "icon": "icon.svg",
        "entry": "index.html",
        "permissions": ["notify", "settings"],
    }
    base.update(overrides)
    return base


def test_valid_manifest() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    assert manifest.id == "hello-world"
    assert manifest.unknown_permissions() == []
    # type 默认 iframe，向后兼容三方 zip 应用
    assert manifest.type == "iframe"


def test_react_type_accepted() -> None:
    manifest = PluginManifest.model_validate(_manifest(type="react"))
    assert manifest.type == "react"


def test_remote_type_requires_http_url() -> None:
    manifest = PluginManifest.model_validate(_manifest(type="remote", url="https://example.com/"))
    assert manifest.type == "remote"
    assert manifest.url == "https://example.com/"


def test_remote_type_rejects_missing_url() -> None:
    with pytest.raises(ValidationError, match="url"):
        PluginManifest.model_validate(_manifest(type="remote"))


def test_remote_type_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError, match="http"):
        PluginManifest.model_validate(_manifest(type="remote", url="ftp://example.com/"))


def test_local_type_rejects_url() -> None:
    with pytest.raises(ValidationError, match="remote"):
        PluginManifest.model_validate(_manifest(type="iframe", url="https://example.com/"))


@pytest.mark.parametrize("bad_type", ["native", "webview", ""])
def test_invalid_type_rejected(bad_type: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(type=bad_type))


@pytest.mark.parametrize(
    "plugin_id",
    ["Bad ID", "-abc", "a/b", "中文字符", "has space"],
)
def test_invalid_id_rejected(plugin_id: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(id=plugin_id))


@pytest.mark.parametrize(
    "entry",
    ["../evil.html", "/etc/passwd", "a/../../evil.html", "", "..\\evil.html"],
)
def test_entry_traversal_rejected(entry: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(entry=entry))


def test_unknown_permissions_reported() -> None:
    manifest = PluginManifest.model_validate(_manifest(permissions=["notify", "future-ability"]))
    assert manifest.unknown_permissions() == ["future-ability"]


def test_open_mode_defaults_to_inline() -> None:
    # 未声明 open_mode 的老插件必须保持原有行为（壳内展开）
    manifest = PluginManifest.model_validate(_manifest())
    assert manifest.open_mode == "inline"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("window", "window"), ("browser", "browser"), ("inline", "inline"), (" Window ", "window"), ("BROWSER", "browser")],
)
def test_open_mode_accepts_known_values(raw: str, expected: str) -> None:
    manifest = PluginManifest.model_validate(_manifest(open_mode=raw))
    assert manifest.open_mode == expected


@pytest.mark.parametrize("bad", ["newwindow", "popup", "1", "", None, 123, ["window"]])
def test_open_mode_falls_back_to_inline_on_invalid_value(bad: object) -> None:
    # 宽容策略：open_mode 只是展示策略，写错不该让插件装不上
    manifest = PluginManifest.model_validate(_manifest(open_mode=bad))
    assert manifest.open_mode == "inline"

