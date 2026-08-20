"""FastAPI 应用工厂：托管静态页面并提供健康检查接口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from desktop_app.paths import static_dir


def create_app() -> FastAPI:
    """构建内嵌 FastAPI 应用。

    路由顺序说明：/api/health 必须先于根路径挂载注册，否则会被
    StaticFiles 的 / 挂载拦截。
    """
    app = FastAPI(title="Desktop App", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """健康检查：供页面与外部探测确认内嵌服务已就绪。"""
        return {"status": "ok", "service": "desktop-app", "version": "0.1.0"}

    # html=True 时访问目录路径会自动返回 index.html
    app.mount("/", StaticFiles(directory=static_dir(), html=True), name="static")
    return app
