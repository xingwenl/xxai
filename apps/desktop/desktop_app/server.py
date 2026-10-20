"""FastAPI 应用工厂：托管宿主壳、插件静态资源与桌面管理接口。"""

from __future__ import annotations

import json
import mimetypes
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from desktop_app import agent_config
from desktop_app import bookmarks
from desktop_app import dev_agent
from desktop_app import metadata
from desktop_app import paths
from desktop_app.agent_config import AgentBackendConfig, AgentConfigError, AgentConfigNotConfigured, AgentConfigStore
from desktop_app.app_config import APP_NAME, APP_VERSION
from desktop_app.bookmarks import MAX_BOOKMARKS_PER_REPORT, BookmarkItem
from desktop_app.manager import PluginError, PluginExistsError, PluginManager, PluginNotFoundError
from desktop_app.plugin_data import MAX_VALUE_BYTES, PluginDataError, PluginDataStore, PluginDataTooLarge
from desktop_app.registry import PluginInfo
from desktop_app.security import MAX_ZIP_SIZE


class ProxyRequest(BaseModel):
    """HTTP 代理请求体（宿主 SDK 经权限门控后调用）。"""

    method: str = Field(default="GET", description="GET / POST")
    url: str = Field(description="目标 URL（仅 http/https）")
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, description="POST 请求体")


class PluginPatchRequest(BaseModel):
    """插件更新请求体：启停（enabled）与 remote 插件元数据编辑（name/description/iconUrl）。"""

    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    iconUrl: str | None = None


class InstallFromUrlRequest(BaseModel):
    """从 URL 安装远程壳插件请求体；name/description/iconUrl 为空时使用自动抓取结果。"""

    url: str
    name: str | None = None
    description: str | None = None
    iconUrl: str | None = None


class AgentConfigRequest(BaseModel):
    """智能体后端配置请求体；clientSecret 留空表示沿用已保存的 secret。"""

    baseUrl: str = Field(description="AI Base 地址，例如 http://127.0.0.1:8000")
    clientId: str = Field(description="Embed Client ID")
    clientSecret: str | None = Field(default=None, description="Embed Client Secret；留空表示沿用旧值")
    agentId: int = Field(description="Agent ID")
    hostToolNames: list[str] | None = Field(default=None, description="希望启用的方法名")


class AgentTokenRequest(BaseModel):
    """换短期 token 的请求体：origin 必须与页面真实来源一致。"""

    origin: str = Field(description="渲染层 window.location.origin")


class CollectBookmarksRequest(BaseModel):
    """Chrome 扩展书签上报请求体。"""

    bookmarks: list[BookmarkItem] = Field(description="扩展读取的书签列表")
    source: str = Field(default="chrome-extension", description="上报来源标识")


