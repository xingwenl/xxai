---
id: 2026-10-20-ledger-app
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["新增独立应用 apps/ledger 与 pnpm workspace 成员（跨 apps/ 改动）", "新增宿主通用能力契约：/api/desktop/plugin-data/*（插件级本地持久化）、SDK storage 语义变更、新增 permissions: tools", "新增子应用方法注册桥与全局助手挂载（desktop 全局 AI 面），工具名与入参 schema 一旦定下会被后续后台策略复用"]
---

## 目标与范围

一句话：新建独立子应用 `apps/ledger`（纯网页），构建产物作为 desktop iframe 插件安装；本地数据能力与智能体能力都由 desktop 宿主提供，子应用只负责界面 + 声明自己的方法。

- `apps/ledger`：独立 Vite + React + TS 项目，单页（hash 路由），产物 `dist/` 内自带 `manifest.json`/`icon.svg`，即插即用；不依赖桌面宿主也能 `pnpm dev` 起来（SDK 缺失时退化为 localStorage）。
- 记账能力（v1）：记一笔（支出/收入、金额、分类、备注、日期）、按月明细、月汇总（合计 + 分类占比）、删除、分类列表（内置 + 自定义）；金额以「分」存整数，界面显示元。
- 子应用对外方法（5 个，由子应用在页面内注册，宿主转发）：`ledger_add_entry`、`ledger_list_entries`、`ledger_month_summary`、`ledger_delete_entry`、`ledger_list_categories`。
- 宿主提供能力 ①：插件级本地持久化 `~/.desktop-app/plugin-data/<plugin_id>/<key>.json`，REST `GET/PUT/DELETE /api/desktop/plugin-data/{plugin_id}/{key}`，SDK `desktop.storage` 改为走宿主（不再用 localStorage）。
- 宿主提供能力 ②：方法注册桥——子应用 `desktop.tools.register({name,description,inputSchema,sideEffect}, execute)`，宿主聚合为「工具集合」；子应用卸载/注销时移除。
- 真实模型（m00689 追加）：助手默认接真实 AI Base Agent（deepseek），宿主用保存的 Embed Client 凭证换短期 token；5 个 `ledger_*` 方法走后台 HostToolPolicy + Agent/Client 双绑定 + schema 指纹三方一致校验；`DESKTOP_DEV_AGENT=1` 的规则式网关保留为离线兜底。
- 宿主全局助手：只有一个，挂在宿主壳层，用 ai-sdk 自带悬浮 UI（`createAgentClient({ui:{mode:'floating'}})` 单例），工具集合随子应用动态增减；子应用打开的 iframe 在切换页面后保持常驻（隐藏），保证其方法持续可用。
- 非目标：不碰 `apps/backend`；本批不做 MCP 端点与 SKILL.md（下一批）；不做多用户/云同步/预算/导入导出；不改多窗口逻辑（子应用默认 inline）。

## 来源与方案比较

已核实的宿主契约（本机源码）：
- 插件静态托管：`server.py:226-234` 的 `/apps/{plugin_id}` 与 `/apps/{plugin_id}/{file_path:path}` → `_serve_plugin_file`（`server.py:258-275`）按插件目录 `resolve()` 后 `is_relative_to` 防穿越、目录回退 `index.html`、**无 SPA 深链回退**；`registry.py:50` 生成 `entryUrl=/apps/{id}/{entry}`。⇒ 子应用必须单页或 hash 路由，Vite 必须 `base:'./'`。
- 插件校验：iframe 入口文件必须存在（`registry.py:86`）；`entry/icon` 必须是包内相对 POSIX 路径（`protocol.py:57-66`）；权限白名单 `{notify,settings,storage,events,http,platform,log}`（`protocol.py:18-20`）；SDK 在 iframe `load` 后注入并派发 `desktop-ready`（`plugin-view.tsx:28-41`），`sandbox="allow-scripts allow-same-origin allow-forms"`（`:88`）。
- 现有 SDK：`storage/settings` 走 localStorage（`desktop-sdk.ts:100-107`、`:91-98`），postMessage 只在自己 window 内闭环（`:117-134`），无方法注册能力。
- ai-sdk：`UIOptions` 见 `types.ts:190-226`（mode/position/theme/container/colors/window/layout/showAgentSteps）；嵌入与否只由是否传 `container` 决定（`ui/index.ts:42`），不传则挂 body 悬浮球 + 430×680 面板；样式必须 `import 'xxai-agent/style.css'`；`registerTools` 在 connect 前排队、`session_ready`/重连时重放（`websocket.ts:217-225`、`288-303`），`unregisterTool` 不通知服务端；`execute` 结果 >32KiB 失败、默认 10s 超时（`client.ts:1329-1347`）。

