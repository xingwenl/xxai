"""zip 安全解压：限制大小与条目数，拒绝路径穿越、绝对路径与符号链接。"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

# 安装限制：总大小 / 条目数 / 单文件大小（测试可通过 monkeypatch 调整）
MAX_ZIP_SIZE = 20 * 1024 * 1024
MAX_ENTRIES = 200
MAX_FILE_SIZE = 10 * 1024 * 1024


class ZipSecurityError(ValueError):
    """zip 安全检查失败。"""


def validate_zip_entry_name(name: str) -> None:
    """校验 zip 条目路径：拒绝空路径、绝对路径、路径穿越与反斜杠变体。"""
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        raise ZipSecurityError("zip 条目路径非法（空路径或绝对路径）")
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        raise ZipSecurityError("zip 条目路径非法（路径穿越）")


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """受控解压：全部条目通过安全校验后写入 dest。

    调用方负责保证 dest 目录为空或已清理，避免与历史残留文件混合。
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ZipSecurityError(f"zip 条目数超过限制（{len(infos)} > {MAX_ENTRIES}）")
        # 第一轮：统一校验全部条目，避免半写入
        for info in infos:
            validate_zip_entry_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ZipSecurityError("zip 包含符号链接条目，已拒绝")
            if info.file_size > MAX_FILE_SIZE:
                raise ZipSecurityError(f"zip 单文件超过限制（{info.filename}）")
        # 第二轮：解压并累计总大小
        total = 0
        for info in infos:
            target = dest / info.filename.replace("\\", "/")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ZIP_SIZE:
                        raise ZipSecurityError("zip 解压后总大小超过限制")
                    out.write(chunk)
