"""插件市场：读取静态索引、下载插件包、校验 sha256 后交给 PluginManager 安装。

索引是一份静态 JSON（默认托管在本仓库的 raw.githubusercontent 上），插件包是普通
zip。宿主只负责「拿包 + 验完整性 + 验包内 manifest 与索引一致」，落盘仍然复用
`PluginManager.install_zip()`，避免把解压/归一化/冲突检测写第二遍。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from desktop_app import transfer
from desktop_app.manager import PluginManager
from desktop_app.protocol import KNOWN_PERMISSIONS, PLUGIN_ID_PATTERN
from desktop_app.registry import PluginInfo
from desktop_app.security import MAX_ZIP_SIZE, validate_zip_entry_name
from desktop_app.version import version_greater

logger = logging.getLogger(__name__)

# 索引地址（可指向 file:// 或本机 http://，便于本地开发与端到端验证）
MARKET_ENV = "DESKTOP_PLUGIN_MARKET_URL"
# 索引镜像（逗号分隔）：主源取不到时按顺序回退，例如 Gitee raw
MARKET_MIRRORS_ENV = "DESKTOP_PLUGIN_MARKET_MIRRORS"
# 置 0/false/no/off 可整体关闭市场（前端显示「未启用」）
MARKET_DISABLE_ENV = "DESKTOP_PLUGIN_MARKET"
DEFAULT_MARKET_URL = (
    "https://raw.githubusercontent.com/xingwenl/xxai/main/apps/desktop/market/index.json"
)

MAX_INDEX_BYTES = 256 * 1024
MAX_MARKET_PLUGINS = 200
CACHE_TTL_SECONDS = 300
FETCH_TIMEOUT_SECONDS = 10
USER_AGENT = "WW-Desktop-PluginMarket/1.0"
_ID_KEYS = ("id", "name", "version", "download", "sha256")


class MarketError(Exception):
    """插件市场业务错误（索引获取失败、校验失败、安装冲突等）。"""


class MarketValidationError(MarketError):
    """索引或插件包内容不符合约定（用户可修正，HTTP 400）。"""


class MarketDownloadError(MarketError):
    """下载失败：网络错误、HTTP 状态异常（HTTP 502）。"""


@dataclass(frozen=True)
class MarketEntry:
    """市场索引里的一条插件记录。"""

    id: str
    name: str
    version: str
    download: str
    sha256: str
    description: str = ""
    size: int | None = None
    permissions: tuple[str, ...] = field(default_factory=tuple)
    # 下载镜像：主源（download）取不到时按顺序回退，例如 Gitee raw
    mirrors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """返回给前端的 camelCase 结构。"""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "download": self.download,
            "sha256": self.sha256,
            "size": self.size,
            "permissions": list(self.permissions),
            "mirrors": list(self.mirrors),
        }


def is_enabled() -> bool:
    """市场是否启用（默认启用，可用 DESKTOP_PLUGIN_MARKET 关闭）。"""
    value = os.environ.get(MARKET_DISABLE_ENV)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def index_url() -> str:
    """当前生效的索引地址：优先环境变量，其次仓库内默认地址。"""
    return os.environ.get(MARKET_ENV, "").strip() or DEFAULT_MARKET_URL


def index_mirrors() -> tuple[str, ...]:
    """索引镜像地址（逗号分隔）：主源取不到时按顺序回退。"""
    raw = os.environ.get(MARKET_MIRRORS_ENV, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _validate_url(url: str, *, what: str) -> str:
    """校验下载地址：生产只接受 https，本机开发额外允许 file:// 与回环 http://。"""
    try:
        return transfer.validate_url(url, what=what)
    except transfer.TransferValidationError as exc:
        raise MarketValidationError(str(exc)) from exc


def _read_entry_bytes(entry: MarketEntry) -> bytes:
    """按「download → mirrors」顺序取插件包，全部失败才报错。"""
    _, data = transfer.read_first(
        entry.download,
        entry.mirrors,
        MAX_ZIP_SIZE,
        what=f"插件 {entry.id} 的安装包",
        user_agent=USER_AGENT,
    )
    return data


