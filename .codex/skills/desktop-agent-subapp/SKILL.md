---
name: desktop-agent-subapp
description: Use when building a new sub-app under `apps/<name>` for the desktop host (`apps/desktop`), or extending one to expose methods to the global ai-sdk assistant — creating the sub-app project and plugin manifest, registering tools the model can actually call, persisting sub-app data through the host, wiring a real AI Base model, or debugging "the assistant can't see my tools".
---

# 桌面子应用接入全局助手

## 触发场景

- 在 `apps/` 下新建一个要装进桌面宿主的子应用（`apps/<name>` → `~/.desktop-app/plugins/<id>`）
- 给已有子应用加「助手能调用的方法」（记账、待办、收藏……任何可被模型操作的能力）
- 子应用要落本地数据（`~/.desktop-app/plugin-data/<id>/`）
- 要把桌面助手从本地 mock 切到真实 AI Base 模型，或排查助手看不到工具

## 心智模型：两条边界

1. **子应用是纯网页**。它只有 HTML/JS/CSS，没有 Node、没有数据库、没有密钥。它跑在宿主 iframe 里，通过宿主注入的 `window.desktop` 拿能力。
2. **能力在宿主侧**。持久化（plugin-data）、方法注册（tool-bridge）、助手连接（ai-sdk 单例）、模型凭据（`~/.desktop-app/agent.json`）全在 `apps/desktop`。子应用只说「我有什么方法、我需要存什么」，不碰后端、不碰 AI Base。

工具调用链：子应用 `desktop.tools.register` → 宿主 tool-bridge → 全局助手的 ai-sdk 连接 → 后端网关（策略指纹 + 绑定裁决）→ 模型。**任何一环缺失，模型都只会说「我没有这个工具」。**

## 实施流程

### 1. 先定方法契约（唯一来源 `tools.json`）

在 `apps/<name>/tools.json` 写全部方法的 `name/description/sideEffect/inputSchema`，页面和宿主脚本都读这一份。

- 命名 `<子应用>_<动作>_<对象>`，如 `ledger_add_entry`；必须匹配后端 `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`，用下划线不要用点。
- `sideEffect` 取 `none | navigation | write | financial | external`；动钱、动不可逆数据用 `financial` / `write`。
- `inputSchema` 必须 `{"type":"object",...}`；描述写清楚单位和格式（金额是「元」还是「分」必须在 description 里说死）。
- 返回值保持小对象（JSON ≤32KiB），调用超时默认 10s。

**完成判据**：`tools.json` 里每个方法都能用一句话说清「模型什么时候该调它、参数是什么、返回什么」。

### 2. 搭子应用工程

照抄 `apps/ledger` 的骨架（Vite + React + TS，无后端依赖）：

