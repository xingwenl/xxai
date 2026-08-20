"""资源路径解析：兼容开发模式与 PyInstaller 打包模式。"""

from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    """返回应用资源根目录。

    开发模式下为工程根目录（apps/desktop）；PyInstaller 打包后为解压资源目录
    sys._MEIPASS，此时 static 资源被打入该目录下。
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    """返回静态资源（HTML/CSS/JS）目录。"""
    return _base_dir() / "static"