def _parse_entry(raw: Any, position: int) -> MarketEntry:
    """把索引里的一条 JSON 记录解析成 MarketEntry，并做严格校验。"""
    if not isinstance(raw, dict):
        raise MarketValidationError(f"索引第 {position} 条不是对象")
    missing = [key for key in _ID_KEYS if not isinstance(raw.get(key), str) or not raw.get(key)]
    if missing:
        raise MarketValidationError(f"索引第 {position} 条缺少字段：{'、'.join(missing)}")
    plugin_id = raw["id"]
    if not PLUGIN_ID_PATTERN.match(plugin_id):
        raise MarketValidationError(f"索引第 {position} 条的插件 id 不合法：{plugin_id}")
    sha256 = raw["sha256"].lower()
    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise MarketValidationError(f"插件 {plugin_id} 的 sha256 必须是 64 位十六进制")
    download = _validate_url(raw["download"], what=f"插件 {plugin_id} 的下载地址")
    size = raw.get("size")
    if size is not None:
        if isinstance(size, bool) or not isinstance(size, int):
            raise MarketValidationError(f"插件 {plugin_id} 的 size 必须是整数")
        if size < 0 or size > MAX_ZIP_SIZE:
            raise MarketValidationError(
                f"插件 {plugin_id} 的 size 超出范围（{size}，上限 {MAX_ZIP_SIZE}）"
            )
    permissions_raw = raw.get("permissions") or []
    if not isinstance(permissions_raw, list) or not all(
        isinstance(item, str) for item in permissions_raw
    ):
        raise MarketValidationError(f"插件 {plugin_id} 的 permissions 必须是字符串数组")
    unknown = [item for item in permissions_raw if item not in KNOWN_PERMISSIONS]
    if unknown:
        # 未知权限只影响插件自身的运行态，不阻断上架
        logger.warning("插件 %s 声明了未知权限：%s", plugin_id, "、".join(unknown))
    mirrors_raw = raw.get("mirrors") or []
    if not isinstance(mirrors_raw, list) or not all(isinstance(item, str) for item in mirrors_raw):
        raise MarketValidationError(f"插件 {plugin_id} 的 mirrors 必须是字符串数组")
    mirrors = tuple(
        _validate_url(item, what=f"插件 {plugin_id} 的下载镜像") for item in mirrors_raw if item
    )
    return MarketEntry(
        id=plugin_id,
        name=raw["name"],
        version=raw["version"],
        download=download,
        sha256=sha256,
        description=str(raw.get("description") or ""),
        size=size,
        permissions=tuple(permissions_raw),
        mirrors=mirrors,
    )


