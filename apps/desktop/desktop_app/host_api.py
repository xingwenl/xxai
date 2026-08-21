"""pywebview js_api 桥：仅宿主壳顶层页面可调用，插件一律走宿主 SDK。"""

from __future__ import annotations

import webbrowser

import webview

from desktop_app.app_config import APP_NAME, APP_VERSION
from desktop_app.manager import PluginManager


class HostApi:
    """暴露给宿主壳页面（window.pywebview.api）的 Python 侧能力。"""

    def __init__(self, manager: PluginManager | None = None) -> None:
        self._manager = manager or PluginManager()

    def app_info(self) -> dict[str, str]:
        """返回应用基本信息。"""
        return {"name": APP_NAME, "version": APP_VERSION}

    def plugins_summary(self) -> list[dict]:
        """返回插件列表摘要（宿主壳页面可直接复用）。"""
        return [p.to_dict() for p in self._manager.list_plugins()]

    def open_file_dialog(self) -> str | None:
        """打开原生文件对话框选择 zip 插件包，返回路径或 None。"""
        if not webview.windows:
            return None
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Zip 插件包 (*.zip)", "所有文件 (*.*)"),
        )
        return result[0] if result else None

    def open_urls(self, urls: list[str]) -> dict[str, int]:
        """在系统默认浏览器中批量打开书签 URL（仅允许 http/https，避免协议注入）。"""
        opened = 0
        failed = 0
        for url in urls:
            if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                try:
                    webbrowser.open(url, new=2)
                    opened += 1
                except Exception:
                    # 单个链接打开失败不影响其余链接
                    failed += 1
        return {"opened": opened, "failed": failed}
