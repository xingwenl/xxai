"""插件事件日志：宿主进程把关键事件写成 JSONL，用于排查「工具静默失效」。

为什么必须落盘：iframe 自己的 console 只在 DevTools 里可见，关掉就没有证据；
「manifest 没声明 tools」「iframe 没加载」「SDK 注入失败」「方法注册被跳过」这些问题
需要事后 tail 才能定位，所以由宿主统一记账，格式与 akm 的 plugin.launch.log 对齐。

事件名走白名单：前端可以经 ``POST /api/desktop/plugin-log`` 上报，不限制会被写成噪声，
也不便于按事件名 grep。单文件超过 1 MiB 轮转为 ``plugin.log.1``（只保留一份历史）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desktop_app import paths
from desktop_app.protocol import PLUGIN_ID_PATTERN

logger = logging.getLogger(__name__)

# 允许写入的事件名；新增事件时同步更新 README 的事件表
EVENT_NAMES = frozenset(
    {
        "install_ok",
        "install_failed",
        "uninstall",
        "enable",
        "disable",
        "update_ok",
        "update_failed",
        "iframe_load",
        "sdk_injected",
        "sdk_inject_failed",
        "tools_registered",
        "tool_skipped",
        "config_saved",
    }
)

# 单个日志文件上限：1 MiB 约可容纳上万条事件，超出后轮转为 plugin.log.1
MAX_LOG_BYTES = 1024 * 1024

# detail 字段长度上限：前端上报的异常文本可能很长，截断避免单行日志膨胀
MAX_DETAIL_LENGTH = 4096

# 清单解析失败、还没拿到插件 id 的安装失败，用固定占位 id 记账
UNKNOWN_PLUGIN = "unknown"


class PluginLog:
    """插件事件日志写入器（线程安全）。

    ``path`` 默认为 ``~/.desktop-app/plugin.log``；测试可传临时路径。
    写日志失败只记 warning、不向上抛，避免记账问题影响安装/启停等主流程。
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else paths.plugin_log_file()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """返回日志文件路径（便于测试与诊断）。"""
        return self._path

    @staticmethod
    def _normalize_plugin_id(plugin_id: str) -> str:
        if plugin_id == UNKNOWN_PLUGIN or PLUGIN_ID_PATTERN.match(plugin_id):
            return plugin_id
        # 插件 id 非法时也允许记账，但打上占位符，避免脏数据混进日志
        return UNKNOWN_PLUGIN

    def append(self, plugin_id: str, event: str, detail: str | None = None, **fields: Any) -> None:
        """追加一条事件。

        - ``event`` 必须是 ``EVENT_NAMES`` 中的名字，否则抛 ValueError（接口层转 400）；
        - ``detail`` 会截断到 4 KiB；
        - 其余 ``fields`` 作为附加字段原样写入（必须可 JSON 序列化）。
        """
        if event not in EVENT_NAMES:
            raise ValueError(f"未知事件名: {event!r}（允许：{'、'.join(sorted(EVENT_NAMES))}）")
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "plugin": self._normalize_plugin_id(plugin_id),
            "event": event,
        }
        if detail:
            record["detail"] = detail[:MAX_DETAIL_LENGTH]
        record.update(fields)
        try:
            line = json.dumps(record, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise ValueError(f"日志字段无法序列化为 JSON: {exc}") from exc
        payload = line.encode("utf-8")
        with self._lock:
            try:
                self._rotate_if_needed(len(payload))
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError as exc:  # 记账失败不阻塞主流程
                logger.warning("写入插件日志失败（%s）: %s", self._path, exc)

    def _rotate_if_needed(self, incoming: int) -> None:
        """写入前检查大小：加上本条会超过上限时，把当前文件轮转为 plugin.log.1。"""
        if not self._path.is_file():
            return
        if self._path.stat().st_size + incoming <= MAX_LOG_BYTES:
            return
        rotated = self._path.with_name(f"{self._path.name}.1")
        os.replace(self._path, rotated)