方案比较（子应用形态）：

| 方案 | 做法 | 结论 |
|---|---|---|
| 独立 apps/ledger + iframe 插件（采纳） | 独立构建、dist 即插件；数据与方法都由宿主提供 | 子应用可独立开发/分发，宿主只保留通用能力 |
| 宿主内置 react 子应用（上一版 spec） | 组件写进 `apps/desktop/front/src/components` | 不是独立项目，无法独立构建/安装，与「子应用是纯网页」不符 |
| 子应用自带后端 | 自带 HTTP/MCP 服务 | 纯静态页面承载不了，且违背「本地数据能力由宿主提供」 |
| 宿主实现账本业务 REST | 宿主 `/api/desktop/ledger/*` + Python 账本实现 | 账本逻辑漏进宿主，子应用成空壳，以后每个子应用都要改宿主 |

## 被否决的选项

- **把子应用做成 desktop 内置 react 插件**：不是独立项目，不能独立构建/分发，且违背「子应用是纯网页、数据能力在宿主」。
- **子应用自带后端或自带 MCP 服务**：纯静态 dist 无法承载；MCP 需要外部 agent 反向连本机，本地闭环验证不了，本批延后。
- **宿主实现账本 REST 与账本存储**：业务逻辑漏进宿主 Python，子应用变空壳；以后每新增子应用都要改宿主。
- **把工具实现放在宿主**：子应用无法自我描述能力，等于宿主替子应用定义方法。
- **工具只在子应用打开时可用（不保活 iframe）**：切走后全局助手工具消失，「全局助手 + 多子应用方法」不成立。
- **storage 继续用 localStorage**：不能满足「写到本地数据这种能力放在 desktop 里」，换设备/清缓存即丢，且无法被宿主统一管理。
- **子应用用 history 路由**：`/apps/{id}/{path}` 无 SPA 回退会 404，必须 hash 或单页。
- **每打开一次子应用就新建一个 AgentClient**：多实例多连接、工具重复注册；全局助手必须是单例。

## 停点判断

- 架构边界变化：**命中** —— 新增独立应用 `apps/ledger`（pnpm workspace 成员）与宿主两类通用能力（持久化、方法桥）。
- 数据模型变化：**命中** —— 新增插件级数据目录 `plugin-data/<plugin_id>/<key>.json` 与账本 JSON 结构。
- API 契约变化：**命中** —— 新增 plugin-data REST、SDK `storage` 语义变更、新增 `permissions: tools`。
- 鉴权或权限行为变化：**命中** —— 权限白名单增加 `tools`，storage 从 localStorage 迁移到宿主持久化。
- 核心资料缺失：不命中（宿主与 SDK 契约均已从本机源码核实）。
→ `approval.required: true`，实现前必须获得用户确认。

## 变更点

