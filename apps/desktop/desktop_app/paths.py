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
    """返回静态资源目录（当前仅保留插件共享 CSS 产物）。"""
    return _base_dir() / "static"


def front_dist_dir() -> Path:
    """返回宿主前端构建产物目录（apps/desktop/front/dist）。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "front_dist"  # noqa: SLF001
    return _base_dir() / "front" / "dist"


def builtin_plugins_dir() -> Path:
    """返回内置插件目录（随应用分发的只读插件）。"""
    return _base_dir() / "plugins"


def user_data_dir() -> Path:
    """返回用户数据目录：跨平台统一使用 ~/.desktop-app。"""
    return Path.home() / ".desktop-app"


def user_plugins_dir() -> Path:
    """返回用户安装的插件目录（zip 导入后存放于此）。"""
    return user_data_dir() / "plugins"


def state_file() -> Path:
    """返回插件启停状态持久化文件。"""
    return user_data_dir() / "state.json"