- `vite.config.ts` 必须 `base: './'`（宿主按 `/apps/<id>/` 挂载，绝对路径会 404）；路由用 hash 或单页。
- `public/manifest.json`：`id` 与目录名一致、匹配 `^[a-z0-9][a-z0-9_-]*$`，`type: "iframe"`，`entry: "index.html"`。
- `permissions` 按需声明，缺一个对应能力就是 `权限不足` 抛错：`storage`（落数据）、`tools`（注册方法）、`notify`（提示）、`settings`（读取宿主配置与订阅变更）、`dashboard`（首页概览卡）。
- 需要用户可调参数时，在 manifest 里声明 `settings[]`（`text`/`number`/`boolean`/`select`），设置页会自动渲染表单，**不要自己搭设置页**；子应用侧用 `desktop.settings.getConfig()` 读、`desktop.settings.onChanged()` 订阅变更（只读，写入只能在宿主设置页）。
- 想让宿主首页「概览」区显示业务数字时，声明 `dashboard` 权限，并在 `desktop-ready` 之后调用 `desktop.dashboard.publish({ title, metrics: [{label, value}], recent: [{text, hint}], emptyText })`；卡片是展示层，宿主会把超长字段截断（标题 ≤40、指标 ≤4 条、最近 ≤5 条），详情仍放在子应用里；什么都不推就不显示。声明 `dashboard` 的子应用会在宿主启动时静默挂载（隐藏 iframe），所以卡片一进首页就有，但启动脚本要轻；可参考 `apps/desktop/plugins/hello-world`。
- 在根 `pnpm-workspace.yaml` 追加 `- 'apps/<name>'`。
- 提供 `scripts/install-to-desktop.mjs`：把 `dist/` 复制到 `~/.desktop-app/plugins/<id>`，支持 `--target`（最终插件目录）与 `--json`。
- **发新版本只要改索引里的 version，宿主会自己认出「可升级」**：设置页在市场条目上显示「更新到 vX」，点一下就走「下载 → 校 sha256/大小 → 校包内 manifest id/version → 备份旧目录到 `~/.desktop-app/plugin-backups/<id>/`（保留最近 3 份）→ 同盘 rename 原子替换 → 失败自动回滚」，`plugin-data/` 与 `plugin-config/` 不动、启用状态沿用。因此：manifest 的 `id` 必须长期稳定（换 id 等于换插件，旧数据不会跟过去）、`version` 每次必须真的变大（宿主按 `desktop_app/version.py::version_greater` 逐段比较：`1` 与 `1.0.0` 相等、`-beta` 视为比正式版旧、降级会被拒绝）、升级后要能读旧的 `plugin-data`（不兼容就自己在子应用里做迁移）。内置插件与 `type=remote` 壳插件不参与市场升级。
- 想让用户免 zip 安装，就把包上架到插件市场：一条命令 `cd apps/desktop && .venv/bin/python scripts/make_plugin_release.py <id>`（默认 hello-world，`--bump patch` 代改版本）。它会校验 manifest、确定性打包到 `apps/desktop/market/packages/`（同内容重复打包 sha256 一致）、更新 `apps/desktop/market/index.json`（含 Gitee `mirrors`）并打印提交推送命令；`--check-only` 只校验不出包，索引版本更高或同版本换包会被拦下（`--force` 放行）。旧入口 `make_plugin_zip.py` 仍可用（= `--no-index --out-dir dist`）。宿主安装时会校 sha256、校包内 `manifest.json` 的 id/version，再走既有安装流程（校验失败不落文件）。本地联调用 `DESKTOP_PLUGIN_MARKET_URL=file:///abs/path/index.json`，关闭市场用 `DESKTOP_PLUGIN_MARKET=0`；CLI 用 `scripts/plugin_market.py list|install|entry|verify`。

**完成判据**：`pnpm --dir apps/<name> build` 产出 `dist/manifest.json`，`node scripts/install-to-desktop.mjs` 后宿主插件列表能看到它（重启应用）。

### 3. 注册方法（子应用侧）

在 `window.desktop` 注入后（等 `desktop-ready`，宿主在 iframe load 时派发）**立即**注册，且只注册一次：

- `await desktop.tools.register(defs, handlers)`，`defs` 直接来自 `tools.json`，`handlers` 同名映射。
- handler 入参是 `unknown`，自己校验后再用；抛错会被宿主包装成中文错误回给模型。
- 页面要在浏览器里也能跑（无宿主时回退 localStorage），别让缺能力直接崩。

**完成判据**：宿主启动后（**不用点开子应用**），后端日志出现 `Host tool registration: [...]` 或 mock 网关打出收到的工具名。

### 4. 数据落宿主磁盘

- `desktop.storage` 全是异步：`await get/set/delete/keys`；key 匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，单值 ≤256KiB。
- 数据位置 `~/.desktop-app/plugin-data/<plugin_id>/<key>.json`；**卸载插件不清数据**。
- 写入串行化（一个 `mutate()` 队列），并发写同一 key 会互相覆盖。
- 需要浏览器调试时，用独立 localStorage key 存一份，首次拿到宿主后迁移过去。

**完成判据**：关掉应用重开，数据还在；`ls ~/.desktop-app/plugin-data/<id>/` 能看到对应 JSON。

### 5. 接真实模型（可选，需要 AI Base 后端）

宿主配置在 `~/.desktop-app/agent.json`（0600，含 client secret），渲染层只拿短期 token：

