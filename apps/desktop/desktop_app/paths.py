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


def plugin_data_dir() -> Path:
    """返回子应用数据根目录（每个插件在其下拥有独立子目录）。"""
    return user_data_dir() / "plugin-data"


def plugin_config_dir() -> Path:
    """返回宿主维护的插件配置根目录（每个插件一个 <id>.json）。

    与 plugin-data 分开：plugin-data 归子应用读写，plugin-config 是宿主权威配置，
    子应用只能通过 SDK 只读，避免两套写权限混在同一命名空间。
    """
    return user_data_dir() / "plugin-config"


def plugin_log_file() -> Path:
    """返回插件事件日志文件（JSONL，超过上限轮转为 plugin.log.1）。"""
    return user_data_dir() / "plugin.log"


def plugin_backups_dir() -> Path:
    """返回插件升级前的旧版本备份根目录（每个插件一个子目录，保留最近若干份）。

    放在用户数据目录而不是插件目录里：备份不参与插件扫描，也不会被当成插件加载；
    出问题时用户可以直接把备份目录拷回 ``plugins/<id>`` 手动回滚。
    """
    return user_data_dir() / "plugin-backups"


def updates_dir() -> Path:
    """返回宿主应用更新包的落地目录（``updates/<version>/``）。"""
    return user_data_dir() / "updates"
