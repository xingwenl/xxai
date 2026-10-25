"""桌面窗口与内嵌服务编排：单进程内运行 uvicorn + pywebview。"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

import uvicorn
import webview

from desktop_app.api_port import DEFAULT_API_PORT, resolve_api_port
from desktop_app.app_config import APP_NAME, ICON_PNG
from desktop_app.host_api import HostApi
from desktop_app.manager import PluginManager
from desktop_app.server import create_app
from desktop_app.windows import AppWindowManager

logger = logging.getLogger(__name__)


class EmbeddedServer:
    """在后台线程运行内嵌 uvicorn/FastAPI 服务。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, app=None) -> None:
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._app = app or create_app()

    def start(self) -> int:
        """启动服务并返回实际监听端口（port=0 时由系统分配）。"""
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="embedded-uvicorn", daemon=True)
        self._thread.start()
        return self._wait_until_ready()

    def _wait_until_ready(self, timeout: float = 15.0) -> int:
        """等待 uvicorn 完成启动，返回实际端口。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._thread is not None and not self._thread.is_alive():
                # uvicorn 绑定失败会直接退出线程（例如端口被别的进程占住）
                raise RuntimeError(f"内嵌 FastAPI 服务启动失败：端口 {self.port} 无法绑定")
            if self._server is not None and self._server.started and self._server.servers:
                # uvicorn 启动完成后可从其绑定的 socket 获取实际端口
                sock = self._server.servers[0].sockets[0]
                return int(sock.getsockname()[1])
            time.sleep(0.05)
        raise RuntimeError("内嵌 FastAPI 服务启动超时")

    def stop(self) -> None:
        """请求停止服务并等待后台线程退出。"""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=10)


def run() -> None:
    """应用入口：先启动内嵌服务，再创建 pywebview 窗口加载页面。"""
    manager = PluginManager()
    # 端口策略见 desktop_app/api_port.py：开发态固定 8765 供 Vite 代理，
    # 正式/打包态同样默认 8765——页面 origin 必须落在 AI Base Embed Client 的
    # allowed_origins 里，否则助手换 token 会被拒（401 origin is not allowed）后静默不挂载
    dev_front = os.environ.get("DESKTOP_DEV_FRONT") == "1"
    api_port = resolve_api_port(os.environ.get("DESKTOP_API_PORT"), dev_front)
    server = EmbeddedServer(port=api_port, app=create_app(manager))
    port = server.start()
    if dev_front:
        url = "http://127.0.0.1:8443"
        logger.info("开发模式：窗口加载 Vite dev server %s（需先执行 pnpm --dir apps/desktop/front dev）", url)
    else:
        url = f"http://{server.host}:{port}"
        if port != api_port:
            # 端口被占用才退回随机端口：窗口能开，但该 origin 换不到 token，助手不会显示
            logger.warning(
                "默认端口 %s 已被占用（可能已有一个宿主实例在运行），本次改用 %s："
                "该来源不在 AI Base 的 allowed_origins 里，桌面助手（ai-sdk 智能体）将无法连接。"
                "关闭占用端口的进程后重启即可恢复。",
                DEFAULT_API_PORT,
                port,
            )
    logger.info("内嵌服务已就绪: %s", url)

    # 子应用窗口管理器：与 HostApi 共用同一实例，主窗口关闭时统一清理
    windows = AppWindowManager()
    api = HostApi(manager, base_url=url, windows=windows)
    window = webview.create_window(
        APP_NAME,
        url=url,
        js_api=api,
        width=1100,
        height=760,
        min_size=(800, 600),
    )

    def _on_master_closed() -> None:
        """主窗口关闭：先销毁子窗口（它们依赖内嵌服务），再停服务，避免残留进程。"""
        windows.close_all()
        server.stop()

    window.events.closed += _on_master_closed
    webview.start(
        # DESKTOP_DEBUG=1 时启用 Web Inspector（macOS 可右键 → 检查元素）
        debug=os.environ.get("DESKTOP_DEBUG") == "1",
        # 关闭隐私模式：保留 localStorage，主题 / 星标 / 插件设置与存储跨重启保持
        private_mode=False,
        # macOS 运行时设置 Dock/应用图标：开发模式没有 .app 包也能显示 Logo
        # （pywebview Cocoa 后端调用 setApplicationIconImage_；GTK/QT 同样生效）
        icon=str(ICON_PNG) if sys.platform == "darwin" and ICON_PNG.is_file() else None,
    )
