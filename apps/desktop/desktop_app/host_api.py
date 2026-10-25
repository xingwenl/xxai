"""pywebview js_api 桥：仅宿主壳顶层页面可调用，插件一律走宿主 SDK。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import webbrowser
from typing import Any

import webview

from desktop_app.app_config import APP_NAME, APP_VERSION
from desktop_app.manager import PluginManager
from desktop_app.protocol import DEFAULT_OPEN_MODE, OPEN_MODES
from desktop_app.registry import PluginInfo
from desktop_app.windows import AppWindowManager, child_url, deep_link

logger = logging.getLogger(__name__)


def _appkit_open(target: str) -> bool | None:
    """进程内用 NSWorkspace 打开 URL（等价于系统 open，但同步返回真实结果）。

    返回 None 表示 pyobjc 不可用或调用异常，调用方应改用子进程兜底。
    pywebview 的 macOS 后端本身依赖 pyobjc，所以这条路径在实际运行环境里总是可用。
    """
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL
    except Exception:
        return None
    try:
        return bool(NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(target)))
    except Exception:
        logger.exception("NSWorkspace 打开 %s 失败", target)
        return None


def _macos_open(target: str, timeout: float = 5.0) -> bool | None:
    """macOS 上打开 URL。

    返回 None 表示当前平台不适用（交给 webbrowser）；返回 False 表示确实尝试过但失败。

    优先走进程内的 NSWorkspace，理由有两条：
    - 标准库 webbrowser 的 osascript 实现没有「控制其它应用」自动化权限时**静默失败**，
      而且 AppleScript 执行成功也不代表浏览器真的起来了，无法据此回执；
    - `/usr/bin/open` 子进程在 GUI 应用里会卡在前台激活握手上（实测 5 秒超时），
      进程内调用则 0.01 秒级返回 LaunchServices 的真实结果。
    子进程只作为 pyobjc 不可用时的兜底；兜底里超时也不再算失败——那通常只是 open
    自己不退出，URL 早已交给系统了。
    """
    if sys.platform != "darwin":
        return None
    launched = _appkit_open(target)
    if launched is not None:
        return launched
    opener = shutil.which("open") or "/usr/bin/open"
    try:
        proc = subprocess.Popen(  # noqa: S603
            [opener, target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.warning("调用 %s 打开 %s 失败：%s", opener, target, exc)
        return False
    try:
        return proc.wait(timeout=timeout) == 0
    except subprocess.TimeoutExpired:
        logger.info("%s 未在 %.1f 秒内退出，按已交给系统处理：%s", opener, timeout, target)
        return True


class HostApi:
    """暴露给宿主壳页面（window.pywebview.api）的 Python 侧能力。"""

    def __init__(
        self,
        manager: PluginManager | None = None,
        base_url: str = "",
        windows: AppWindowManager | None = None,
    ) -> None:
        self._manager = manager or PluginManager()
        # 宿主壳自身的访问地址（dev 为 Vite，生产为内嵌服务），用于拼子应用深链
        self._base_url = base_url
        self._windows = windows or AppWindowManager()

    def app_info(self) -> dict[str, str]:
        """返回应用基本信息。"""
        return {"name": APP_NAME, "version": APP_VERSION}

    def plugins_summary(self) -> list[dict]:
        """返回插件列表摘要（宿主壳页面可直接复用）。"""
        return [p.to_dict() for p in self._manager.list_plugins()]

    def open_file_dialog(self) -> str | None:
        """打开原生文件对话框选择 zip 插件包，返回路径或 None。"""
        window = self._current_window()
        if window is None:
            return None
        result = window.create_file_dialog(
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

    def open_app(self, app_id: str, mode: str | None = None) -> dict[str, Any]:
        """在系统浏览器或新的原生窗口里打开子应用。

        mode 为空时取插件 manifest 声明的 open_mode；`inline` 不在这里处理，
        只回执给前端——壳内展开是前端自己的一份视图状态，后端插手会和它抢。
        """
        plugin = next((p for p in self._manager.list_plugins() if p.id == app_id), None)
        if plugin is None:
            return self._result(False, None, reason="not_found")
        resolved = mode.strip().lower() if isinstance(mode, str) else None
        if resolved not in OPEN_MODES:
            resolved = plugin.open_mode
        if resolved not in OPEN_MODES:
            resolved = DEFAULT_OPEN_MODE
        if resolved == "inline":
            return self._result(True, "inline")
        target = self._target_url(plugin, resolved)
        if target is None:
            # 没有壳基址就拼不出深链（例如脱离 main.run() 的嵌入场景）
            return self._result(False, resolved, reason="no_base_url")
        if resolved == "browser":
            if not self._open_in_browser(target):
                return self._result(False, "browser", target=target, reason="browser_failed")
            return self._result(True, "browser", target=target)
        # 子窗口同样挂宿主桥，壳里的插件才能拿到 SDK；
        # remote 插件是外部页面，绝不能把桥暴露给它（它本身就是零权限纯壳）
        bridge = None if plugin.type == "remote" else self
        opened = self._windows.open(plugin.id, target, plugin.name, js_api=bridge)
        return self._result(True, "window", target=target, **opened)

    def _open_in_browser(self, target: str) -> bool:
        """在系统默认浏览器里打开目标地址，返回是否真的起来了。"""
        launched = _macos_open(target)
        if launched is not None:
            return launched
        try:
            # webbrowser 的返回值就是「有没有找到能打开的浏览器」，不能忽略
            return bool(webbrowser.open(target, new=2))
        except Exception:
            logger.exception("调用系统浏览器打开 %s 失败", target)
            return False

    def close_current_window(self) -> bool:
        """关闭发起调用的子应用窗口。

        主窗口调用时返回 False，前端据此退化为「退出全屏」，这样同一个
        Esc / 返回 处理在两种窗口里都成立。
        """
        return self._windows.close(self._current_window())

    def _target_url(self, plugin: PluginInfo, mode: str) -> str | None:
        """子应用在窗口 / 浏览器里的目标地址。

        只有原生子窗口才带 `?child=1` 标记：浏览器标签页不是原生窗口，
        Esc / 返回 在它里面应当退回应用列表，而不是去关一个不存在的窗口。
        """
        if plugin.type == "remote" and plugin.url:
            # 远程插件是外部站点，直接开它自己的地址即可，壳的深链对它没有意义
            return plugin.url
        if not self._base_url:
            return None
        if mode == "window":
            return child_url(self._base_url, plugin.id)
        return deep_link(self._base_url, plugin.id)

    def _current_window(self) -> Any:
        """定位发起本次调用的窗口。

        多窗口下 windows[0] 不再一定是调用方（对话框会挂到错误的窗口上），
        因此优先用 active_window()；取不到时回退主窗口。
        """
        window = webview.active_window()
        if window is not None:
            return window
        return webview.windows[0] if webview.windows else None

    @staticmethod
    def _result(
        ok: bool, mode: str | None, target: str | None = None, reason: str | None = None, **extra: Any
    ) -> dict[str, Any]:
        """统一 js_api 返回结构，便于前端区分失败原因。"""
        result: dict[str, Any] = {
            "ok": ok,
            "mode": mode,
            "target": target,
            "reused": bool(extra.pop("reused", False)),
        }
        if reason:
            result["reason"] = reason
        result.update(extra)
        return result
