# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir 模式，收集 front 产物、static 与 plugins 资源并补充 uvicorn 隐式导入。

应用名称、版本、图标与 Bundle ID 均从 desktop_app/app_config.py 读取，修改品牌信息时无需改本文件。
"""

import sys
from pathlib import Path

import PyInstaller.utils.hooks as hooks

# SPECPATH 为 spec 文件所在目录（apps/desktop/build），其上一级即项目根
project_root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(project_root))

from desktop_app.app_config import (  # noqa: E402
    APP_BUNDLE_ID,
    APP_NAME,
    APP_VERSION,
    ASSETS_DIR,
    ICON_ICNS,
    ICON_ICO,
)

static_src = project_root / "static"
plugins_src = project_root / "plugins"
front_dist_src = project_root / "front" / "dist"

hiddenimports = hooks.collect_submodules("uvicorn")

a = Analysis(
    [str(project_root / "desktop_app" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(static_src), "static"),
        (str(plugins_src), "plugins"),
        (str(front_dist_src), "front_dist"),
        # 品牌资源一并打入，运行时 Dock 图标（webview.start(icon=...)）可直接读取
        (str(ASSETS_DIR), "assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # 仅 Windows 使用 ico；macOS 图标由下方 BUNDLE 指定 icns
    icon=str(ICON_ICO) if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# macOS 上额外生成 .app 应用包
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICON_ICNS),
        bundle_identifier=APP_BUNDLE_ID,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13",
        },
    )
