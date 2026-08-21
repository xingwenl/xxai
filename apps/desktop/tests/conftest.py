"""共享测试夹具与工具函数：隔离的插件目录环境与 zip 构造。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest


def seed_plugin(root: Path, plugin_id: str = "hello-world", name: str = "你好世界", **overrides) -> Path:
    """在 root 下创建最小合法插件目录。"""
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_id,
        "name": name,
        "version": "0.1.0",
        "description": "测试插件",
        "icon": "icon.svg",
        "entry": "index.html",
        "permissions": ["notify", "settings"],
    }
    manifest.update(overrides)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (plugin_dir / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")
    (plugin_dir / "icon.svg").write_text("<svg/>", encoding="utf-8")
    return plugin_dir


def make_zip(zip_path: Path, files: dict[str, str], wrapper_dir: str | None = None) -> Path:
    """按 files（arcname -> 内容）构造 zip；wrapper_dir 可把全部条目包进一个目录。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            arc = f"{wrapper_dir}/{name}" if wrapper_dir else name
            zf.writestr(arc, content.encode("utf-8"))
    return zip_path


@pytest.fixture
def plugin_env(tmp_path: Path) -> dict:
    """返回隔离的测试环境：内置目录、用户目录、状态文件路径。"""
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    state = tmp_path / "state.json"
    builtin.mkdir()
    user.mkdir()
    seed_plugin(builtin, "hello-world", "你好世界")
    return {"builtin": builtin, "user": user, "state": state}
