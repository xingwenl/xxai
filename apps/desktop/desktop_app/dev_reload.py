"""开发期插件热重载：对插件目录做轻量指纹，供前端轮询发现变更。

只读、无外部依赖：本模块不监听文件系统事件，也不缓存状态，每次请求都按需
遍历插件目录计算指纹。由 ``DESKTOP_DEV_RELOAD`` 环境变量整体门控，生产环境
（未设置）不会付出任何磁盘遍历成本。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from . import paths

# 开发热重载开关：只有显式开启时前端才会轮询指纹端点
DEV_RELOAD_ENV = "DESKTOP_DEV_RELOAD"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 不参与指纹的目录：依赖、版本库、字节码与构建产物改了不算插件变更
_SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".git", ".venv", "dist"})

# 单个插件参与指纹的文件数上限：防止把大目录误纳入开发期轮询
MAX_WATCH_FILES = 2000

# 指纹取值长度（sha256 前 12 位十六进制，碰撞概率足够低且响应体小）
DIGEST_LENGTH = 12


def is_enabled() -> bool:
    """返回开发热重载是否开启（读环境变量，未设置即关闭）。"""
    return os.environ.get(DEV_RELOAD_ENV, "").strip().lower() in _TRUTHY


def _iter_plugin_dirs(root: Path) -> list[Path]:
    """列出插件根目录下的插件子目录，跳过隐藏目录（与 registry.scan 的口径一致）。"""
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")]


def plugin_fingerprint(plugin_dir: Path) -> str:
    """计算单个插件目录的指纹。

    指纹只由「相对路径 + 修改时间纳秒 + 文件大小」组成，不读文件内容：
    开发时保存一次文件 mtime 必然变化，足以触发重载，且大文件不产生 IO 成本。
    """
    entries: list[str] = []
    for current, dirnames, filenames in os.walk(plugin_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(current) / name
            try:
                stat = path.stat()
            except OSError:
                # 遍历期间文件被删除（编辑器原子保存）时跳过，下一轮轮询自然会拿到新指纹
                continue
            rel = path.relative_to(plugin_dir).as_posix()
            entries.append(f"{rel}\0{stat.st_mtime_ns}\0{stat.st_size}")
            if len(entries) >= MAX_WATCH_FILES:
                return _digest("\n".join(entries))
    return _digest("\n".join(entries))


def snapshot(builtin_dir: Path | None = None, user_dir: Path | None = None) -> dict[str, Any]:
    """返回当前插件树指纹快照。

    - ``revision``：整棵插件树的摘要，前端只需比较这一个值判断「有没有变」
    - ``plugins``：插件 id → 该插件目录的指纹，用于定位具体哪个插件变了
    """
    roots = [
        Path(builtin_dir) if builtin_dir else paths.builtin_plugins_dir(),
        Path(user_dir) if user_dir else paths.user_plugins_dir(),
    ]
    plugins: dict[str, str] = {}
    for root in roots:
        for plugin_dir in _iter_plugin_dirs(root):
            # 内置优先：同 id 的插件目录只认先出现的那份，与 registry.scan 一致
            plugins.setdefault(plugin_dir.name, plugin_fingerprint(plugin_dir))
    joined = "\n".join(f"{plugin_id}\0{digest}" for plugin_id, digest in sorted(plugins.items()))
    return {"revision": _digest(joined), "plugins": plugins}


def _digest(text: str) -> str:
    """对文本取定长摘要；空集合（没有任何插件文件）也返回空串而非固定哈希。"""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