def parse_index(data: bytes | str) -> list[MarketEntry]:
    """解析索引 JSON，返回去重后的插件条目列表。"""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarketValidationError(f"索引不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise MarketValidationError("索引根节点必须是对象")
    if payload.get("version") != 1:
        raise MarketValidationError("不支持的索引版本（当前只支持 version: 1）")
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        raise MarketValidationError("索引缺少 plugins 数组")
    if len(plugins) > MAX_MARKET_PLUGINS:
        raise MarketValidationError(
            f"索引条目过多（{len(plugins)} > {MAX_MARKET_PLUGINS}）"
        )
    entries: list[MarketEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(plugins, start=1):
        entry = _parse_entry(raw, index)
        if entry.id in seen:
            raise MarketValidationError(f"索引里插件 id 重复：{entry.id}")
        seen.add(entry.id)
        entries.append(entry)
    return entries


_index_cache: dict[str, tuple[float, list[MarketEntry]]] = {}


def clear_cache() -> None:
    """清空索引缓存（测试与 CLI 用）。"""
    _index_cache.clear()


def fetch_index(url: str | None = None, *, refresh: bool = False) -> list[MarketEntry]:
    """获取索引条目；默认走 5 分钟内存缓存，refresh=True 强制重取。

    主源取不到时按 ``DESKTOP_PLUGIN_MARKET_MIRRORS`` 顺序回退（例如 Gitee raw），
    这样 GitHub 被墙时市场仍然可用。
    """
    target = url or index_url()
    _validate_url(target, what="索引地址")
    now = time.monotonic()
    cached = _index_cache.get(target)
    if cached and not refresh and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    try:
        _, data = transfer.read_first(
            target,
            index_mirrors(),
            MAX_INDEX_BYTES,
            what="插件索引",
            user_agent=USER_AGENT,
        )
    except transfer.TransferValidationError as exc:
        raise MarketValidationError(str(exc)) from exc
    except transfer.TransferDownloadError as exc:
        raise MarketDownloadError(str(exc)) from exc
    entries = parse_index(data)
    _index_cache[target] = (now, entries)
    return entries


def read_archive_manifest(data: bytes) -> dict[str, Any]:
    """从 zip 字节里读出 manifest.json（支持根目录或单层目录两种包结构）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            for name in names:
                validate_zip_entry_name(name)
            manifests = [name for name in names if PurePosixPath(name).name == "manifest.json"]
            if not manifests:
                raise MarketValidationError("插件包里没有 manifest.json")
            if "manifest.json" in manifests:
                chosen = "manifest.json"
            elif len(manifests) == 1:
                # make_plugin_zip.py 打出的包是 plugins/<id>/manifest.json，允许唯一清单在子目录
                chosen = manifests[0]
            else:
                raise MarketValidationError(
                    "插件包结构不合法：只能存在一个 manifest.json（根目录或唯一子目录）"
                )
            raw = archive.read(chosen)
    except zipfile.BadZipFile as exc:
        raise MarketValidationError("不是有效的 zip 文件") from exc
    except OSError as exc:
        raise MarketValidationError(f"读取插件包失败：{exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketValidationError("插件包里的 manifest.json 不是合法 JSON") from exc
    if not isinstance(manifest, dict):
        raise MarketValidationError("插件包里的 manifest.json 必须是对象")
    return manifest


def _download_verified(entry: MarketEntry) -> bytes:
    """下载插件包并校验大小、sha256、包内 manifest 的 id 与版本，返回 zip 字节。"""
    data = _read_entry_bytes(entry)
    if entry.size is not None and len(data) != entry.size:
        raise MarketValidationError(
            f"插件 {entry.id} 的安装包大小与索引不一致（索引 {entry.size}，实际 {len(data)}）"
        )
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.sha256:
        raise MarketValidationError(
            f"插件 {entry.id} 的 sha256 校验失败（索引 {entry.sha256}，实际 {digest}）"
        )
    manifest = read_archive_manifest(data)
    manifest_id = str(manifest.get("id") or "")
    if manifest_id != entry.id:
        raise MarketValidationError(
            f"插件包内的 manifest id（{manifest_id or '缺失'}）与索引（{entry.id}）不一致"
        )
    manifest_version = str(manifest.get("version") or "")
    if manifest_version != entry.version:
        raise MarketValidationError(
            f"插件包版本（{manifest_version or '缺失'}）与索引（{entry.version}）不一致"
        )
    return data


def install_entry(manager: PluginManager, entry: MarketEntry) -> PluginInfo:
    """下载并安装一条市场记录：校验 sha256 与包内 manifest 后交给 manager 落盘。"""
    data = _download_verified(entry)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        handle.write(data)
        tmp_path = Path(handle.name)
    try:
        return manager.install_zip(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def upgrade_entry(manager: PluginManager, entry: MarketEntry) -> PluginInfo:
    """把已安装插件升级到索引里的版本：校验之后交给 manager 备份替换。

    只允许「索引版本严格高于本机版本」；内置插件与 remote 壳插件由宿主自己更新，
    这里直接拒绝，避免前端出现一个点了必然失败的按钮。
    """
    plugin = manager.get(entry.id)
    if plugin.builtin:
        raise MarketValidationError(f"内置插件 {entry.id} 随宿主一起更新，不支持市场升级")
    if plugin.type == "remote":
        raise MarketValidationError(f"URL 壳插件 {entry.id} 不支持市场升级")
    if not version_greater(entry.version, plugin.version):
        raise MarketValidationError(
            f"市场版本 {entry.version} 不高于已安装版本 {plugin.version}，无需升级"
        )
    data = _download_verified(entry)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        handle.write(data)
        tmp_path = Path(handle.name)
    try:
        return manager.upgrade_zip(
            tmp_path, expected_id=entry.id, expected_version=entry.version
        )
    finally:
        tmp_path.unlink(missing_ok=True)
