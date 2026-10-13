"""插件注册表：扫描内置与用户插件目录，解析 manifest 并合并启停状态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_app import paths
from desktop_app.protocol import DEFAULT_OPEN_MODE, PluginManifest


@dataclass
class PluginInfo:
    """插件运行时信息（由 manifest 与启停状态合并得到）。"""

    id: str
    name: str
    version: str
    description: str
    icon: str
    entry: str
    type: str
    permissions: list[str]
    dir: Path
    builtin: bool
    open_mode: str = DEFAULT_OPEN_MODE
    enabled: bool = True
    installed_at: str | None = None
    error: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "icon": self.icon,
            "entry": self.entry,
            "type": self.type,
            "permissions": self.permissions,
            "openMode": self.open_mode,
            "url": self.url,
            "builtin": self.builtin,
            "enabled": self.enabled,
            "installedAt": self.installed_at,
            "error": self.error,
            "iconUrl": f"/apps/{self.id}/{self.icon}" if self.icon else None,
            "entryUrl": self.url if self.type == "remote" and self.url else f"/apps/{self.id}/{self.entry}",
        }


class PluginRegistry:
    """扫描插件目录并构建插件列表；内置插件优先于用户插件。"""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        self.builtin_dir = Path(builtin_dir) if builtin_dir else paths.builtin_plugins_dir()
        self.user_dir = Path(user_dir) if user_dir else paths.user_plugins_dir()
        self._state = state or {}

    @staticmethod
    def load_manifest(
        plugin_dir: Path, require_dir_match: bool = True
    ) -> tuple[PluginManifest | None, str | None]:
        """解析并校验插件目录中的 manifest，返回 (manifest, error)。

        require_dir_match=False 用于「manifest 位于 zip 根」的安装场景，
        此时目录名是随机临时目录，无法与 id 比对。
        """
        manifest_file = plugin_dir / "manifest.json"
        if not manifest_file.is_file():
            return None, "缺少 manifest.json"
        try:
            manifest = PluginManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:  # pydantic 校验失败
            return None, f"manifest 解析失败: {exc}"
        if require_dir_match and manifest.id != plugin_dir.name:
            return None, f"manifest.id（{manifest.id}）与目录名（{plugin_dir.name}）不一致"
        # react 类型子应用由宿主 React 组件渲染，不需要 iframe 入口页面
        if manifest.type == "iframe" and not (plugin_dir / manifest.entry).is_file():
            return None, f"入口文件缺失: {manifest.entry}"
        return manifest, None

    def scan(self) -> list[PluginInfo]:
        """扫描内置 + 用户插件目录，返回合并后的插件列表。"""
        plugins: dict[str, PluginInfo] = {}
        for plugin_dir in self._iter_dirs(self.builtin_dir):
            manifest, error = self.load_manifest(plugin_dir)
            if manifest is None:
                # 内置插件包随应用分发，非法时静默跳过，避免宿主壳报错
                continue
            state_entry = self._state.get("plugins", {}).get(manifest.id, {})
            # remote 插件是纯壳：无论 manifest 声明什么都强制零权限，不向宿主申请能力
            plugins[manifest.id] = PluginInfo(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                icon=manifest.icon,
                entry=manifest.entry,
                type=manifest.type,
                permissions=[] if manifest.type == "remote" else manifest.permissions,
                open_mode=manifest.open_mode,
                url=manifest.url,
                dir=plugin_dir,
                builtin=True,
                enabled=bool(state_entry.get("enabled", True)),
            )
        for plugin_dir in self._iter_dirs(self.user_dir):
            manifest, error = self.load_manifest(plugin_dir)
            if manifest is None:
                # 用户安装的目录存在但非法：纳入列表并标记错误，便于设置页提示
                plugins[plugin_dir.name] = PluginInfo(
                    id=plugin_dir.name,
                    name=plugin_dir.name,
                    version="",
                    description="",
                    icon="",
                    entry="",
                    type="",
                    permissions=[],
                    dir=plugin_dir,
                    builtin=False,
                    enabled=False,
                    error=error,
                )
                continue
            if manifest.id in plugins:
                # 内置优先：同 id 时忽略用户目录中的副本
                continue
            state_entry = self._state.get("plugins", {}).get(manifest.id, {})
            plugins[manifest.id] = PluginInfo(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                icon=manifest.icon,
                entry=manifest.entry,
                type=manifest.type,
                permissions=[] if manifest.type == "remote" else manifest.permissions,
                open_mode=manifest.open_mode,
                url=manifest.url,
                dir=plugin_dir,
                builtin=False,
                enabled=bool(state_entry.get("enabled", True)),
                installed_at=state_entry.get("installedAt"),
            )
        return sorted(plugins.values(), key=lambda p: (not p.builtin, p.name.lower()))

    @staticmethod
    def _iter_dirs(root: Path) -> list[Path]:
        """遍历插件目录根下的子目录，跳过隐藏目录。"""
        if not root.is_dir():
            return []
        return [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")]