def create_app(
    manager: PluginManager | None = None,
    bookmarks_snapshot_path: Path | None = None,
    plugin_data: PluginDataStore | None = None,
    dev_agent_enabled: bool | None = None,
    agent_config_store: AgentConfigStore | None = None,
    agent_token_issuer: Callable[[AgentConfigStore, str], dict] | None = None,
) -> FastAPI:
    """构建内嵌 FastAPI 应用。

    - manager：插件管理器（默认自建）
    - bookmarks_snapshot_path：书签快照路径（默认用户数据目录）
    - plugin_data：子应用数据存储（默认用户数据目录）
    - dev_agent_enabled：是否挂载本地 mock 智能体网关；None 时读 DESKTOP_DEV_AGENT 环境变量
    - agent_config_store：AI Base 后端配置存储（默认 ~/.desktop-app/agent.json）
    - agent_token_issuer：换 token 的可注入实现（默认走真实 AI Base；测试用它打桩）
    """
    manager = manager or PluginManager()
    snapshot_path = bookmarks_snapshot_path or bookmarks.snapshot_path()
    data_store = plugin_data or PluginDataStore()
    config_store = agent_config_store or AgentConfigStore()
    token_issuer = agent_token_issuer or agent_config.issue_agent_token
    dev_enabled = dev_agent.is_enabled_by_env() if dev_agent_enabled is None else dev_agent_enabled
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

    @app.post("/api/desktop/plugins/install-from-url")
    def install_from_url(req: InstallFromUrlRequest) -> dict:
        """从公网 URL 安装远程壳插件：自动抓取元数据并落盘，返回插件与可嵌入性预检。"""
        try:
            plugin = manager.install_from_url(
                req.url,
                name=req.name,
                description=req.description,
                icon_url=req.iconUrl,
            )
        except PluginExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        frameable: bool | None = None
        try:
            frameable = metadata.preflight_frameable(req.url)
        except metadata.MetadataError:
            pass
        return {"plugin": plugin.to_dict(), "frameable": frameable}

    @app.patch("/api/desktop/plugins/{plugin_id}")
    def patch_plugin(plugin_id: str, req: PluginPatchRequest) -> dict:
        """更新插件：启停（所有插件）与 remote 插件元数据编辑（URL 保持不变）。"""
        try:
            plugin = None
            if req.enabled is not None:
                plugin = manager.set_enabled(plugin_id, req.enabled)
            if req.name is not None or req.description is not None or req.iconUrl is not None:
                plugin = manager.update_metadata(
                    plugin_id,
                    name=req.name,
                    description=req.description,
                    icon_url=req.iconUrl,
                )
            if plugin is None:
                raise HTTPException(400, "请求体为空，请提供 enabled 或元数据字段")
        except PluginNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"plugin": plugin.to_dict()}

    @app.post("/api/desktop/plugins/{plugin_id}/refresh-metadata")
    def refresh_metadata(plugin_id: str) -> dict:
        """重新抓取 remote 插件元数据（名称/描述/图标），id 与 url 保持不变。"""
        try:
            plugin = manager.refresh_metadata(plugin_id)
        except PluginNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
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

    # ---------- 子应用本地数据接口（plugin-data） ----------

    @app.get("/api/desktop/plugin-data/{plugin_id}")
    def list_plugin_data_keys(plugin_id: str) -> dict[str, list[str]]:
        """返回插件已持久化的数据键列表。"""
        _require_enabled_plugin(manager, plugin_id, ability="storage")
        try:
            return {"keys": data_store.keys(plugin_id)}
        except PluginDataError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/desktop/plugin-data/{plugin_id}/{key}")
    def get_plugin_data(plugin_id: str, key: str) -> Response:
        """读取单个数据键，返回存储时的原始 JSON。"""
        _require_enabled_plugin(manager, plugin_id, ability="storage")
        try:
            raw = data_store.read_raw(plugin_id, key)
        except PluginDataError as exc:
            raise HTTPException(400, str(exc)) from exc
        if raw is None:
            raise HTTPException(404, f"数据不存在: {key}")
        return Response(content=raw, media_type="application/json")

    @app.put("/api/desktop/plugin-data/{plugin_id}/{key}")
    async def put_plugin_data(plugin_id: str, key: str, request: Request) -> dict[str, bool]:
        """写入单个数据键；请求体为任意合法 JSON 值，大小受 MAX_VALUE_BYTES 限制。"""
        _require_enabled_plugin(manager, plugin_id, ability="storage")
        body = await request.body()
        if not body:
            raise HTTPException(400, "请求体为空，需要一个 JSON 值")
        if len(body) > MAX_VALUE_BYTES:
            raise HTTPException(400, f"值超过大小上限（{MAX_VALUE_BYTES} 字节）")
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"请求体不是合法 JSON: {exc}") from exc
        try:
            data_store.write(plugin_id, key, value)
        except PluginDataTooLarge as exc:
            raise HTTPException(400, str(exc)) from exc
        except PluginDataError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/desktop/plugin-data/{plugin_id}/{key}")
    def delete_plugin_data(plugin_id: str, key: str) -> Response:
        """删除单个数据键（不存在时同样返回 204，保持幂等）。"""
        _require_enabled_plugin(manager, plugin_id, ability="storage")
        try:
            data_store.delete(plugin_id, key)
        except PluginDataError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(status_code=204)

    # ---------- 全局助手连接配置 ----------

    @app.get("/api/desktop/agent-config")
    def get_agent_config() -> dict:
        """返回全局助手连接参数：优先 AI Base 配置，其次本地 mock 网关。

        渲染层拿到的配置不含 client_secret；真正的短期 token 由 agent-token 接口现换。
        """
        try:
            config = config_store.load()
        except AgentConfigError as exc:
            # 配置损坏时明确报出来，避免用户以为是「没配」而反复保存
            return {"enabled": False, "mode": "remote", "reason": str(exc)}
        if config is not None:
            return {"enabled": True, "mode": "remote", **config.redacted()}
        if dev_enabled:
            return dev_agent.session_payload()
        return {
            "enabled": False,
            "reason": "未配置智能体后端：请在设置页填写 AI Base 连接信息，或用 DESKTOP_DEV_AGENT=1 启动本地网关",
        }

    @app.put("/api/desktop/agent-config")
    def save_agent_config(req: AgentConfigRequest) -> dict:
        """保存 AI Base 连接配置；secret 留空时沿用已保存的值。"""
        previous: AgentBackendConfig | None
        try:
            previous = config_store.load()
        except AgentConfigError:
            previous = None
        secret = (req.clientSecret or "").strip()
        if not secret and previous is not None:
            secret = previous.client_secret
        if not secret:
            raise HTTPException(400, "首次配置必须填写 Embed Client Secret")
        try:
            config = AgentBackendConfig(
                base_url=req.baseUrl,
                client_id=req.clientId,
                client_secret=secret,
                agent_id=req.agentId,
                host_tool_names=tuple(req.hostToolNames or agent_config.DEFAULT_HOST_TOOL_NAMES),
            )
            config_store.save(config)
        except AgentConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "config": config.redacted()}

    @app.delete("/api/desktop/agent-config")
    def clear_agent_config() -> dict:
        """清除 AI Base 配置（之后回落到本地 mock 网关或停用助手）。"""
        removed = config_store.clear()
        return {"ok": True, "removed": removed}

    @app.post("/api/desktop/agent-token")
    def create_agent_token(req: AgentTokenRequest) -> dict:
        """用服务端保存的 Client 凭证换短期 token；secret 不出宿主进程。"""
        try:
            agent_config.validate_local_origin(req.origin)
        except AgentConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            return token_issuer(config_store, req.origin)
        except AgentConfigNotConfigured as exc:
            raise HTTPException(400, str(exc)) from exc
        except AgentConfigError as exc:
            raise HTTPException(502, str(exc)) from exc

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

    # ---------- AI Base HTTP 同源转发（避免渲染层跨域直连后端） ----------

    forward_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    # 只透传与鉴权/内容协商相关的头，其余（Origin/Referer 等）由宿主与 urllib 生成。
    forward_headers = ("authorization", "content-type", "accept", "x-request-id")

    @app.api_route("/api/v1/{path:path}", methods=forward_methods)
    async def ai_base_proxy(request: Request, path: str) -> Response:
        """把 ai-sdk 的 HTTP 调用（附件上传、会话列表等）转发到 AI Base。

        渲染层只认宿主 origin，因此后端不需要给桌面来源配 CORS；Embed Client
        secret 始终留在宿主进程内，透传的只有渲染层拿到的短期 token。
        """
        if ".." in Path(path).parts:
            raise HTTPException(400, "非法转发路径")
        try:
            config = config_store.load()
        except AgentConfigError as exc:
            raise HTTPException(503, f"智能体配置不可用: {exc}") from exc
        if config is None:
            raise HTTPException(503, "尚未配置智能体后端，请在设置页填写 AI Base 地址与 Embed Client 凭证")

        target = f"{config.base_url}/api/v1/{path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        headers = {
            name: value for name, value in request.headers.items() if name.lower() in forward_headers
        }
        body = await request.body()
        data = body if body and request.method not in {"GET", "HEAD"} else None
        upstream = urllib.request.Request(target, data=data, method=request.method, headers=headers)
        try:
            response = await run_in_threadpool(_urlopen, upstream, 30)
        except urllib.error.HTTPError as exc:
            return Response(
                content=exc.read(),
                status_code=exc.code,
                media_type=exc.headers.get("Content-Type", "application/json"),
            )
        except Exception as exc:  # 网络错误统一转为 502
            raise HTTPException(502, f"转发 AI Base 请求失败: {exc}") from exc

        with response:
            content = response.read()
            media_type = response.headers.get("Content-Type", "application/octet-stream")
            if response.status == 204 or not content:
                return Response(status_code=response.status, media_type=media_type)
            return Response(content=content, status_code=response.status, media_type=media_type)

    # ---------- 插件静态资源 ----------

    @app.get("/apps/{plugin_id}")
    def plugin_index(plugin_id: str) -> FileResponse:
        """插件入口：目录路径自动回退到 index.html。"""
        return _serve_plugin_file(manager, plugin_id, "index.html")

    @app.get("/apps/{plugin_id}/{file_path:path}")
    def plugin_static(plugin_id: str, file_path: str) -> FileResponse:
        """插件静态资源服务：按插件目录解析相对路径，拒绝路径穿越。"""
        return _serve_plugin_file(manager, plugin_id, file_path or "index.html")

    # ---------- 本地 mock 智能体网关（仅开发闭环，不连 AI Base） ----------

    if dev_enabled:
        dev_agent.register_dev_agent(app)

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


def _require_enabled_plugin(
    manager: PluginManager,
    plugin_id: str,
    ability: str | None = None,
) -> PluginInfo:
    """校验插件存在、可用且已声明所需能力；作为子应用数据接口的统一前置检查。"""
    try:
        plugin = manager.get(plugin_id)
    except PluginNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if plugin.error:
        raise HTTPException(400, f"插件 manifest 异常: {plugin.error}")
    if not plugin.enabled:
        raise HTTPException(403, f"插件已停用: {plugin_id}")
    if ability and ability not in plugin.permissions:
        raise HTTPException(403, f"插件未声明 {ability} 能力，无法使用该接口")
    return plugin


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