1. 设置页或直接写配置：`baseUrl`、`clientId`、`clientSecret`、`agentId`、`hostToolNames`（默认取子应用方法名）。
2. 跑 `python apps/desktop/scripts/configure_ai_base.py`：把桌面 origin 并进 Embed Client 的 `allowed_origins`，按 `tools.json` upsert 工具策略并绑定 Agent + Client（幂等，可重复跑；先 `--dry-run` 看变更）。
3. origin 必须是 `http://127.0.0.1:<port>`（生产 8765 / Vite dev 8443），且**必须**出现在 `allowed_origins` 里，否则换 token 被拒。

**完成判据**：宿主 `POST /api/desktop/agent-token` 返回 token，token claims 的 `host_tools` 包含你的方法名。

### 6. 验证闭环

按 `tools/harness/verify/2026-10-20-ledger-app.sh` 的顺序来，缺哪步补哪步：

1. `poetry run pytest tests/`（宿主后端，新增/改动的 REST 与网关逻辑）
2. `pnpm --dir apps/<name> build` + 断言 `dist/manifest.json` 与产物里的方法名
3. `pnpm --dir apps/desktop/front build`（宿主前端 tsc + vite）
4. 安装探针：假 `HOME` 下 `install-to-desktop.mjs --target <home>/.desktop-app/plugins/<id> --json`
5. **预挂载探针**：无头 Chrome 打开宿主首页（不带 hash），grep 注册日志 —— 证明「不点开子应用也有方法」
6. 协议回环：`websockets` 客户端连 `DESKTOP_DEV_AGENT=1` 的本地网关，发 `host_tools_register` + `message_send`，断言收到 `host_tool_call`
7. 真实模型探针：换 token 连 `ws://127.0.0.1:8000/api/v1/ws/agents/<id>`，断言模型真的调用了你的方法

**完成判据**：verify 脚本退出码 0 或 3（3=有未执行项，须在 `verify.md` 列明），且第 5、6 步都真的跑过。

## 硬规则（踩过的坑）

- **宿主负责预挂载，子应用负责尽早注册**：宿主会把 manifest 声明了 `tools` 的插件启动即静默挂载（隐藏 iframe）。子应用不要等用户交互才 `register`，否则用户先跟助手说话时工具表是空的。
- **注册必须幂等**：`desktop-ready` 可能在 React 重渲染后再次触发，用 `onHostAttach` + 一次性守卫，别重复注册同名方法。
- **契约只写一处**：后端策略指纹 = `tools.json` 按 `sort_keys` + 紧凑分隔符的 sha256。手写第二份 schema 必然漂移，漂移的表现是工具静默失效（后端日志 `Host tool registration rejected`）。
- **工具静默失效的三种典型**：manifest 没声明 `tools`（SDK 抛 denied）、iframe 没加载（工具没注册）、策略/绑定/指纹不一致（网关拒绝）。
- **改前端要 build + 重启桌面应用**：宿主跑的是 `apps/desktop/front/dist`，热更只对 Vite dev 有效。
- **别把 secret 放进页面**：`clientSecret` 只出现在宿主进程与 `~/.desktop-app/agent.json`，渲染层只调 `/api/desktop/agent-token`。
- 跨 `apps/` 改动按 B 档走：先写 `docs/harness/requests/<date>-<topic>/spec.md` 给用户确认，再实现。

## 排障矩阵

