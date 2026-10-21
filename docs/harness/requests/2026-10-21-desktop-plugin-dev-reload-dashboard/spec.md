---
id: 2026-10-21-desktop-plugin-dev-reload-dashboard
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["插件 manifest 契约扩展（permissions 白名单新增 dashboard）", "新增宿主 HTTP 端点 GET /api/desktop/plugin-revision 与 SDK 公开方法 desktop.dashboard.*"]
---

## 目标与范围

一句话：第二刀给桌面宿主补上「开发热重载」与「首页概览卡」两项能力——

1. **开发热重载**：开发态以 `DESKTOP_DEV_RELOAD=1` 启动宿主后，改插件目录里的 `manifest.json` / 入口页 / 静态资源，前端自动感知并重新挂载对应 iframe，不必重启宿主、不必手动刷新页面，已打开的子应用与已注册工具不丢。
2. **首页概览卡（dashboard_card）**：子应用在 manifest 声明 `dashboard` 权限后可用 `desktop.dashboard.publish({...})` 往宿主首页「概览」区推一张卡（标题 + 指标 + 最近条目），点击卡片打开该应用，`clear()` 撤销；对齐 akm 的 `dashboard_card()` 插槽。

现状痛点（本仓库源码）：
- 插件目录只在启动时扫描：`apps/desktop/desktop_app/manager.py:82` `list_plugins()` 每次新建 `PluginRegistry(...).scan()`，所以后端总能读到新文件，但前端没有任何「变了」的信号；`apps/desktop/front/src/components/plugin-view.tsx` 的 iframe 只在首次渲染时加载，改完 HTML 只能刷新整页，而整页刷新会丢掉已打开子应用与 `tools` 注册（`App.tsx:763-777` 正是为工具列表做的预挂载）。
- 首页只有固定 4 格统计条（`App.tsx:1140-1160`，今日使用/最常用多为 `—` 占位）与工具网格；子应用的真实数字（记账本月支出、书签总数）只能等用户点开，没有任何「一眼看全」的位置。

**不做**：插件市场索引与 sha256（第三刀）；不引入文件监听依赖（watchdog/watchfiles）；react 类型子应用（`bookmarks-organizer`）是宿主编译产物，热重载不覆盖，README 明说要 `pnpm build`；概览卡不落盘（内存态，刷新后插件重新 publish）；概览卡不做图表/趋势/自定义操作按钮；不改 `state.json` 格式与既有 HTTP 契约。

## 来源与方案比较

实时依据（本机源码，2026-10-21）：
- akm 对应实现两处：`akm/plugins/plugin_manager.py:1234` `_hot_reload_plugin`（on_unload → 拆路由 → 重新导入 → on_load，三个入口含 HTTP/CLI/管理台）；首页卡片由 `akm/server.py` 的 `_build_plugin_dashboard_cards_section` 遍历实现 `dashboard_card() -> dict` 的插件渲染。
- 本仓库可复用形态：`apps/desktop/front/src/lib/tool-bridge.ts:28` 的内存注册表 + 订阅（概览卡照抄）、`apps/desktop/front/src/lib/runtime-status.ts` 的同形态 pub/sub、`apps/desktop/desktop_app/protocol.py:18` `KNOWN_PERMISSIONS` 白名单、`apps/desktop/tests/conftest.py` 的 `plugin_env` 夹具。

方案比较（热重载的变更检测）：

| 方案 | 检测方式 | 依赖 | 结论 |
|---|---|---|---|
| A 前端轮询全量插件列表 | 给 `PluginInfo` 加 mtime 字段 | 无 | 逼前端把「何时该重载」的判断做两遍，列表体积随插件数增长 |
| B 后端指纹 + 前端轮询（采纳） | sha256(各插件目录 (relpath, mtime_ns, size)) | 无 | 响应体极小，`enabled` 开关可整体门控，打包态零成本 |
| C 后端 asyncio 任务 + SSE | 同上但推流 | 无 | 断线重连/多窗口语义要自己实现，本轮过度设计 |
| D watchdog 文件监听 | OS 事件 | 新依赖 | 打包体积与跨平台差异不值，开发态 1.5s 轮询足够 |

方案比较（概览卡的数据来源）：

| 方案 | 数据来源 | 结论 |
|---|---|---|
| A manifest 静态声明 | 固定文案 | 拿不到真实数字，只是装饰 |
| B SDK 运行时 publish（采纳） | 插件自己 push | 与 tool-bridge 同形态、可实时更新、权限门控清晰 |
| C 插件提供 dashboard 小页面 iframe 嵌首页 | 独立 HTML | 首页嵌 N 个 iframe，样式/性能/权限面都失控 |

## 被否决的选项

- **引入 watchdog 做文件监听**：新运行时依赖还要过 PyInstaller 打包，跨平台 inotify/FSEvents 差异会让验证脚本不稳定；开发态 1.5s 轮询的收益差距看不出来。
- **后端 SSE 推送 revision**：要处理断连重连、多窗口、代理缓冲，本轮不需要；同源 127.0.0.1 轮一个 hash 的开销可忽略。
- **给 `PluginInfo` 加 mtime 让前端自己比较**：把「该不该重载」的判断散到前后端两处，且每次列表都带一堆 mtime；指纹只回一个 hash。
- **热重载覆盖 react 子应用**：那是宿主编译产物，等于自建前端 HMR，超出插件体系范围；README 明说 react 插件改完要 `pnpm build`。
- **概览卡用 manifest 静态声明**：只有固定文案，展示不了记账/书签这类真实数字。
- **概览卡用插件页面 iframe 嵌首页**：首页嵌多份 iframe、插件拿到整页视口与滚动，样式不可控，等于在首页再起一套 SDK 注入。
- **概览卡数据落 `plugin-data`**：那是插件自有数据的权威存储，宿主不该在渲染首页时读写它；内存态 + 插件启动 publish 足够。
- **把 dev 热重载与概览卡拆成两刀**：两块都不大，合在一刀共用一份 README、一份探针、一次验证更省周转。

