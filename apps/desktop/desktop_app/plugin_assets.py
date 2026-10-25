"""插件资产存储：子应用图片等二进制文件的落盘、去重与配额。

设计取舍（与 ADR 0017 一致）：
- 每个插件一个目录，文件名由服务端按内容 sha256 生成（``sha256(data)[:16] + 扩展名``）：
  客户端拿不到命名权，顺带解决路径穿越、重名与「同图重复粘贴」三件事；
- 类型白名单只有 png/jpeg/webp/gif，并校验文件魔数而不只信 Content-Type：同源 SVG
  可以携带脚本，直接打开等于给宿主开 XSS 口子，因此位图之外一律拒绝；
- 配额写死在存储层（单文件 2 MiB、单插件 64 MiB 与 500 个），因为客户端压缩后的
  截图只有几百 KB，超限基本意味着「有人塞了张原图」，宿主按原始字节校验、不信任声明；
- 写入走「临时文件 + os.replace」原子替换，读写共用同一把重入锁，供 FastAPI 多线程调用；
- 文件名与内容一一对应，因此 GET 可以放心长缓存；存储层只负责落盘，孤儿资产的回收
  由子应用按正文引用自己决定（宿主扫目录做 GC 一旦解析有 bug 就是静默丢图）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from desktop_app import paths
from desktop_app.protocol import PLUGIN_ID_PATTERN

logger = logging.getLogger(__name__)

# 允许的资产类型 → 落盘扩展名；新增类型只需在这里加一行（key/引用/回收三条语义不变）
ALLOWED_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# 扩展名反查 MIME：GET 响应按落盘扩展名声明类型，不依赖客户端上传时的声明
MIME_BY_SUFFIX: dict[str, str] = {suffix: mime for mime, suffix in ALLOWED_MIME.items()}

# 单个资产上限：压过的截图约 200~400 KB，2 MiB 是「塞原图」的兜底门槛
MAX_FILE_BYTES = 2 * 1024 * 1024
# 单个插件资产总字节与文件数配额：与 plugin-data 的 256 KiB/键分开计，互不挤占
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILE_COUNT = 500

# 资产 key 由服务端生成：16 位十六进制内容前缀 + 白名单扩展名，客户端无法构造越界路径
KEY_PATTERN = re.compile(r"^[a-z0-9]{16}\.(png|jpg|webp|gif)$")

# 资产引用的站内路径前缀（只拼路径不拼 host：换端口/换机器后引用依然成立）
ASSET_URL_PREFIX = "/api/desktop/plugin-assets"


class PluginAssetError(Exception):
    """插件资产读写失败的基类。"""


class InvalidPluginAssetKey(PluginAssetError):
    """插件 id 或资产 key 不合法（含路径穿越风险）。"""


class UnsupportedAssetType(PluginAssetError):
    """资产类型不在白名单，或文件魔数与声明类型不符。"""


class AssetTooLarge(PluginAssetError):
    """单个资产超过大小上限。"""


class AssetQuotaExceeded(PluginAssetError):
    """插件资产总量或数量超过配额。"""


@dataclass(frozen=True)
class AssetInfo:
    """一个已落盘资产的元信息（不含内容字节）。

    ``size`` 对外的字段名是 ``bytes``（见 :meth:`to_dict`）；``created`` 只描述
    本次 ``put`` 是否新建了文件——已存在同内容资产时直接返回、不重写也不占配额。
    """

    key: str
    size: int
    mime: str
    created_at: str
    created: bool = True

    def to_dict(self, plugin_id: str) -> dict[str, object]:
        """转成 REST 形状：字段名对齐前端 ``PluginAsset`` 接口。"""
        return {
            "key": self.key,
            "url": asset_url(plugin_id, self.key),
            "bytes": self.size,
            "mime": self.mime,
            "createdAt": self.created_at,
        }


def asset_url(plugin_id: str, key: str) -> str:
    """拼接资产的站内绝对路径（不含 host/port），可直接放进正文与 ``<img src>``。"""
    return f"{ASSET_URL_PREFIX}/{plugin_id}/{key}"


def normalize_mime(raw: str) -> str:
    """把 Content-Type 归一成纯 MIME：去参数、去空白、转小写（``image/PNG; q=1`` → ``image/png``）。"""
    return (raw or "").split(";")[0].strip().lower()


def _matches_magic(data: bytes, mime: str) -> bool:
    """校验文件头魔数是否与声明的类型一致（OWASP：只信 Content-Type 等于没校验）。"""
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if mime == "image/gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    return False


def _detect_mime(data: bytes) -> str | None:
    """按魔数识别实际类型；只用于错误消息里说明「你传的到底是什么」。"""
    for mime in ALLOWED_MIME:
        if _matches_magic(data, mime):
            return mime
    return None


def _iso_timestamp(timestamp: float) -> str:
    """把文件 mtime 转成带时区的 ISO 8601（UTC、秒级），作为对外的 createdAt。

    秒级精度足够展示；需要精确先后时排序仍用 mtime 浮点值，不受截断影响。
    """
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


class PluginAssetStore:
    """按插件隔离的二进制资产存储。

    ``root`` 为资产根目录（默认 ``~/.desktop-app/plugin-assets``），测试可传临时目录；
    所有读写都在同一把重入锁内完成。目录或文件任一环节是符号链接都不跟随，
    避免「根目录里被塞一个链接」读到宿主其它位置的内容。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or paths.plugin_assets_dir()).resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        """返回资产根目录（便于测试与诊断）。"""
        return self._root

    def plugin_dir(self, plugin_id: str) -> Path:
        """返回指定插件的资产目录（不创建）。"""
        if not PLUGIN_ID_PATTERN.match(plugin_id):
            raise InvalidPluginAssetKey(f"非法插件 id: {plugin_id!r}")
        return self._root / plugin_id

    def _file(self, plugin_id: str, key: str) -> Path:
        if not KEY_PATTERN.match(key):
            raise InvalidPluginAssetKey(f"非法资产 key: {key!r}（须匹配 {KEY_PATTERN.pattern}）")
        return self.plugin_dir(plugin_id) / key

    def _scan(self, plugin_id: str) -> list[tuple[Path, os.stat_result]]:
        """扫描插件资产目录，返回 ``(路径, stat)`` 列表（按创建时间倒序）。

        忽略临时文件、不符合 key 规则的文件与符号链接；调用方需自行持锁。
        """
        directory = self.plugin_dir(plugin_id)
        if directory.is_symlink() or not directory.is_dir():
            return []
        entries: list[tuple[Path, os.stat_result]] = []
        for path in directory.iterdir():
            if not KEY_PATTERN.match(path.name) or path.is_symlink():
                continue
            try:
                if not path.is_file():
                    continue
                entries.append((path, path.stat()))
            except OSError as exc:  # 单个文件读不到不影响整体列表
                logger.warning("读取插件资产元信息失败: %s（%s）", path, exc)
        entries.sort(key=lambda item: (item[1].st_mtime, item[0].name), reverse=True)
        return entries

    def put(self, plugin_id: str, data: bytes, mime: str) -> AssetInfo:
        """写入一个资产，返回其元信息；同内容已存在时直接返回且不重写（``created=False``）。

        类型 → 大小 → 魔数 → 配额 的校验顺序是刻意的：先按声明类型判白名单（415），
        再按真实字节判上限与内容（413/415），最后才让新文件挤占配额（413）。
        """
        directory = self.plugin_dir(plugin_id)
        normalized = normalize_mime(mime)
        suffix = ALLOWED_MIME.get(normalized)
        if suffix is None:
            raise UnsupportedAssetType(
                f"不支持的资产类型: {mime.strip() or '(空)'}；仅允许 {'、'.join(sorted(ALLOWED_MIME))}"
            )
        if not data:
            raise PluginAssetError("资产内容为空，需要图片的原始字节")
        if len(data) > MAX_FILE_BYTES:
            raise AssetTooLarge(f"资产超过单文件上限（{len(data)} > {MAX_FILE_BYTES} 字节）")
        if not _matches_magic(data, normalized):
            actual = _detect_mime(data) or "未知类型"
            raise UnsupportedAssetType(f"文件内容与声明的类型 {normalized} 不符（魔数识别为 {actual}）")

        key = hashlib.sha256(data).hexdigest()[:16] + suffix
        target = directory / key
        with self._lock:
            if target.is_file() and not target.is_symlink():
                stat = target.stat()
                return AssetInfo(
                    key=key,
                    size=stat.st_size,
                    mime=normalized,
                    created_at=_iso_timestamp(stat.st_mtime),
                    created=False,
                )
            entries = self._scan(plugin_id)
            total = sum(stat.st_size for _, stat in entries)
            if len(entries) >= MAX_FILE_COUNT:
                raise AssetQuotaExceeded(
                    f"资产数量已达上限（{len(entries)} / {MAX_FILE_COUNT} 个），"
                    "请删除不再引用的图片后重试"
                )
            if total + len(data) > MAX_TOTAL_BYTES:
                raise AssetQuotaExceeded(
                    f"资产总量将超过配额（当前 {total} 字节 + 本次 {len(data)} 字节 > {MAX_TOTAL_BYTES} 字节），"
                    "请删除不再引用的图片后重试"
                )
            try:
                directory.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(prefix=f".{key[:16]}.", suffix=".tmp", dir=directory)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                    os.replace(tmp_name, target)
                finally:
                    Path(tmp_name).unlink(missing_ok=True)
            except OSError as exc:
                raise PluginAssetError(f"写入插件资产失败: {exc}") from exc
            stat = target.stat()
            return AssetInfo(
                key=key,
                size=stat.st_size,
                mime=normalized,
                created_at=_iso_timestamp(stat.st_mtime),
                created=True,
            )

    def get_path(self, plugin_id: str, key: str) -> Path | None:
        """返回资产文件路径，不存在返回 None（不跟随符号链接）。"""
        target = self._file(plugin_id, key)
        with self._lock:
            if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
                return None
            return target

    def read(self, plugin_id: str, key: str) -> tuple[bytes, str] | None:
        """读取资产内容与落盘时的 MIME，不存在返回 None。

        MIME 按扩展名反查而不是回读上传时的声明：扩展名由服务端按白名单生成，
        是比请求头更可信的来源。
        """
        target = self._file(plugin_id, key)
        with self._lock:
            if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
                return None
            try:
                return target.read_bytes(), MIME_BY_SUFFIX[target.suffix]
            except OSError as exc:
                raise PluginAssetError(f"读取插件资产失败: {exc}") from exc

    def list(self, plugin_id: str) -> list[AssetInfo]:
        """列出该插件的全部资产（按创建时间倒序，同秒按 key 倒序）。"""
        with self._lock:
            entries = self._scan(plugin_id)
        return [
            AssetInfo(
                key=path.name,
                size=stat.st_size,
                mime=MIME_BY_SUFFIX[path.suffix],
                created_at=_iso_timestamp(stat.st_mtime),
            )
            for path, stat in entries
        ]

    def delete(self, plugin_id: str, key: str) -> bool:
        """删除资产文件；返回是否确实删除了文件（幂等，不存在返回 False）。"""
        target = self._file(plugin_id, key)
        with self._lock:
            try:
                target.unlink()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise PluginAssetError(f"删除插件资产失败: {exc}") from exc

    def usage(self, plugin_id: str) -> dict[str, int]:
        """返回该插件当前用量与配额，字段名对齐前端 ``PluginAssetUsage``。"""
        with self._lock:
            entries = self._scan(plugin_id)
        return {
            "bytes": sum(stat.st_size for _, stat in entries),
            "count": len(entries),
            "limitBytes": MAX_TOTAL_BYTES,
            "limitCount": MAX_FILE_COUNT,
            "limitFileBytes": MAX_FILE_BYTES,
        }
