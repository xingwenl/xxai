"""FastAPI 应用工厂：托管宿主壳、插件静态资源与桌面管理接口。"""

from __future__ import annotations

import mimetypes
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from desktop_app import paths
from desktop_app import bookmarks
from desktop_app.app_config import APP_NAME, APP_VERSION
from desktop_app.bookmarks import MAX_BOOKMARKS_PER_REPORT, BookmarkItem
from desktop_app.manager import PluginError, PluginExistsError, PluginManager, PluginNotFoundError
from desktop_app.security import MAX_ZIP_SIZE


class ProxyRequest(BaseModel):
    """HTTP 代理请求体（宿主 SDK 经权限门控后调用）。"""

    method: str = Field(default="GET", description="GET / POST")
    url: str = Field(description="目标 URL（仅 http/https）")
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, description="POST 请求体")


class SetEnabledRequest(BaseModel):
    """启停请求体。"""

    enabled: bool


class CollectBookmarksRequest(BaseModel):
    """Chrome 扩展书签上报请求体。"""

    bookmarks: list[BookmarkItem] = Field(description="扩展读取的书签列表")
    source: str = Field(default="chrome-extension", description="上报来源标识")


def create_app(
    manager: PluginManager | None = None,
    bookmarks_snapshot_path: Path | None = None,
) -> FastAPI:
    """构建内嵌 FastAPI 应用；可传入共享 PluginManager 与书签快照路径（默认自建）。"""
    manager = manager or PluginManager()
    snapshot_path = bookmarks_snapshot_path or bookmarks.snapshot_path()
    app = FastAPI(title=APP_NAME, version=APP_VERSION)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """健康检查：供页面与外部探测确认内嵌服务已就绪。"""
        return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}

    # ---------- 桌面管理接口 ----------

    @app.get("/api/desktop/plugins")
    def list_plugins() -> dict:
        """返回内置 + 用户插件列表（含启停状态）。"""
        return {"items": [p.to_dict() for p in manager.list_plugins()]}

    @app.post("/api/desktop/plugins/install")
    async def install_plugin(request: Request) -> dict:
        """上传 zip 插件包并安装（请求体为 zip 原始字节流）。"""
        total = 0
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_ZIP_SIZE:
                    tmp_path.unlink(missing_ok=True)
                    raise HTTPException(400, f"zip 文件超过大小限制（{total} > {MAX_ZIP_SIZE}）")
                tmp.write(chunk)
        if total == 0:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(400, "请求体为空，请上传 zip 插件包")
        try:
            plugin = manager.install_zip(tmp_path)
            return {"plugin": plugin.to_dict()}
        except PluginExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.patch("/api/desktop/plugins/{plugin_id}")
    def set_enabled(plugin_id: str, req: SetEnabledRequest) -> dict:
        """启用/禁用插件。"""
        try:
            plugin = manager.set_enabled(plugin_id, req.enabled)
        except PluginNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"plugin": plugin.to_dict()}

    @app.delete("/api/desktop/plugins/{plugin_id}")
    def uninstall_plugin(plugin_id: str) -> Response:
        """卸载用户插件（内置插件返回 403）。"""
        try:
            manager.uninstall(plugin_id)
        except PluginNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PluginError as exc:
            raise HTTPException(403, str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/desktop/settings")
    def desktop_settings() -> dict[str, str]:
        """返回框架信息（版本与关键目录）。"""
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "pluginsDir": str(paths.builtin_plugins_dir()),
            "userDataDir": str(paths.user_data_dir()),
        }

    # ---------- Chrome 书签整理接口 ----------

    @app.post("/api/desktop/bookmarks/collect")
    def collect_bookmarks(req: CollectBookmarksRequest) -> dict:
        """接收扩展上报的书签并整理：过滤、去重、按域名分组，保存快照。"""
        if len(req.bookmarks) > MAX_BOOKMARKS_PER_REPORT:
            raise HTTPException(400, f"单次上报书签数量超过上限（{MAX_BOOKMARKS_PER_REPORT}）")
        snapshot = bookmarks.organize_bookmarks(req.bookmarks)
        bookmarks.save_snapshot(snapshot, snapshot_path)
        return snapshot

    @app.get("/api/desktop/bookmarks/summary")
    def bookmarks_summary() -> dict:
        """返回最近一次整理的书签快照；尚无快照时返回 404。"""
        snapshot = bookmarks.load_snapshot(snapshot_path)
        if snapshot is None:
            raise HTTPException(404, "尚未整理过书签，请先在 Chrome 扩展中点击「整理书签」")
        return snapshot

    @app.post("/api/desktop/proxy")
    def proxy(req: ProxyRequest) -> Response:
        """HTTP 代理：解决插件页面访问外部接口的 CORS 限制。"""
        method = req.method.upper()
        if method not in {"GET", "POST"}:
            raise HTTPException(400, "仅支持 GET / POST")
        if not req.url.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "仅支持 http/https 代理")
        data = req.body.encode("utf-8") if req.body else None
        request = urllib.request.Request(req.url, data=data, method=method, headers=req.headers)
        try:
            with _urlopen(request, timeout=15) as resp:
                return Response(
                    content=resp.read(),
                    media_type=resp.headers.get("Content-Type", "application/octet-stream"),
                )
        except urllib.error.HTTPError as exc:
            return Response(
                content=exc.read(),
                status_code=exc.code,
                media_type=exc.headers.get("Content-Type", "text/plain"),
            )
        except Exception as exc:  # 网络错误统一转为 502
            raise HTTPException(502, f"代理请求失败: {exc}") from exc

    # ---------- 插件静态资源 ----------

    @app.get("/apps/{plugin_id}")
    def plugin_index(plugin_id: str) -> FileResponse:
        """插件入口：目录路径自动回退到 index.html。"""
        return _serve_plugin_file(manager, plugin_id, "index.html")

    @app.get("/apps/{plugin_id}/{file_path:path}")
    def plugin_static(plugin_id: str, file_path: str) -> FileResponse:
        """插件静态资源服务：按插件目录解析相对路径，拒绝路径穿越。"""
        return _serve_plugin_file(manager, plugin_id, file_path or "index.html")

    # ---------- 静态资源挂载（顺序：/css → / 宿主前端） ----------

    # 插件共享样式：/css/tailwind.css 供插件页面引用
    app.mount(
        "/css",
        StaticFiles(directory=paths.static_dir() / "css", html=False),
        name="plugin-css",
    )
    # 宿主前端：React 构建产物；未构建时回退到 static/ 的提示页
    front_dist = paths.front_dist_dir()
    if front_dist.is_dir():
        app.mount("/", StaticFiles(directory=front_dist, html=True), name="front")
    else:
        app.mount("/", StaticFiles(directory=paths.static_dir(), html=True), name="static-fallback")
    return app


def _urlopen(request: urllib.request.Request, timeout: int = 15):
    """独立封装便于测试注入；生产行为等价 urllib.request.urlopen。"""
    return urllib.request.urlopen(request, timeout=timeout)


def _serve_plugin_file(manager: PluginManager, plugin_id: str, file_path: str) -> FileResponse:
    """按插件目录安全解析并返回文件；目录自动回退 index.html。"""
    try:
        plugin = manager.get(plugin_id)
    except PluginNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if plugin.error:
        raise HTTPException(400, f"插件 manifest 异常: {plugin.error}")
    root = plugin.dir.resolve()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404, "not found")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(404, "not found")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


if __name__ == "__main__":
    """开发模式：独立启动 API 服务（默认 127.0.0.1:8765），供 Vite dev server 代理。"""
    import os

    import uvicorn

    port = int(os.environ.get("DESKTOP_API_PORT", "8765"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
