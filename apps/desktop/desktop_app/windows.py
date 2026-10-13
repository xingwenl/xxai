"""子应用窗口管理：同一应用只保留一个窗口，主窗口关闭时统一销毁。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import webview

logger = logging.getLogger(__name__)

# 子窗口尺寸与主窗口保持一致，保证小屏也能完整放下应用界面
CHILD_WIDTH = 1100
CHILD_HEIGHT = 760
CHILD_MIN_SIZE = (800, 600)


def deep_link(base_url: str, app_id: str) -> str:
    """构造宿主壳深链（浏览器模式用），不带窗口标记。

    浏览器标签页不是原生窗口，壳在里面应当把 Esc / 返回 当作「退回应用列表」，
    而不是去关一个不存在的窗口，所以这里不加 child=1。
    """
    return f"{base_url.rstrip('/')}/#/app/{quote(app_id, safe='')}"


def child_url(base_url: str, app_id: str) -> str:
    """构造子窗口地址：宿主壳深链 + child=1 标记。

    child=1 让壳知道「自己跑在独立窗口里」，Esc / 返回应当关闭窗口而不是退出全屏。
    不能靠 hash 判断这件事：插件随时可以用 SDK 改 hash 切视图，会误判。
    """
    return f"{base_url.rstrip('/')}/?child=1#/app/{quote(app_id, safe='')}"


class AppWindowManager:
    """按 app_id 维护子窗口。

    `create_window` 以参数注入（默认 pywebview.create_window），单测可传替身，
    从而在无 GUI 环境下覆盖去重、聚焦与清理逻辑。
    """

    def __init__(self, create_window: Callable[..., Any] | None = None) -> None:
        self._windows: dict[str, Any] = {}
        self._create_window = create_window or webview.create_window

    @property
    def app_ids(self) -> list[str]:
        """当前已打开的子应用 id 列表。"""
        return list(self._windows)

    def open(self, app_id: str, url: str, title: str, js_api: Any = None) -> dict[str, Any]:
        """打开子应用窗口；该应用已有窗口时聚焦，返回 {opened, reused}。"""
        existing = self._windows.get(app_id)
        if existing is not None:
            try:
                # restore() 处理最小化过的窗口，show() 把它提到最前
                existing.restore()
                existing.show()
                return {"opened": True, "reused": True}
            except Exception:
                # 用户已经手动关掉了该窗口（closed 回调可能尚未到达）：
                # 旧引用失效，丢弃后按新建处理，避免「点了没反应」
                logger.warning("子窗口 %s 复用失败，改为新建", app_id)
                self._windows.pop(app_id, None)
        window = self._create_window(
            title,
            url=url,
            js_api=js_api,
            width=CHILD_WIDTH,
            height=CHILD_HEIGHT,
            min_size=CHILD_MIN_SIZE,
        )
        self._windows[app_id] = window
        self._bind_closed(app_id, window)
        return {"opened": True, "reused": False}

    def is_child(self, window: Any) -> bool:
        """判断窗口是否由本管理器创建（用于区分主窗口与子应用窗口）。"""
        return any(window is current for current in self._windows.values())

    def close(self, window: Any) -> bool:
        """销毁指定子窗口；传入的不是子窗口时返回 False。"""
        for app_id, current in list(self._windows.items()):
            if current is window:
                self._windows.pop(app_id, None)
                return self._destroy(app_id, window)
        return False

    def close_all(self) -> int:
        """销毁全部子窗口，返回成功销毁的数量（主窗口关闭时调用）。"""
        destroyed = 0
        for app_id, window in list(self._windows.items()):
            self._windows.pop(app_id, None)
            if self._destroy(app_id, window):
                destroyed += 1
        return destroyed

    def _destroy(self, app_id: str, window: Any) -> bool:
        try:
            window.destroy()
            return True
        except Exception:
            # 窗口可能已被用户关闭；属于正常路径，不影响其余窗口的清理
            logger.warning("子窗口 %s 销毁失败", app_id)
            return False

    def _bind_closed(self, app_id: str, window: Any) -> None:
        """窗口被用户手动关闭时从注册表摘除，避免下次点击复用失效引用。"""
        closed = getattr(getattr(window, "events", None), "closed", None)
        if closed is None:
            return
        closed += lambda: self._windows.pop(app_id, None)
