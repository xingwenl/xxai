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
