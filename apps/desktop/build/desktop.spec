# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir 模式，收集 static 资源并补充 uvicorn 隐式导入。"""

import sys
from pathlib import Path

import PyInstaller.utils.hooks as hooks

# SPECPATH 为 spec 文件所在目录（apps/desktop/build），其上一级即项目根
project_root = Path(SPECPATH).resolve().parent
static_src = project_root / "static"

hiddenimports = hooks.collect_submodules("uvicorn")

a = Analysis(
    [str(project_root / "desktop_app" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(static_src), "static")],
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
    name="desktop-app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="desktop-app",
)

# macOS 上额外生成 .app 应用包
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="desktop-app.app",
        icon=None,
        bundle_identifier="com.example.desktop-app",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13",
        },
    )
