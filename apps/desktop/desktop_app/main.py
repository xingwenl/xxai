"""桌面窗口与内嵌服务编排：单进程内运行 uvicorn + pywebview。"""

from __future__ import annotations

import logging
import threading
import time

import uvicorn
import webview

from desktop_app.server import create_app

logger = logging.getLogger(__name__)


class Api:
    """通过 js_api 暴露给前端 JS 的 Python 对象。

    注意：pywebview 要求暴露的方法名不能以下划线开头。
    """

    def app_info(self) -> dict[str, str]:
        """返回应用基本信息，供页面展示。"""
        return {"name": "Desktop App", "version": "0.1.0"}


class EmbeddedServer:
    """在后台线程运行内嵌 uvicorn/FastAPI 服务。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        """启动服务并返回实际监听端口（port=0 时由系统分配）。"""
        config = uvicorn.Config(
            create_app(),
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
    server = EmbeddedServer()
    port = server.start()
    url = f"http://{server.host}:{port}"
    logger.info("内嵌服务已就绪: %s", url)

    window = webview.create_window(
        "Desktop App",
        url=url,
        js_api=Api(),
        width=1100,
        height=760,
        min_size=(800, 600),
    )
    # 窗口关闭时同步停止内嵌服务，避免残留进程
    window.events.closed += server.stop
    webview.start()