- 新增 `apps/ledger/`：`package.json`、`vite.config.ts`（`base:'./'`、`build.outDir:'dist'`、dev 代理 `/api`+`ws:true` → 8765）、`tsconfig.json`、`index.html`、`src/main.tsx`、`src/App.tsx`、`src/lib/types.ts`（账本模型/类型）、`src/lib/format.ts`（金额与日期格式化，纯函数）、`src/lib/desktop.ts`（宿主桥封装）、`src/lib/store.ts`（数据读写 + 串行写队列 + localStorage 降级）、`src/lib/tools.ts`（5 个方法的 schema 与 execute）、`src/styles.css`、`public/manifest.json`（`type:"iframe"`、`entry:"index.html"`、`permissions:["storage","tools","notify"]`）、`public/icon.svg`、`scripts/install-to-desktop.mjs`（把 `dist/` 同步到 `~/.desktop-app/plugins/ledger/`，可选 `--zip` 生成安装包）、`README.md`。
- `pnpm-workspace.yaml`：加 `- 'apps/ledger'`；根 `package.json`：加 `dev:ledger`/`build:ledger`。
- 新增 `apps/desktop/desktop_app/plugin_data.py`：`PluginDataStore`（目录 `~/.desktop-app/plugin-data/<plugin_id>/`、key 校验 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`、单值 ≤256KiB、临时文件 + `os.replace` 原子写、`threading.Lock`）。
- `apps/desktop/desktop_app/paths.py`：`plugin_data_dir()`。
- `apps/desktop/desktop_app/server.py`：`GET/PUT/DELETE /api/desktop/plugin-data/{plugin_id}/{key}`（插件必须存在且启用；value 走 JSON）。
- `apps/desktop/desktop_app/protocol.py`：`KNOWN_PERMISSIONS` 增加 `tools`；README 权限表同步。
- `apps/desktop/desktop_app/dev_agent.py`：本地开发用 ai-agent.v1 最小服务端（仅 `DESKTOP_DEV_AGENT=1` 时挂 `WS /api/v1/ws/agents/{agent_id}`），按客户端已注册的工具名做规则式意图（记一笔/月汇总/列明细/引导），不接 LLM；`GET /api/desktop/dev-agent/session` 返回占位 token。
- `apps/desktop/front/src/lib/desktop-sdk.ts`：`storage` 改为调用 plugin-data REST（保留 get/set/delete/list 既有方法形状）；新增 `tools` 能力（`register(defs, handlers)`/`unregister(names)`/`ready`），未声明权限仍抛「权限不足」。
- 新增 `apps/desktop/front/src/lib/tool-bridge.ts`：宿主侧工具集合（`registerPluginTools/getAllTools/onToolsChanged`），把子应用方法转成 ai-sdk `ToolDefinition`（`execute` 调子应用注册的 handler，异常/超时转错误）。
- 新增 `apps/desktop/front/src/lib/assistant.ts`：全局助手单例；`createAgentClient({ endpoint, platformId, agentId, getToken, ui:{mode:'floating',position:'right',theme:'auto'} })` + `import 'xxai-agent/style.css'`；订阅 tool-bridge 变化做 `registerTools`/`unregisterTool`；端点与 token 来自 `GET /api/desktop/agent-config`（dev agent 时返回本机 mock 网关参数），`enabled:false` 时不挂载。
- `apps/desktop/front/src/App.tsx`：挂载全局助手（`useEffect` 一次）；插件页改为「已打开过的 iframe 常驻 + 非当前页 `hidden`」，保证子应用方法不因切页消失。
- `apps/desktop/front/src/App.tsx`（m01088 修复）：声明了 `tools` 权限的子应用在 `plugins` 加载完成后**静默预挂载**（隐藏 iframe，不点开也加载），让全局助手在启动时就能拿到方法；否则用户不先打开「记账」就问助手，模型会看到空工具列表并回复「没有记账工具」。
- `apps/desktop/front/package.json`：新增 `xxai-agent: workspace:*`；根 `pnpm-lock.yaml` 更新。
- 测试：`apps/desktop/tests/test_plugin_data.py`（REST + 原子写 + key 校验 + 权限/未启用插件拒绝）、`apps/desktop/tests/test_dev_agent.py`（`TestClient.websocket_connect` 走 session_ready → message 流 → host_tool_call → host_tool_result）；`tools/harness/verify/2026-10-20-ledger-app.sh`（构建 ledger → 安装到临时插件目录 → 断言 `/apps/ledger/index.html` 与 assets 可访问、manifest 校验、pytest、tsc）。
- 真实模型接入（m00689 追加）：
  - `apps/ledger/tools.json`：5 个方法的唯一契约源（name/description/sideEffect/inputSchema），`apps/ledger/src/lib/tools.ts` 改为从中导入，避免与后台策略的 schema 指纹漂移。
  - 新增 `apps/desktop/desktop_app/agent_config.py`：`AgentBackendConfig`（baseUrl/clientId/clientSecret/agentId/hostToolNames，派生 ws 端点与 token 地址）、`AgentConfigStore`（`~/.desktop-app/agent.json`，0600 原子写）、`validate_local_origin`（只接受本机 http(s) 来源）、`issue_agent_token`（stdlib urllib 调 `POST /api/v1/embed/tokens`，解 JWT payload 取 platform_id）。
  - `apps/desktop/desktop_app/server.py`：`GET/PUT/DELETE /api/desktop/agent-config`、`POST /api/desktop/agent-token`（secret 不出宿主进程；`agent_token_issuer` 可注入便于测试）。
  - `apps/desktop/front/src/lib/assistant.ts`：remote 分支先换 token 拿 endpoint/platformId，`getToken` 每次经宿主刷新；dev 分支保留静态 token。
  - `apps/desktop/front/src/components/settings.tsx`：新增「智能体后端」配置区（地址/Client ID/Secret/Agent ID/方法名，保存/测试连接/清除）。
  - 新增 `apps/desktop/scripts/configure_ai_base.py`：管理员登录后把桌面来源并入 Embed Client `allowed_origins`，按 `tools.json` upsert 5 条 HostToolPolicy（canonical 指纹）并 PUT 绑定 Agent 与 Client。
  - `apps/backend/app/modules/host_tool/repositories.py`：修复 `create_policy` 只 flush 不 commit（事务在会话退出时回滚），补 commit + refresh 与回归测试。
  - `apps/desktop/tests/test_agent_config.py`：配置归一化/落盘权限/来源校验/token 换发与路由（含 issuer 打桩、错误码映射）。
  - `apps/desktop/README.md`、`apps/ledger/README.md`、`docs/CHANGELOG.md` 说明真实模型配置与故障排查。
- `apps/desktop/README.md` 新增「子应用能力契约（plugin-data / tools / 全局助手）」章节；`apps/ledger/README.md` 说明构建与安装；`docs/CHANGELOG.md` 同步。

## 验收标准

1. `pnpm install && pnpm --dir apps/ledger build` 通过，`apps/ledger/dist/` 含 `index.html`、`manifest.json`、`assets/*`，页面在浏览器里可直接打开使用（无宿主时数据落 localStorage，有宿主时落 plugin-data）。
2. `node apps/ledger/scripts/install-to-desktop.mjs` 后，桌面应用应用页出现「记账」卡片，点开进入记账页；可记一笔、看月汇总与明细、删除单条，重启应用后数据仍在（`~/.desktop-app/plugin-data/ledger/ledger.json`）。
3. 全局助手在宿主任意页面可用（悬浮球），其工具集合包含 5 个 `ledger_*` 方法；**启动后不打开记账应用也有这 5 个方法**（声明 `tools` 的子应用静默预挂载），切换到其他页面后工具仍在（iframe 常驻），卸载/停用记账插件后工具消失。
4. 设置 `DESKTOP_DEV_AGENT=1` 启动时：对助手说「今天午饭花了 35 块」→ 助手调用 `ledger_add_entry` → 记账页出现该条记录；说「这个月花了多少」→ 助手调用 `ledger_month_summary` 并读出合计。
5. README 中记录的 5 个方法名与入参 schema，与子应用注册、dev agent 调用、后续后台 host tool 策略三方一致。
6. 真实模型（m00689 追加）：设置页保存 AI Base 配置后「测试连接」成功；对助手说「今天午饭花了 35 块」→ 真实模型调用 `ledger_add_entry`，回复含金额与本月汇总；「这个月花了多少」→ 调 `ledger_month_summary`。后台策略/绑定/指纹任一不符时工具被网关静默忽略，需能从日志定位。
7. `cd apps/desktop && .venv/bin/python -m pytest -q` 全绿；`pnpm --dir apps/ledger build`、`pnpm --dir apps/desktop/front build`、`tsc --noEmit` 通过；verify 脚本通过。