## 停点判断

- 架构边界变化：否（改动全部在 `apps/desktop` 内，沿用既有 iframe + SDK 注入模型）
- 数据模型变化：否（无数据库；概览卡是内存注册表）
- API 契约变化：是（新增 `GET /api/desktop/plugin-revision`；`/api/desktop/settings` 增 `devReload`；`manifest.permissions` 白名单新增 `dashboard`；SDK 新增 `desktop.dashboard`）
- 鉴权或权限行为变化：是（`dashboard` 受新权限门控，未声明即抛「权限不足」）
- 结论：命中「API 契约变化」与「鉴权或权限行为变化」，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

后端 `apps/desktop/desktop_app/`：
- 新增 `dev_reload.py`：`DEV_RELOAD_ENV = "DESKTOP_DEV_RELOAD"`、`is_enabled()`（`1/true/yes/on`）；`snapshot(builtin_dir, user_dir)` 遍历插件子目录（跳过隐藏目录与 `node_modules`、`.git`、`__pycache__`、`dist`），对每个插件把排序后的 `(relpath, mtime_ns, size)` 做 sha256 取前 12 位，整树再哈希得 `revision`，返回 `{revision, plugins}`。
- `server.py`：新增 `GET /api/desktop/plugin-revision` → `{enabled, revision, plugins}`（未开启时 `enabled:false` 且不遍历磁盘）；`/api/desktop/settings` 增 `"devReload": bool`。
- `protocol.py`：`KNOWN_PERMISSIONS` 增 `dashboard`。

前端 `apps/desktop/front/src/`：
- `lib/api.ts`：`PluginRevision{enabled,revision,plugins}` 与 `getPluginRevision()`。
- 新增 `lib/dashboard-bridge.ts`：内存注册表 + pub/sub；`publishDashboardCard(plugin, payload)` 做宿主侧截断校验（标题 ≤40、指标 ≤4 条且 label ≤12/value ≤24、最近 ≤5 条且 text ≤80、空态 ≤40，非法返回 false）、`clearDashboardCard(pluginId)`、`getDashboardCards()`、`subscribeDashboardCards()`。
- `lib/desktop-sdk.ts`：新增可选 `dashboard?: { publish(card): boolean; clear(): void }`，按 `permissions.has('dashboard')` 门控，未声明走 `denied('dashboard')`。
- 新增 `components/dashboard-cards.tsx`：首页「概览」区（沿用现有毛玻璃卡片风格），渲染标题、指标、最近条目与空态；点击卡片调 `onOpen(id)`；无卡片时整区不渲染。
- `App.tsx`：①热重载轮询（`getPluginRevision()` 每 1500ms，仅 `enabled` 时）——revision 变化就重拉插件列表、对变化的插件 bump `reloadTokens`、toast「N 个插件已热重载」，react 类型只提示「需 pnpm build」不 remount；②`<PluginView>` 传 `reloadToken`；③首页统计条之后挂 `<DashboardCards onOpen={openAppByMode} />`；④把启动时静默挂载的判定从「`permissions` 含 `tools`」扩展为「含 `tools` 或 `dashboard`」——概览卡是子应用运行时 publish 到宿主内存的，iframe 不加载首屏就没有卡片（实现时由浏览器探针发现，补入本节）。
- `components/plugin-view.tsx`：接收 `reloadToken`，作为 iframe 的 `key`（`${plugin.id}:${reloadToken}`）以强制重新加载。
- `plugins/hello-world/`：manifest 增 `dashboard` 权限；`desktop-ready` 之后 publish 一张演示卡（2 条指标 + 2 条最近记录），作为活样板。

文档与验证：
- `apps/desktop/README.md`：SDK 能力表新增 `dashboard` 行、manifest 示例 permissions 补 `dashboard`、新增「开发热重载」「首页概览卡」两节（含 payload 契约与上限）、「开发一个插件」补步骤、FAQ（改了没反应 / 概览卡不显示）同步。
- `.codex/skills/desktop-agent-subapp/SKILL.md`、`docs/CHANGELOG.md`。
- 新增 `tools/harness/verify/2026-10-21-desktop-plugin-dev-reload-dashboard.sh` 与运行产出的 `verify.md`。

## 验收标准

1. `cd apps/desktop && poetry run pytest tests/ -q` 全绿；新增用例覆盖：revision 端点默认 `enabled:false`、开启后改动插件文件指纹变化且只影响该插件、隐藏目录与 `node_modules` 不计入、`settings.devReload` 字段存在、`dashboard` 进入权限白名单。
2. `pnpm --dir apps/desktop/front build` 通过（含 tsc 类型检查）。
3. headless 探针（`DESKTOP_DEV_RELOAD=1` + 临时 HOME）：改测试插件 `index.html` 的可见文本后**不刷新宿主页面**，探针轮询到 iframe 内文本更新；首页出现 hello-world 概览卡且指标/最近条目文案命中，点击卡片进入该应用。
4. 回归：未设 `DESKTOP_DEV_RELOAD` 时 `/api/desktop/plugin-revision` 返回 `enabled:false` 且前端不发轮询；未声明 `dashboard` 权限的插件调用 `desktop.dashboard.publish` 抛「权限不足」。
5. `python3 tools/harness/audit.py` 无本次新增 ERROR。
