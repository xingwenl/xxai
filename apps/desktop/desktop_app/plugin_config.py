"""插件宿主配置：按插件隔离的 JSON 配置文件，宿主权威、子应用只读。

设计取舍：
- 目录与 plugin-data 分开（``~/.desktop-app/plugin-config/<id>.json``）：plugin-data 归子应用
  读写，plugin-config 只由宿主写、子应用经 SDK 只读，两套写权限不混在同一命名空间；
- 每个插件一个文件、内容为 ``{配置键: 值}``，便于人工排查与备份，无需数据库依赖；
- 写入走「临时文件 + os.replace」原子替换，避免进程中断留下半截文件；
- 读取时按 manifest 的 ``settings[]`` 合并默认值并丢弃未声明键，插件升级删掉配置项后旧值自然失效。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from desktop_app import paths
from desktop_app.protocol import MAX_SETTING_OPTIONS, PLUGIN_ID_PATTERN

logger = logging.getLogger(__name__)

# 单插件配置文件上限：配置项只有几十个标量，64 KiB 已足够宽松
MAX_CONFIG_BYTES = 64 * 1024

# text 类型取值的长度上限，避免用户把大段文本塞进配置
MAX_TEXT_LENGTH = 4096


class PluginConfigError(Exception):
    """插件配置读写失败的基类。"""


class InvalidPluginConfig(PluginConfigError):
    """插件 id 或配置内容不合法。"""


def _normalize_settings(settings: Sequence[Any]) -> list[dict[str, Any]]:
    """统一配置项形态：manifest 模型与 registry 透出的字典都可传进来。"""
    normalized: list[dict[str, Any]] = []
    for item in settings:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
        else:
            normalized.append(item.model_dump())
    return normalized


def _describe(value: Any) -> str:
    """把 Python 值翻译成中文类型名，用于「期望数字、实际收到字符串」这类错因。"""
    if isinstance(value, bool):
        return "布尔"
    if isinstance(value, (int, float)):
        return "数字"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, Mapping):
        return "对象"
    if isinstance(value, Sequence):
        return "数组"
    if value is None:
        return "null"
    return type(value).__name__


def merge_defaults(
    settings: Sequence[Any], stored: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """按 manifest 声明合并默认值与已存值；未在 manifest 中声明的历史键一律丢弃。"""
    stored = stored or {}
    values: dict[str, Any] = {}
    for item in _normalize_settings(settings):
        key = item["key"]
        values[key] = stored[key] if key in stored else item.get("default")
    return values


def _validate_one(item: Mapping[str, Any], value: Any) -> str | None:
    """校验单个配置项取值，合法返回 None，非法返回中文错因。"""
    label = item.get("label") or item["key"]
    kind = item.get("type", "text")
    if kind == "text":
        if not isinstance(value, str):
            return f"配置项「{label}」期望字符串，实际收到{_describe(value)}"
        if len(value) > MAX_TEXT_LENGTH:
            return f"配置项「{label}」长度超过上限（{len(value)} > {MAX_TEXT_LENGTH} 字符）"
        return None
    if kind == "boolean":
        if not isinstance(value, bool):
            return f"配置项「{label}」期望 true/false，实际收到{_describe(value)}"
        return None
    if kind == "number":
        # bool 是 int 的子类，必须显式排除，否则 true 会被当成 1
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"配置项「{label}」期望数字，实际收到{_describe(value)}"
        minimum = item.get("min")
        maximum = item.get("max")
        if minimum is not None and value < minimum:
            return f"配置项「{label}」不能小于 {minimum}（当前 {value}）"
        if maximum is not None and value > maximum:
            return f"配置项「{label}」不能大于 {maximum}（当前 {value}）"
        return None
    if kind == "select":
        if not isinstance(value, str):
            return f"配置项「{label}」期望字符串取值，实际收到{_describe(value)}"
        allowed = [option.get("value") for option in item.get("options", [])][:MAX_SETTING_OPTIONS]
        if value not in allowed:
            return f"配置项「{label}」取值 {value!r} 不在候选项中（可选：{'、'.join(map(str, allowed))}）"
        return None
    return f"配置项「{label}」声明了未知类型 {kind!r}"


def validate_values(settings: Sequence[Any], values: Mapping[str, Any]) -> list[str]:
    """校验一份待保存的配置（只校验实际传入的键，缺省键由 merge_defaults 补默认值）。

    返回中文错因列表，空列表表示通过；调用方在非空时不得落盘。
    """
    declared = {item["key"]: item for item in _normalize_settings(settings)}
    errors: list[str] = []
    for key in values:
        item = declared.get(key)
        if item is None:
            errors.append(f"配置项 {key!r} 未在 manifest 的 settings[] 中声明")
            continue
        error = _validate_one(item, values[key])
        if error:
            errors.append(error)
    return errors


class PluginConfigStore:
    """按插件隔离的配置读写。

    ``root`` 为配置根目录（默认 ``~/.desktop-app/plugin-config``），测试可传临时目录；
    所有读写都在同一把重入锁内完成，供 FastAPI 多线程调用。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or paths.plugin_config_dir()).resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        """返回配置根目录（便于测试与诊断）。"""
        return self._root

    def file(self, plugin_id: str) -> Path:
        """返回指定插件的配置文件路径。"""
        if not PLUGIN_ID_PATTERN.match(plugin_id):
            raise InvalidPluginConfig(f"非法插件 id: {plugin_id!r}")
        return self._root / f"{plugin_id}.json"

    def read(self, plugin_id: str) -> dict[str, Any]:
        """读取已保存的配置；文件不存在返回空字典，内容损坏时抛 PluginConfigError。"""
        target = self.file(plugin_id)
        with self._lock:
            if not target.is_file():
                return {}
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PluginConfigError(f"读取插件配置失败: {exc}") from exc
        if not isinstance(data, dict):
            raise PluginConfigError(f"插件配置 {plugin_id} 必须是 JSON 对象")
        return data

    def write(self, plugin_id: str, values: Mapping[str, Any]) -> None:
        """整体写入配置（先经调用方校验），原子替换目标文件。"""
        target = self.file(plugin_id)
        try:
            # sort_keys 让文件内容稳定，便于用户对比与版本管理
            payload = json.dumps(
                dict(values), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PluginConfigError(f"配置无法序列化为 JSON: {exc}") from exc
        if len(payload) > MAX_CONFIG_BYTES:
            raise PluginConfigError(
                f"配置超过大小上限（{len(payload)} > {MAX_CONFIG_BYTES} 字节）"
            )
        with self._lock:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{plugin_id}.", suffix=".tmp", dir=target.parent
                )
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(payload)
                    os.replace(tmp_name, target)
                finally:
                    Path(tmp_name).unlink(missing_ok=True)
            except OSError as exc:
                raise PluginConfigError(f"写入插件配置失败: {exc}") from exc
