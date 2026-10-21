"""插件管理：zip 安装（受控解压 + 原子落盘）、升级（备份 + 回滚）、卸载、启停与状态持久化。"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desktop_app import metadata, paths
from desktop_app.plugin_log import UNKNOWN_PLUGIN, PluginLog
from desktop_app.protocol import PLUGIN_ID_PATTERN, PluginManifest
from desktop_app.registry import PluginInfo, PluginRegistry
from desktop_app.security import MAX_ZIP_SIZE, safe_extract_zip
from desktop_app.version import version_greater

# 每个插件保留的旧版本备份份数：够回滚最近几次，又不会把用户数据目录撑大
MAX_PLUGIN_BACKUPS = 3


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
        log: PluginLog | None = None,
    ) -> None:
        self.builtin_dir = Path(builtin_dir) if builtin_dir else paths.builtin_plugins_dir()
        self.user_dir = Path(user_dir) if user_dir else paths.user_plugins_dir()
        self.state_file = Path(state_file) if state_file else paths.state_file()
        # 事件日志默认放在状态文件旁边：生产即 ~/.desktop-app/plugin.log，测试传临时目录时也自然隔离
        self.log = log or PluginLog(self.state_file.parent / "plugin.log")
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
        """安装 zip 插件包，并把成功/失败事件写进插件日志（不改原有异常与返回值）。"""
        try:
            plugin = self._install_zip(zip_path)
        except PluginError as exc:
            # 失败时可能连 manifest.id 都还没解析出来，用占位 id 记账，错因里带原文
            self.log.append(UNKNOWN_PLUGIN, "install_failed", str(exc))
            raise
        except Exception as exc:  # 落盘异常等非业务错误同样留痕后再抛
            self.log.append(UNKNOWN_PLUGIN, "install_failed", f"{type(exc).__name__}: {exc}")
            raise
        self.log.append(plugin.id, "install_ok", version=plugin.version)
        return plugin

    def _install_zip(self, zip_path: Path) -> PluginInfo:
        """安装 zip 插件包：受控解压 → 校验 → 原子落盘到用户插件目录。"""
        with self._stage_zip(zip_path) as (manifest, plugin_src, manifest_at_root):
            if any(p.id == manifest.id for p in self.list_plugins()):
                raise PluginExistsError(f"插件已存在: {manifest.id}")
            dest = self.user_dir / manifest.id
            if dest.exists():
                raise PluginExistsError(f"插件目录已存在: {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._move_plugin_tree(plugin_src, dest, manifest_at_root=manifest_at_root)
            self._state.setdefault("plugins", {})[manifest.id] = {
                "enabled": True,
                "installedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._save_state()
        return self.get(manifest.id)

    @contextmanager
    def _stage_zip(self, zip_path: Path) -> Iterator[tuple[PluginManifest, Path, bool]]:
        """解压 zip 并校验 manifest，产出 (manifest, 归一化插件根, 清单是否在 zip 根)。

        临时目录的生命周期覆盖整个 with 块，调用方必须在块内完成落盘；安装与升级
        共用这一步，避免把安全解压/归一化/清单校验写两遍。
        """
        zip_path = Path(zip_path)
        size = zip_path.stat().st_size
        if size > MAX_ZIP_SIZE:
            raise PluginError(f"zip 文件超过大小限制（{size} > {MAX_ZIP_SIZE}）")
        with tempfile.TemporaryDirectory(prefix="desktop-plugin-") as tmp:
            tmp_root = Path(tmp)
            try:
                safe_extract_zip(zip_path, tmp_root)
            except zipfile.BadZipFile as exc:
                raise PluginError("不是有效的 zip 文件") from exc
            except OSError as exc:
                raise PluginError(f"zip 读取失败: {exc}") from exc
            plugin_src = _normalize_plugin_root(tmp_root)
            manifest_at_root = (tmp_root / "manifest.json").is_file()
            manifest, error = PluginRegistry.load_manifest(
                plugin_src, require_dir_match=not manifest_at_root
            )
            if manifest is None:
                raise PluginError(error or "manifest 校验失败")
            yield manifest, plugin_src, manifest_at_root

    @staticmethod
    def _move_plugin_tree(plugin_src: Path, dest: Path, *, manifest_at_root: bool) -> None:
        """把临时目录里的插件内容移动到 dest（同盘时优先走原子 rename）。"""
        if manifest_at_root:
            # manifest 位于 zip 根：以 manifest.id 建目录后整体落入
            dest.mkdir()
            for item in plugin_src.iterdir():
                shutil.move(str(item), str(dest))
        else:
            # 临时目录与用户插件目录通常同盘，shutil.move 优先走原子 rename
            shutil.move(str(plugin_src), str(dest))

    @property
    def backups_dir(self) -> Path:
        """旧版本备份根目录：跟随 user_dir 定位，测试传临时目录时天然隔离。"""
        return self.user_dir.parent / "plugin-backups"

    def upgrade_zip(
        self,
        zip_path: Path,
        *,
        expected_id: str | None = None,
        expected_version: str | None = None,
    ) -> PluginInfo:
        """升级已安装插件：备份旧目录 → 原子替换，失败回滚并写 update_failed 日志。"""
        try:
            plugin = self._upgrade_zip(
                zip_path, expected_id=expected_id, expected_version=expected_version
            )
        except PluginError as exc:
            self.log.append(UNKNOWN_PLUGIN, "update_failed", str(exc))
            raise
        except Exception as exc:  # 落盘异常等非业务错误同样留痕后再抛
            self.log.append(UNKNOWN_PLUGIN, "update_failed", f"{type(exc).__name__}: {exc}")
            raise
        self.log.append(plugin.id, "update_ok", version=plugin.version)
        return plugin

    def _upgrade_zip(
        self,
        zip_path: Path,
        *,
        expected_id: str | None,
        expected_version: str | None,
    ) -> PluginInfo:
        """升级的核心流程；只在 ``upgrade_zip`` 里，便于统一记账失败事件。"""
        with self._stage_zip(zip_path) as (manifest, plugin_src, manifest_at_root):
            if expected_id and manifest.id != expected_id:
                raise PluginError(f"插件包 id（{manifest.id}）与索引（{expected_id}）不一致")
            if expected_version and manifest.version != expected_version:
                raise PluginError(
                    f"插件包版本（{manifest.version}）与索引（{expected_version}）不一致"
                )
            current = self.get(manifest.id)
            if current.builtin:
                raise PluginError("内置插件随宿主一起更新，不支持单独升级")
            if current.type == "remote":
                raise PluginError("URL 壳插件由宿主生成 manifest，不支持市场升级")
            if not version_greater(manifest.version, current.version):
                raise PluginError(
                    f"新版本 {manifest.version} 不高于已安装版本 {current.version}，无需升级"
                )
            dest = self.user_dir / manifest.id
            if not dest.is_dir():
                raise PluginError(f"已安装插件目录不存在：{dest}")
            # 先把旧目录 rename 进备份区：既是备份，也保证 dest 在替换前是空位
            backup = self._backup_plugin_dir(manifest.id, current.version, dest)
            staging = self.user_dir / f".{manifest.id}.upgrading"
            shutil.rmtree(staging, ignore_errors=True)
            try:
                self._move_plugin_tree(plugin_src, staging, manifest_at_root=manifest_at_root)
                staging.rename(dest)
            except OSError as exc:
                shutil.rmtree(staging, ignore_errors=True)
                if backup is not None and backup.is_dir() and not dest.exists():
                    shutil.move(str(backup), str(dest))
                raise PluginError(f"升级失败，已回滚到 {current.version}：{exc}") from exc
            now = datetime.now(timezone.utc).isoformat()
            state = self._state.setdefault("plugins", {}).setdefault(manifest.id, {})
            # 升级只换代码：启停状态与安装时间原样保留，另记升级时间与来源版本
            state["enabled"] = current.enabled
            state["installedAt"] = current.installed_at or now
            state["updatedAt"] = now
            state["previousVersion"] = current.version
            self._save_state()
        return self.get(manifest.id)

    def _backup_plugin_dir(self, plugin_id: str, version: str, dest: Path) -> Path | None:
        """把旧版本目录整体移动到备份目录（同盘 rename）。

        备份失败返回 None 且不阻断升级：此时 dest 仍在原位，后续替换失败也不会
        丢旧版本；正常路径下备份一定存在，用户可据此手动回滚。
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_version = re.sub(r"[^0-9A-Za-z._-]", "_", version) or "unknown"
        backup_root = self.backups_dir / plugin_id
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / f"{safe_version}-{stamp}"
            dest.rename(backup)
        except OSError:
            return None
        self._prune_backups(backup_root)
        return backup

    @staticmethod
    def _prune_backups(backup_root: Path) -> None:
        """只保留最近 MAX_PLUGIN_BACKUPS 份备份（目录名含版本与时间戳，倒序取新）。"""
        try:
            backups = sorted(
                (path for path in backup_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
        except OSError:
            return
        for stale in backups[MAX_PLUGIN_BACKUPS:]:
            shutil.rmtree(stale, ignore_errors=True)

    def uninstall(self, plugin_id: str) -> None:
        """卸载用户插件；内置插件禁止卸载。"""
        plugin = self.get(plugin_id)
        if plugin.builtin:
            raise PluginError("内置插件不可卸载")
        shutil.rmtree(plugin.dir)
        self._state.get("plugins", {}).pop(plugin_id, None)
        self._save_state()
        self.log.append(plugin_id, "uninstall")

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        """启用/禁用插件（内置插件同样受状态控制，仅影响应用页展示）。"""
        self.get(plugin_id)
        self._state.setdefault("plugins", {})[plugin_id] = {
            **self._state["plugins"].get(plugin_id, {}),
            "enabled": enabled,
        }
        self._save_state()
        self.log.append(plugin_id, "enable" if enabled else "disable")
        return self.get(plugin_id)

    # ---------- 从 URL 安装远程壳插件 ----------

    @staticmethod
    def _derive_plugin_id(url: str) -> str:
        """由 URL 域名生成稳定插件 id：小写、非字母数字转连字符、冲突时调用方加后缀。"""
        host = (urllib.parse.urlparse(url).hostname or "site").lower()
        slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-")
        if not slug or not PLUGIN_ID_PATTERN.match(slug):
            slug = "site"
        return slug

    @staticmethod
    def _placeholder_icon(name: str) -> bytes:
        """生成占位 SVG 图标（名称首字符，保证 remote 插件始终有图标文件）。"""
        letter = html.escape((name[:1] or "?").upper())
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">'
            '<rect width="256" height="256" rx="56" fill="#06b6d4"/>'
            f'<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="128" fill="#ffffff">{letter}</text>'
            "</svg>"
        )
        return svg.encode("utf-8")

    @staticmethod
    def _unique_id(base: str, existing: set[str]) -> str:
        """在 base 基础上追加 -2/-3 后缀，保证插件 id 唯一。"""
        candidate = base
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def install_from_url(
        self,
        url: str,
        name: str | None = None,
        description: str | None = None,
        icon_url: str | None = None,
        fetcher=None,
    ) -> PluginInfo:
        """从 URL 安装远程壳插件，并把成功/失败事件写进插件日志（不改原有异常与返回值）。"""
        try:
            plugin = self._install_from_url(
                url, name=name, description=description, icon_url=icon_url, fetcher=fetcher
            )
        except PluginError as exc:
            self.log.append(UNKNOWN_PLUGIN, "install_failed", str(exc), source="url")
            raise
        except Exception as exc:
            self.log.append(
                UNKNOWN_PLUGIN, "install_failed", f"{type(exc).__name__}: {exc}", source="url"
            )
            raise
        self.log.append(plugin.id, "install_ok", version=plugin.version, source="url")
        return plugin

    def _install_from_url(
        self,
        url: str,
        name: str | None = None,
        description: str | None = None,
        icon_url: str | None = None,
        fetcher=None,
    ) -> PluginInfo:
        """从 URL 安装远程壳插件：抓取元数据 -> 生成 manifest -> 原子落盘。"""
        try:
            page_url = metadata.validate_fetchable_url(url)
        except metadata.MetadataError as exc:
            raise PluginError(str(exc)) from exc

        installed = self.list_plugins()
        existing = {p.id for p in installed}
        for plugin in installed:
            if plugin.type == "remote" and plugin.url == page_url:
                raise PluginExistsError(f"该 URL 已安装为插件: {plugin.id}")
        plugin_id = self._unique_id(self._derive_plugin_id(page_url), existing)

        meta: metadata.SiteMetadata | None = None
        try:
            meta = metadata.fetch_site_metadata(page_url, fetcher)
        except metadata.MetadataError as exc:
            meta = None
            if not (name or "").strip():
                raise PluginError(f"自动抓取元数据失败：{exc}；请手动填写名称后重试") from exc

        final_name = (name or "").strip() or (meta.name if meta else "")
        if not final_name:
            raise PluginError("未能从站点获取名称，请手动填写")
        final_desc = (description or "").strip() or (meta.description if meta else "") or ""

        icon_bytes: bytes | None = None
        icon_ext: str | None = None
        if (icon_url or "").strip():
            # 用户显式指定的图标失败时直接报错，不静默降级
            try:
                icon_bytes, icon_ext = metadata.fetch_icon(icon_url.strip(), fetcher)
            except metadata.MetadataError as exc:
                raise PluginError(f"图标下载失败：{exc}") from exc
        elif meta is not None and meta.icon_bytes:
            icon_bytes, icon_ext = meta.icon_bytes, meta.icon_ext

        manifest_data = {
            "id": plugin_id,
            "name": final_name,
            "version": "0.1.0",
            "description": final_desc,
            "icon": f"icon.{icon_ext or 'svg'}",
            "type": "remote",
            "url": page_url,
            "permissions": [],
        }
        dest = self.user_dir / plugin_id
        if dest.exists():
            raise PluginExistsError(f"插件目录已存在: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.mkdir()
            (dest / "manifest.json").write_text(
                json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (dest / manifest_data["icon"]).write_bytes(
                icon_bytes if icon_bytes else self._placeholder_icon(final_name)
            )
        except OSError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        self._state.setdefault("plugins", {})[plugin_id] = {
            "enabled": True,
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "source": "url",
        }
        self._save_state()
        return self.get(plugin_id)

    def _ensure_remote(self, plugin_id: str) -> PluginInfo:
        """校验插件为可编辑的 remote 类型，返回插件信息。"""
        plugin = self.get(plugin_id)
        if plugin.type != "remote" or not plugin.url:
            raise PluginError("仅 type=remote 的 URL 插件支持元数据编辑")
        return plugin

    def _rewrite_manifest(self, plugin: PluginInfo, **updates: Any) -> None:
        """读取并更新插件 manifest.json（保留 id/type/url/version/permissions）。"""
        manifest_file = plugin.dir / "manifest.json"
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        data.update(updates)
        manifest_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_metadata(
        self,
        plugin_id: str,
        name: str | None = None,
        description: str | None = None,
        icon_url: str | None = None,
        fetcher=None,
    ) -> PluginInfo:
        """手动编辑 remote 插件的名称 / 描述 / 图标（URL 保持不变）。"""
        plugin = self._ensure_remote(plugin_id)
        updates: dict[str, Any] = {}
        if name is not None and name.strip():
            updates["name"] = name.strip()
        if description is not None:
            updates["description"] = description.strip()
        if (icon_url or "").strip():
            try:
                icon_bytes, icon_ext = metadata.fetch_icon(icon_url.strip(), fetcher)
            except metadata.MetadataError as exc:
                raise PluginError(f"图标下载失败：{exc}") from exc
            icon_name = f"icon.{icon_ext}"
            (plugin.dir / icon_name).write_bytes(icon_bytes)
            old_icon = plugin.dir / plugin.icon
            if old_icon.is_file() and old_icon.name != icon_name:
                old_icon.unlink()
            updates["icon"] = icon_name
        self._rewrite_manifest(plugin, **updates)
        return self.get(plugin_id)

    def refresh_metadata(self, plugin_id: str, fetcher=None) -> PluginInfo:
        """重新抓取远程插件元数据并更新名称 / 描述 / 图标（保留手动编辑的 id 与 url）。"""
        plugin = self._ensure_remote(plugin_id)
        try:
            meta = metadata.fetch_site_metadata(plugin.url, fetcher)
        except metadata.MetadataError as exc:
            raise PluginError(f"重新抓取失败：{exc}；已保留原数据") from exc
        if not meta.name:
            raise PluginError("重新抓取未获得名称，已保留原数据")
        updates: dict[str, Any] = {"name": meta.name, "description": meta.description}
        if meta.icon_bytes:
            icon_name = f"icon.{meta.icon_ext or 'svg'}"
            (plugin.dir / icon_name).write_bytes(meta.icon_bytes)
            old_icon = plugin.dir / plugin.icon
            if old_icon.is_file() and old_icon.name != icon_name:
                old_icon.unlink()
            updates["icon"] = icon_name
        self._rewrite_manifest(plugin, **updates)
        return self.get(plugin_id)
