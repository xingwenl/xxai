"""应用元信息统一配置：名称、Logo、版本号等集中维护。

修改应用品牌信息（名称 / 版本 / Bundle ID）时只需改本文件；
窗口标题、内嵌服务、前端 SDK、打包产物与系统图标均从本模块读取。
"""

from __future__ import annotations

from pathlib import Path

# 应用名称（窗口标题、产物名、前端展示）
APP_NAME = "WW"

# 应用版本（设置页「框架信息」、/api/health、macOS Info.plist 均使用）
APP_VERSION = "0.2.5"

# macOS .app 的 bundle identifier（发布前建议替换为自己的域名反写）
APP_BUNDLE_ID = "com.ww.desktop"

# Logo 资源：替换 assets/icon.png 后运行 scripts/make_icons.py 重新生成 icns/ico
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICNS = ASSETS_DIR / "icon.icns"
ICON_ICO = ASSETS_DIR / "icon.ico"
