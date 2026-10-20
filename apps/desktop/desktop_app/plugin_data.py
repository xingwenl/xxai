"""插件级本地持久化：为子应用提供跨会话的键值 JSON 存储。

设计取舍：
- 每个插件一个目录、每个键一个 ``<key>.json`` 文件，便于人工排查与备份，无需引入数据库依赖；
- 写入走「临时文件 + os.replace」原子替换，避免进程中断留下半截文件；
- 值上限 256 KiB、键名限制为安全文件名，宿主只做子应用的持久化底座，不承担大对象存储。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from desktop_app import paths
from desktop_app.protocol import PLUGIN_ID_PATTERN

logger = logging.getLogger(__name__)

# 键名会直接作为文件名使用：必须以字母/数字开头，只允许 . _ -，最长 64 字符
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# 单个键值上限：子应用数据（如账本）通常只有几十 KB，256 KiB 已足够
MAX_VALUE_BYTES = 256 * 1024


class PluginDataError(Exception):
    """插件数据读写失败的基类。"""


class InvalidPluginDataKey(PluginDataError):
    """插件 id 或数据键不合法（含路径穿越风险）。"""


class PluginDataTooLarge(PluginDataError):
    """单次写入超过大小上限。"""


class PluginDataStore:
    """按插件隔离的 JSON 键值存储。

    ``root`` 为插件数据根目录（默认 ``~/.desktop-app/plugin-data``），
    测试可传入临时目录；所有读写都在同一把重入锁内完成，供 FastAPI 多线程调用。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or paths.plugin_data_dir()).resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        """返回数据根目录（便于测试与诊断）。"""
        return self._root

    def plugin_dir(self, plugin_id: str) -> Path:
        """返回指定插件的数据目录。"""
        if not PLUGIN_ID_PATTERN.match(plugin_id):
            raise InvalidPluginDataKey(f"非法插件 id: {plugin_id!r}")
        return self._root / plugin_id

    def _file(self, plugin_id: str, key: str) -> Path:
        if not KEY_PATTERN.match(key):
            raise InvalidPluginDataKey(f"非法数据键: {key!r}（须匹配 {KEY_PATTERN.pattern}）")
        return self.plugin_dir(plugin_id) / f"{key}.json"

    def read_raw(self, plugin_id: str, key: str) -> bytes | None:
        """读取键值原始 JSON 字节；不存在返回 None。

        返回原始字节而不是反序列化结果，是为了区分「键不存在」与「值恰为 null」。
        """
        target = self._file(plugin_id, key)
        with self._lock:
            if not target.is_file():
                return None
            try:
                return target.read_bytes()
            except OSError as exc:
                raise PluginDataError(f"读取插件数据失败: {exc}") from exc

    def write(self, plugin_id: str, key: str, value: Any) -> None:
        """写入键值（任意可 JSON 序列化的值），原子替换目标文件。"""
        target = self._file(plugin_id, key)
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PluginDataError(f"值无法序列化为 JSON: {exc}") from exc
        if len(payload) > MAX_VALUE_BYTES:
            raise PluginDataTooLarge(f"值超过大小上限（{len(payload)} > {MAX_VALUE_BYTES} 字节）")
        with self._lock:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=target.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(payload)
                    os.replace(tmp_name, target)
                finally:
                    Path(tmp_name).unlink(missing_ok=True)
            except OSError as exc:
                raise PluginDataError(f"写入插件数据失败: {exc}") from exc

    def delete(self, plugin_id: str, key: str) -> bool:
        """删除键值；返回是否确实删除了文件。"""
        target = self._file(plugin_id, key)
        with self._lock:
            try:
                target.unlink()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise PluginDataError(f"删除插件数据失败: {exc}") from exc

    def keys(self, plugin_id: str) -> list[str]:
        """列出该插件已持久化的数据键（按名称排序，忽略临时文件）。"""
        directory = self.plugin_dir(plugin_id)
        with self._lock:
            if not directory.is_dir():
                return []
            names = [path.stem for path in directory.glob("*.json") if KEY_PATTERN.match(path.stem)]
        return sorted(names)

    def clear(self, plugin_id: str) -> int:
        """删除该插件的全部数据（卸载插件时调用）；返回删除的文件数。"""
        directory = self.plugin_dir(plugin_id)
        removed = 0
        with self._lock:
            if not directory.is_dir():
                return 0
            for path in directory.glob("*.json"):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logger.warning("清理插件数据文件失败: %s", path)
        return removed
