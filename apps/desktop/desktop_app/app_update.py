"""宿主应用更新：读静态发布清单、按平台挑资产、下载校验到本地更新目录。

信任模型与插件市场一致——没有代码签名认证，只保证「拿到的字节与清单里声明的
sha256/size 一致」，并且**不替换宿主自身**：下载完成后由用户手动安装，避免未签名
产物在 macOS Gatekeeper / Windows 文件占用上把应用搞坏。

清单是一份静态 JSON（默认托管在仓库 raw 地址，GitHub 主源 + Gitee 镜像）::

    {
      "version": 1,
      "latest": "0.2.1",
      "publishedAt": "2026-10-21T00:00:00Z",
      "notes": "修复……",
      "releaseUrl": "https://github.com/.../releases/tag/desktop-v0.2.1",
      "platforms": {
        "macos-arm64": {"name": "WW-0.2.1-macos-arm64.zip", "url": "https://...",
                        "mirrors": ["https://gitee.com/..."], "sha256": "<64 hex>", "size": 123}
      }
    }
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from desktop_app import paths, transfer
from desktop_app.version import version_greater

logger = logging.getLogger(__name__)

# 发布清单地址；可指向 file:// 或本机 http://，便于本地联调与端到端验证
APP_UPDATE_ENV = "DESKTOP_APP_UPDATE_URL"
# 清单镜像（逗号分隔）：主源取不到时按顺序回退
APP_UPDATE_MIRRORS_ENV = "DESKTOP_APP_UPDATE_MIRRORS"
# 置 0/false/no/off 可整体关闭宿主更新检查（前端显示「未启用」）
APP_UPDATE_DISABLE_ENV = "DESKTOP_APP_UPDATE"

DEFAULT_APP_UPDATE_URL = (
    "https://raw.githubusercontent.com/xingwenl/xxai/main/apps/desktop/releases/latest.json"
)
# Gitee 作为默认镜像：GitHub raw 在部分网络下不可达
DEFAULT_APP_UPDATE_MIRRORS = (
    "https://gitee.com/xingwenl/xxai/raw/main/apps/desktop/releases/latest.json",
)

# 清单里出现、且本机能识别的平台键；未知键忽略（便于将来加平台而不改老宿主）
PLATFORM_KEYS = ("macos-arm64", "macos-x64", "windows-x64", "linux-arm64", "linux-x64")

MAX_MANIFEST_BYTES = 128 * 1024
MAX_ASSET_BYTES = 1024 * 1024 * 1024
CACHE_TTL_SECONDS = 600
FETCH_TIMEOUT_SECONDS = 30
USER_AGENT = "WW-Desktop-AppUpdate/1.0"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AppUpdateError(Exception):
    """宿主更新业务错误。"""


class AppUpdateValidationError(AppUpdateError):
    """清单或资产不符合约定（HTTP 400）。"""


class AppUpdateDownloadError(AppUpdateError):
    """清单/资产下载失败（HTTP 502）。"""


@dataclass(frozen=True)
class UpdateAsset:
    """当前平台对应的一个发布资产。"""

    key: str
    name: str
    url: str
    sha256: str
    size: int
    mirrors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """返回给前端的 camelCase 结构。"""
        return {
            "platform": self.key,
            "name": self.name,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "mirrors": list(self.mirrors),
        }


@dataclass(frozen=True)
class ReleaseManifest:
    """发布清单内容。"""

    latest: str
    published_at: str = ""
    notes: str = ""
    release_url: str = ""
    platforms: dict[str, UpdateAsset] = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateInfo:
    """下发给前端的更新状态。"""

    enabled: bool
    current: str
    latest: str = ""
    has_update: bool = False
    platform: str = ""
    published_at: str = ""
    notes: str = ""
    release_url: str = ""
    asset: UpdateAsset | None = None
    downloaded_path: str = ""
    source: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """返回给前端的 camelCase 结构。"""
        return {
            "enabled": self.enabled,
            "current": self.current,
            "latest": self.latest,
            "hasUpdate": self.has_update,
            "platform": self.platform,
            "publishedAt": self.published_at,
            "notes": self.notes,
            "releaseUrl": self.release_url,
            "asset": self.asset.to_dict() if self.asset else None,
            "downloadedPath": self.downloaded_path,
            "source": self.source,
            "error": self.error,
        }


def is_enabled() -> bool:
    """更新检查是否启用（默认启用，可用 DESKTOP_APP_UPDATE 关闭）。"""
    value = os.environ.get(APP_UPDATE_DISABLE_ENV)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def manifest_url() -> str:
    """当前生效的发布清单地址。"""
    return os.environ.get(APP_UPDATE_ENV, "").strip() or DEFAULT_APP_UPDATE_URL


def manifest_mirrors() -> tuple[str, ...]:
    """清单镜像：显式配置优先，未配置时用内置 Gitee 镜像。"""
    raw = os.environ.get(APP_UPDATE_MIRRORS_ENV)
    if raw is None:
        return DEFAULT_APP_UPDATE_MIRRORS
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def platform_key() -> str:
    """把 ``sys.platform`` + 机器架构映射成清单里的平台键，识别不了返回空串。"""
    system = sys.platform
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    if system == "darwin":
        return f"macos-{arch}"
    if system in {"win32", "cygwin", "msys"}:
        return f"windows-{arch}"
    if system.startswith("linux"):
        return f"linux-{arch}"
    return ""


def _parse_asset(key: str, raw: Any) -> UpdateAsset:
    """解析并校验单个平台资产。"""
    if not isinstance(raw, dict):
        raise AppUpdateValidationError(f"发布清单里 {key} 必须是对象")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AppUpdateValidationError(f"发布清单里 {key}.name 不能为空")
    # 只允许纯文件名：避免清单里写 ../ 把下载落点带出 updates 目录
    if Path(name).name != name or "/" in name or "\\" in name:
        raise AppUpdateValidationError(f"发布清单里 {key}.name 必须是纯文件名：{name}")
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise AppUpdateValidationError(f"发布清单里 {key}.url 不能为空")
    try:
        transfer.validate_url(url, what=f"发布资产 {name}")
    except transfer.TransferValidationError as exc:
        raise AppUpdateValidationError(str(exc)) from exc
    mirrors_raw = raw.get("mirrors") or []
    if not isinstance(mirrors_raw, list) or not all(isinstance(item, str) for item in mirrors_raw):
        raise AppUpdateValidationError(f"发布清单里 {key}.mirrors 必须是字符串数组")
    mirrors: list[str] = []
    for mirror in mirrors_raw:
        if not mirror:
            continue
        try:
            mirrors.append(transfer.validate_url(mirror, what=f"发布资产 {name} 的镜像"))
        except transfer.TransferValidationError as exc:
            raise AppUpdateValidationError(str(exc)) from exc
    sha256 = raw.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_PATTERN.match(sha256.lower()):
        raise AppUpdateValidationError(f"发布清单里 {key}.sha256 必须是 64 位十六进制")
    size = raw.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ASSET_BYTES:
        raise AppUpdateValidationError(
            f"发布清单里 {key}.size 必须是 1..{MAX_ASSET_BYTES} 之间的整数"
        )
    return UpdateAsset(
        key=key,
        name=name,
        url=url,
        sha256=sha256.lower(),
        size=size,
        mirrors=tuple(mirrors),
    )


def parse_manifest(data: bytes) -> ReleaseManifest:
    """解析发布清单：校验格式版本、版本号、发布时间与各平台资产。"""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppUpdateValidationError(f"发布清单不是有效的 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise AppUpdateValidationError("发布清单必须是 JSON 对象")
    if payload.get("version") != 1:
        raise AppUpdateValidationError("发布清单格式版本必须是 1")
    latest = payload.get("latest")
    if not isinstance(latest, str) or not latest.strip():
        raise AppUpdateValidationError("发布清单的 latest 不能为空")
    published_at = str(payload.get("publishedAt") or "")
    notes = str(payload.get("notes") or "")
    release_url = str(payload.get("releaseUrl") or "")
    if release_url:
        try:
            transfer.validate_url(release_url, what="发布页地址")
        except transfer.TransferValidationError as exc:
            raise AppUpdateValidationError(str(exc)) from exc
    platforms_raw = payload.get("platforms")
    if not isinstance(platforms_raw, dict):
        raise AppUpdateValidationError("发布清单的 platforms 必须是对象")
    platforms: dict[str, UpdateAsset] = {}
    for key, value in platforms_raw.items():
        if key not in PLATFORM_KEYS:
            logger.warning("发布清单包含未知平台键，已忽略：%s", key)
            continue
        platforms[key] = _parse_asset(key, value)
    if not platforms:
        raise AppUpdateValidationError("发布清单没有可用平台资产")
    return ReleaseManifest(
        latest=latest.strip(),
        published_at=published_at,
        notes=notes,
        release_url=release_url,
        platforms=platforms,
    )


_manifest_cache: dict[str, tuple[float, ReleaseManifest]] = {}


def clear_cache() -> None:
    """清空清单缓存（测试与「立即刷新」用）。"""
    _manifest_cache.clear()


def fetch_manifest(url: str | None = None, *, refresh: bool = False) -> ReleaseManifest:
    """获取发布清单：主源失败时按镜像顺序回退，10 分钟内复用内存缓存。"""
    target = url or manifest_url()
    try:
        transfer.validate_url(target, what="发布清单地址")
    except transfer.TransferValidationError as exc:
        raise AppUpdateValidationError(str(exc)) from exc
    now = time.monotonic()
    cached = _manifest_cache.get(target)
    if cached and not refresh and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    try:
        _, data = transfer.read_first(
            target,
            manifest_mirrors(),
            MAX_MANIFEST_BYTES,
            what="发布清单",
            user_agent=USER_AGENT,
        )
    except transfer.TransferValidationError as exc:
        raise AppUpdateValidationError(str(exc)) from exc
    except transfer.TransferDownloadError as exc:
        raise AppUpdateDownloadError(str(exc)) from exc
    manifest = parse_manifest(data)
    _manifest_cache[target] = (now, manifest)
    return manifest


def asset_path(version: str, asset: UpdateAsset) -> Path:
    """返回资产在本机的落点：``~/.desktop-app/updates/<version>/<name>``。"""
    safe_version = re.sub(r"[^0-9A-Za-z._+-]", "_", version) or "unknown"
    return paths.updates_dir() / safe_version / asset.name


def get_update_info(current_version: str, *, refresh: bool = False) -> UpdateInfo:
    """组装下发给前端的更新状态；失败时把中文原因放进 ``error`` 而不是报「已是最新」。"""
    if not is_enabled():
        return UpdateInfo(enabled=False, current=current_version)
    key = platform_key()
    try:
        manifest = fetch_manifest(refresh=refresh)
    except AppUpdateError as exc:
        return UpdateInfo(enabled=True, current=current_version, platform=key, error=str(exc))
    asset = manifest.platforms.get(key) if key else None
    info = UpdateInfo(
        enabled=True,
        current=current_version,
        latest=manifest.latest,
        has_update=bool(asset) and version_greater(manifest.latest, current_version),
        platform=key,
        published_at=manifest.published_at,
        notes=manifest.notes,
        release_url=manifest.release_url,
        asset=asset,
        source=manifest_url(),
    )
    if not key:
        return replace(info, error=f"当前平台不在发布清单支持范围：{sys.platform}")
    if asset is None:
        return replace(info, error=f"发布清单里没有当前平台 {key} 的资产")
    target = asset_path(manifest.latest, asset)
    if target.is_file() and target.stat().st_size == asset.size:
        return replace(info, downloaded_path=str(target))
    return info


def download_asset(info: UpdateInfo) -> tuple[Path, int, str]:
    """下载当前平台资产到更新目录，校 size 与 sha256，返回 (路径, 字节数, sha256)。"""
    if not info.enabled:
        raise AppUpdateValidationError("宿主更新检查未启用")
    if info.asset is None:
        raise AppUpdateValidationError("发布清单里没有当前平台可下载的资产")
    target = asset_path(info.latest, info.asset)
    try:
        _, size, digest = transfer.download_first(
            info.asset.url,
            info.asset.mirrors,
            target,
            MAX_ASSET_BYTES,
            what=f"{info.asset.name}",
            user_agent=USER_AGENT,
            timeout=FETCH_TIMEOUT_SECONDS,
            expected_size=info.asset.size,
            expected_sha256=info.asset.sha256,
        )
    except transfer.TransferValidationError as exc:
        # 校验不过时 .part 已被删掉，这里只清理可能残留的空版本目录
        _remove_empty_dir(target.parent)
        raise AppUpdateValidationError(str(exc)) from exc
    except transfer.TransferDownloadError as exc:
        _remove_empty_dir(target.parent)
        raise AppUpdateDownloadError(str(exc)) from exc
    return target, size, digest


def _remove_empty_dir(path: Path) -> None:
    """下载失败后清掉空的版本目录，避免 ``updates/`` 里堆一串空目录。"""
    try:
        path.rmdir()
    except OSError:
        pass


def reveal_updates_dir() -> Path:
    """在系统文件管理器里打开更新目录（固定目录，不接受外部路径）。"""
    target = paths.updates_dir()
    target.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)  # noqa: S603 - 固定目录
        elif sys.platform in {"win32", "cygwin", "msys"}:
            os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(target)], check=False)  # noqa: S603 - 固定目录
    except OSError as exc:
        raise AppUpdateError(f"打开更新目录失败：{exc}") from exc
    return target
