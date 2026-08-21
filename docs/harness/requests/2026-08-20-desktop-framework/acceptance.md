# 验收记录：Desktop 基础框架（应用页 / 设置页 + 插件化应用体系）

## 状态

- 当前状态：**待人工 GUI 验证后确认完成**
- 验收日期：2026-08-20（自动化部分）

## 验收结论

### 已满足（自动化证据）

- `pytest tests/` 47 项全部通过，覆盖协议校验、zip 安全、安装/卸载/启停、注册表合并、宿主服务接口与代理、插件共享样式。
- `ruff` 检查通过；宿主前端 `pnpm build` 成功；插件共享样式编译成功。
- 内置示例插件与 zip 打包脚本可运行。

### 2026-08-20 第 5 次变更（样式回归）结论

- 前端已恢复 Figma 原版样式基线并最小侵入接入真实插件数据（应用列表、插件 iframe 视图、侧栏设置入口、主题 / 星标持久化）；`pnpm build`、`tsc --noEmit`、`pytest` 47 项、`ruff` 全部通过。
- 本轻量变更未改变架构 / API 契约 / 权限模型；GUI 人工验证仍为最终验收前提。

### 2026-08-21 第 6 次变更（开发环境）结论

- 新增浏览器开发模式（`python -m desktop_app.server` + Vite dev proxy，HMR 免 build）与 pywebview 真窗口调试模式（`DESKTOP_DEV_FRONT` / `DESKTOP_DEBUG`）；修复 pywebview 隐私模式导致 localStorage 重启丢失的问题（`private_mode=False`）。
- `tsc --noEmit`、`pnpm build`、`pytest` 47 项、`ruff` 全部通过；端口监听与 Inspector 打开属本地人工验证项。

### 2026-08-21 第 7 次变更（插件视图双形态）结论

- 插件视图新增常规 / 全屏切换（顶部返回条「全屏」按钮，Esc 或「退出全屏」返回）；`tsc --noEmit` 与 `pnpm build` 通过，全屏切换交互待 GUI 人工确认。

### 2026-08-21 第 8 次变更（全屏 + 悬浮导航）结论

- 全屏时 iframe 覆盖全部应用视图，返回条与左侧导航悬浮于插件上方（复用 `Sidebar`，毛玻璃）；`tsc --noEmit` 与 `pnpm build` 通过，悬浮层级与交互待 GUI 人工确认。

### 2026-08-21 第 9 次变更（样式微调）结论

- 毛玻璃面板更通透、浅色文字加深（faint→mid、按钮文字加粗）；`tsc --noEmit` 与 `pnpm build` 通过，视觉效果待用户本地确认。

### 2026-08-21 第 10 次变更（侧边栏折叠内聚化）结论

- 折叠按钮移入侧栏底部，收起后由左边缘细把手展开；`tsc --noEmit` 与 `pnpm build` 通过，交互体验待用户本地确认。

### 2026-08-21 第 11 次变更（统一头部组件）结论

- 新增 `PageHeader`，应用页 / 插件视图 / 设置页三处头部统一；`tsc --noEmit` 与 `pnpm build` 通过，视觉一致性待用户本地确认。

### 2026-08-21 第 12 次变更（自动全屏 + 沉浸模式）结论

- 点击进入子应用自动全屏，全屏下头部与侧栏隐藏、边缘细毛玻璃把手展开；`tsc --noEmit` 与 `pnpm build` 通过，交互体验待用户本地确认。

### 待人工确认

- GUI 运行 `poetry run python -m desktop_app`：React 宿主壳导航、应用页 iframe 加载、SDK 能力调用、设置页安装/启停/卸载、主题持久化、重启后状态保持。
- 插件 iframe 内 `desktop-ready` 事件与宿主 SDK 注入在 pywebview 中的实际表现。

## 剩余风险

- 同源 iframe + `allow-same-origin` 的隔离强度有限：插件理论上可访问宿主 DOM，当前采用「用户主动安装即信任」模型，宿主壳无敏感数据；后续可升级独立 origin + postMessage RPC。
- HTTP 代理暂无域名白名单（SSRF 面），后续 request 增加白名单与权限 UI。
- 宿主前端构建依赖 `apps/desktop/front` 的 node_modules；`pnpm --dir apps/desktop/front build` 必须先于启动/打包执行。
- 插件共享样式编译依赖仓库内 `apps/front` 已安装依赖（离线复用 `@tailwindcss/node`）；若前端依赖缺失，需要先安装或改回 CLI。
- PyInstaller 打包产物（含 plugins 资源）未在本次重新构建验证。

## 变更文件清单

- `apps/desktop/`：`desktop_app/`（paths/protocol/security/registry/manager/host_api/server/main）、`front/`（React 宿主主项目：App/components/lib + 构建配置）、`static/`（插件共享 css + 回退页）、`src/input.css`、`plugins/hello-world/`、`scripts/`（make_plugin_zip.py、build_css.mjs）、`tests/`、`package.json`、`build/desktop.spec`、`README.md`
- `docs/harness/requests/2026-08-20-desktop-framework/`：research/spec/plan/verify/acceptance/meta

## 下一步

- 用户在本地完成 GUI 人工验证后，本 request 可流转为 `done`；如有问题按 `/fix` 记录增量修复。
