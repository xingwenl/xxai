"""Chrome 书签整理：过滤、去重、按域名分组与快照持久化。

整理结果只在本机流转（扩展上报 → 本服务处理 → 宿主页面展示），
快照以 JSON 文件形式持久化，不依赖数据库。
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from desktop_app import paths

# 快照文件名与单次上报上限（书签数量可能远多于打开的标签）
SNAPSHOT_FILE_NAME = "bookmarks-snapshot.json"
MAX_BOOKMARKS_PER_REPORT = 20000

# 浏览器保留页面或扩展内部页面的协议前缀，整理时直接剔除
_INTERNAL_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "edge://",
    "about:",
    "devtools://",
    "view-source:",
    "chrome-search://",
    "file://",
)


class BookmarkItem(BaseModel):
    """扩展上报的单条书签。"""

    id: str = Field(default="", description="书签 id")
    title: str = Field(default="", description="书签标题")
    url: str = Field(default="", description="书签 URL")
    folderPath: str = Field(default="", description="所属文件夹路径，如 书签栏/开发")


def is_internal_url(url: str) -> bool:
    """判断是否为浏览器保留页面（chrome:// 等无法整理的内容）。"""
    return url.lower().startswith(_INTERNAL_PREFIXES)


def normalize_url(url: str) -> str:
    """URL 归一化：scheme/host 转小写并去掉 fragment，用于去重。"""
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def domain_of(url: str) -> str:
    """提取展示用域名：去掉端口与 www. 前缀，空时回退 unknown。"""
    netloc = urllib.parse.urlsplit(url).netloc
    host = netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host or "unknown"


def organize_bookmarks(bookmarks: list[BookmarkItem]) -> dict:
    """过滤内部页面 + URL 去重 + 按用户文件夹分类，返回整理快照。

    去重时优先保留文件夹路径更短（更接近收藏夹根）的书签；
    按用户自己的书签文件夹路径（folderPath）分组，空路径归入「未分类」；
    分组按路径字典序排列，组内按标题排序。
    """
    valid = [b for b in bookmarks if b.url and not is_internal_url(b.url)]
    ordered = sorted(valid, key=lambda x: (len(x.folderPath), x.title.lower(), x.id))

    seen: set[str] = set()
    unique: list[BookmarkItem] = []
    for item in ordered:
        key = normalize_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # 按用户自己的书签文件夹路径分组；空路径（收藏夹根直接存放）归入「未分类」
    grouped: dict[str, list[BookmarkItem]] = {}
    for item in unique:
        folder = item.folderPath or "未分类"
        grouped.setdefault(folder, []).append(item)
    groups = [
        {"folderPath": folder, "count": len(items), "items": [i.model_dump() for i in items]}
        for folder, items in sorted(grouped.items(), key=lambda kv: kv[0])
    ]
    return {
        "collectedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(bookmarks),
        "unique": len(unique),
        "filtered": len(bookmarks) - len(valid),
        "groups": groups,
    }


def snapshot_path() -> Path:
    """返回快照文件路径（位于用户数据目录）。"""
    return paths.user_data_dir() / SNAPSHOT_FILE_NAME


def save_snapshot(snapshot: dict, path: Path | None = None) -> None:
    """原子写入快照（临时文件 + rename），避免写入一半时崩溃留下损坏文件。"""
    target = path or snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".bookmarks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)


def load_snapshot(path: Path | None = None) -> dict | None:
    """读取最近一次快照；文件不存在或损坏时返回 None。"""
    target = path or snapshot_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
