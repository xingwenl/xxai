# 验证记录

## 执行命令

以下命令均在 `apps/desktop/` 目录下、Poetry 虚拟环境（Python 3.12）中执行：

1. `poetry run pytest tests/ -q`
2. `poetry run ruff check .`
3. `pnpm --dir apps/desktop/front build`
4. `pnpm --dir apps/desktop/front exec tsc --noEmit`
5. `poetry run python -c "from desktop_app.server import create_app; from desktop_app.manager import PluginManager; app = create_app(PluginManager()); print('app factory ok:', app.title)"`
6. 真实站点抓取回归（`fetch_site_metadata("https://example.com/")` 与 `https://github.com/`、`preflight_frameable`）：沙箱 DNS 受限无法执行，审批服务 503，留待用户本机验证

### 2026-08-21 追加：本地 URL 支持

1. `poetry run pytest tests/ -q`
2. `poetry run ruff check .`
3. `pnpm --dir apps/desktop/front build` + `pnpm --dir apps/desktop/front exec tsc --noEmit`

## 预期结果

- `pytest`：全部通过（原 55 个存量测试 + 新增协议/抓取器/remote 插件测试）。
- `ruff check .`：无告警。
- 前端 `vite build` 成功、`tsc --noEmit` 无类型错误。
- app 工厂可正常构建宿主 FastAPI 应用。
- 真实站点回归：可嵌入站点 iframe 打开、不可嵌入站点提示并可系统浏览器打开；需用户本机执行。

## 实际结果

1. `pytest`：**110 passed**（新增 `test_metadata.py` 28 项：SSRF 公网校验、og/manifest/title 三级抓取链、SVG 消毒、图标大小/类型限制、嵌入性预检；新增 `test_remote_plugin.py` 17 项：安装/重复安装/冲突后缀、手动降级、编辑/刷新、宿主接口契约；`test_protocol.py` 增加 remote 协议校验）。仅有 starlette/httpx 弃用警告，不影响结果。
2. `ruff check .`：All checks passed。
3. `vite build`：构建成功（dist 产出约 252 KB JS / 19 KB CSS）。
4. `tsc --noEmit`：无输出，类型检查通过。
5. app 工厂：`app factory ok: WW`，FastAPI 应用创建成功。
6. 真实站点抓取：沙箱内 DNS 解析被拒（`域名解析失败: example.com`）；申请网络批准时审批服务返回 503，无法在本会话完成，按规则不做绕过，留待用户本机执行。

### 本地 URL 支持（追加验证结果）

1. `pytest`：**114 passed**（在 110 基础上新增/调整：回环与私有网段地址校验放行 6 项、本地 URL 安装 1 项、链路本地拒绝 2 项）。
2. `ruff check .`：All checks passed。
3. 前端构建与 `tsc --noEmit`：通过；设置页提示文案已更新为「支持公网、localhost 与本机局域网地址」。

### fix：remote 插件 iframe 空白（同日追加）

- 问题：`.plugin-frame` 默认 `opacity: 0`，`is-ready` 仅在 SDK 注入 `onLoad` 回调添加；remote 纯壳跳过注入，iframe 加载成功但永远透明。
- 修复：remote 分支 iframe 直接附加 `is-ready` 类。
- 复核：`pnpm exec tsc --noEmit` 通过；`vite build` 成功（`index-Bbbw_CHp.js`）。GUI 显示需用户重启桌面应用后确认。

## 失败项与例外

- 真实站点抓取与桌面 GUI 回归（设置页添加应用、iframe 打开、系统浏览器降级）未能在沙箱执行：DNS 受限 + 审批服务 503，属环境限制，非实现缺陷；需用户本机桌面环境人工回归。
- 本地 URL 验证依赖本机实际运行的服务：沙箱无法起真实 HTTP 服务，已用注入 fetcher 覆盖安装链路，建议用户用 `python -m http.server` 起一个本地服务实测。
- 自动审批服务返回 503（`http://127.0.0.1:8800/v1/responses`），已停止重试并记录，未尝试绕过。
