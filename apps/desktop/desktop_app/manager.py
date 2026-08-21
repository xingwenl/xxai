"""插件管理：zip 安装（受控解压 + 原子落盘）、卸载、启停与状态持久化。"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desktop_app import paths
from desktop_app.registry import PluginInfo, PluginRegistry
from desktop_app.security import MAX_ZIP_SIZE, safe_extract_zip


class PluginError(Exception):
    """插件操作失败（含安全校验失败）。"""


class PluginExistsError(PluginError):
    """插件已存在。"""


class PluginNotFoundError(PluginError):
    """插件不存在。"""


def _normalize_plugin_root(root: Path) -> Path:
    """归一化 zip 解压结果：根含 manifest.json，或根下仅一个含 manifest.json 的目录。"""
    if (root / "manifest.json").is_file():
        return root
    entries = [p for p in root.iterdir() if p.name != "__MACOSX"]
    subdirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    if not files and len(subdirs) == 1 and (subdirs[0] / "manifest.json").is_file():
        return subdirs[0]
    raise PluginError("zip 根目录必须包含 manifest.json，或仅包含一个含 manifest.json 的插件目录")


class PluginManager:
    """统一管理内置与用户插件的安装、启停、卸载与状态。"""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.builtin_dir = Path(builtin_dir) if builtin_dir else paths.builtin_plugins_dir()
        self.user_dir = Path(user_dir) if user_dir else paths.user_plugins_dir()
        self.state_file = Path(state_file) if state_file else paths.state_file()
        self._state = self._load_state()

    # ---------- 状态持久化 ----------

    def _load_state(self) -> dict[str, Any]:
        if self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"plugins": {}}

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 查询 ----------

    def list_plugins(self) -> list[PluginInfo]:
        """返回内置 + 用户插件的合并列表（内置优先）。"""
        return PluginRegistry(self.builtin_dir, self.user_dir, self._state).scan()

    def get(self, plugin_id: str) -> PluginInfo:
        """按 id 查找插件，不存在时抛出 PluginNotFoundError。"""
        for plugin in self.list_plugins():
            if plugin.id == plugin_id:
                return plugin
        raise PluginNotFoundError(f"插件不存在: {plugin_id}")

    # ---------- 安装 / 卸载 / 启停 ----------

    def install_zip(self, zip_path: Path) -> PluginInfo:
        """安装 zip 插件包：受控解压 → 校验 → 原子落盘到用户插件目录。"""
        zip_path = Path(zip_path)
        if zip_path.stat().st_size > MAX_ZIP_SIZE:
            raise PluginError(f"zip 文件超过大小限制（{zip_path.stat().st_size} > {MAX_ZIP_SIZE}）")
        with tempfile.TemporaryDirectory(prefix="desktop-plugin-") as tmp:
            tmp_root = Path(tmp)
            try:
                safe_extract_zip(zip_path, tmp_root)
            except zipfile.BadZipFile as exc:
                raise PluginError("不是有效的 zip 文件") from exc
            except OSError as exc:
                raise PluginError(f"zip 读取失败: {exc}") from exc
            plugin_src = _normalize_plugin_root(tmp_root)
            root_manifest = (tmp_root / "manifest.json").is_file()
            manifest, error = PluginRegistry.load_manifest(
                plugin_src, require_dir_match=not root_manifest
            )
            if manifest is None:
                raise PluginError(error or "manifest 校验失败")
            if any(p.id == manifest.id for p in self.list_plugins()):
                raise PluginExistsError(f"插件已存在: {manifest.id}")
            dest = self.user_dir / manifest.id
            if dest.exists():
                raise PluginExistsError(f"插件目录已存在: {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if plugin_src == tmp_root:
                # manifest 位于 zip 根：以 manifest.id 建目录后整体落入
                dest.mkdir()
                for item in plugin_src.iterdir():
                    shutil.move(str(item), str(dest))
            else:
                # 临时目录与用户插件目录通常同盘，shutil.move 优先走原子 rename
                shutil.move(str(plugin_src), str(dest))
            self._state.setdefault("plugins", {})[manifest.id] = {
                "enabled": True,
                "installedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._save_state()
        return self.get(manifest.id)

    def uninstall(self, plugin_id: str) -> None:
        """卸载用户插件；内置插件禁止卸载。"""
        plugin = self.get(plugin_id)
        if plugin.builtin:
            raise PluginError("内置插件不可卸载")
        shutil.rmtree(plugin.dir)
        self._state.get("plugins", {}).pop(plugin_id, None)
        self._save_state()

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        """启用/禁用插件（内置插件同样受状态控制，仅影响应用页展示）。"""
        self.get(plugin_id)
        self._state.setdefault("plugins", {})[plugin_id] = {
            **self._state["plugins"].get(plugin_id, {}),
            "enabled": enabled,
        }
        self._save_state()
        return self.get(plugin_id)