| 现象 | 先查 |
| --- | --- |
| 助手说没有工具，后端日志无 `Host tool registration:` | iframe 是否加载（`permissions` 含 `tools`）、`window.desktop.tools` 是否为 denied、注册是否在 `desktop-ready` 之后 |
| 日志里注册了，但消息 `host_tools=[]` | token 的 `host_tools` claim：换 token 时是否传了 `hostToolNames` |
| 工具在列表里但模型从不调用 | `AgentHostTool` / `EmbedClientHostTool` 是否绑定、策略 `is_enabled`、schema 指纹是否一致 |
| 数据没落盘 / `权限不足` | 插件是否声明 `storage`；是否漏了 `await` |
| 设置页没有「配置」入口 / 保存返回 400 | manifest 是否声明 `settings[]`（`type=remote` 不支持）；400 的 `detail` 是中文原因（候选值、min/max、未声明键） |
| 首页没有「概览」区 / 概览卡不显示 | manifest 是否声明 `dashboard`；`publish` 是否在 `desktop-ready` 之后；插件是否已启用；`metrics`/`recent` 是否为空数组 |
| 改了插件目录里的文件没生效 | 开发态需用 `DESKTOP_DEV_RELOAD=1` 启动宿主（默认关闭）；`react` 类型子应用不走热重载，要 `pnpm build` 后重启 |
| 市场里显示「已安装」但没有「更新到 vX」 | 索引条目的 `version` 是否真的大于本机 manifest `version`（`version_greater`：`1.0.0` 等于 `1`、`-beta` 比正式版旧、降级被拒）；本机是内置插件或 `type=remote` 壳插件时本就不参与升级；改完索引记得刷新（条目有 5 分钟缓存，点「刷新」或重启宿主） |
| 插件升级后打不开 / 数据像丢了 | 升级只换程序目录，`plugin-data/<id>` 与 `plugin-config/<id>.json` 仍在；旧版本在 `~/.desktop-app/plugin-backups/<id>/`，可手工拷回 `plugins/<id>` 回滚；`manifest.version` 未递增时升级会被拒绝 |
| 插件市场里没有自己的插件 / 装不上 | 索引 `plugins[]` 是否有该 id；`download` 是否为 https（回环 http / file 只给本机开发）；sha256 是否按打包后的 zip 现算；包内 manifest 的 id/version 是否与索引一致；内置插件已在 `plugins/`，装同名会 409 |
| 从市场安装返回 400 | `detail` 是中文原因（sha256 校验失败 / 大小不一致 / manifest id 不一致 / 索引版本不支持）；400 不会落任何文件；502 是索引或包下载失败，检查网络与 `DESKTOP_PLUGIN_MARKET_URL` |
| `agent-token` 返回 400/502 | 设置页配置是否完整、origin 是否精确匹配 `allowed_origins`、后端是否可达 |
| 改了代码没生效 | 子应用 `build` + 重装 + **重启桌面应用** |

## References

- 完整范例：`apps/ledger/`（`tools.json`、`src/lib/{desktop,store,tools}.ts`、`scripts/install-to-desktop.mjs`）
- 宿主桥：`apps/desktop/front/src/lib/{desktop-sdk,tool-bridge,dashboard-bridge,assistant}.ts`
- 宿主后端：`apps/desktop/desktop_app/{plugin_data,plugin_config,plugin_log,dev_reload,market,agent_config,dev_agent,server}.py`；更新相关 `apps/desktop/desktop_app/{version,transfer,app_update}.py`（版本比较 / 限字节下载与镜像回退 / 宿主自更新清单）
- 市场与打包：`apps/desktop/market/index.json`、`apps/desktop/scripts/plugin_market.py`（CLI 校验）、`apps/desktop/scripts/make_plugin_release.py`（子应用发布：确定性打包 + 更新索引）、`apps/desktop/scripts/make_plugin_zip.py`（旧入口，只打包）、`apps/desktop/scripts/make_release.py`（主应用发布：版本号 → 构建 → zip → `releases/latest.json` → 打 tag → 上传 GitHub/Gitee Release；令牌用 `--set-github-token` / `--set-gitee-token` 存到 `~/.desktop-app/release-tokens.json`，环境变量优先）
- 精确契约与代码骨架：`reference/contracts.md`
- 模型侧配置脚本：`apps/desktop/scripts/configure_ai_base.py`
- 契约文档：`apps/desktop/README.md`（宿主 SDK / plugin-data / 全局助手 / 插件市场与插件升级 / 宿主应用更新 / 发布桌面版本 / 记账子应用）
- 端到端脚本：`tools/harness/verify/2026-10-20-ledger-app.sh`、`tools/harness/verify/2026-10-21-desktop-plugin-dev-reload-dashboard.sh`（首页概览卡 + 插件目录热重载）、`tools/harness/verify/2026-10-21-desktop-plugin-market.sh`（市场索引 + sha256 安装 + CLI）、`tools/harness/verify/2026-10-21-desktop-app-and-plugin-update.sh`（插件升级回滚 + 宿主更新镜像回退 + 发版脚本）
