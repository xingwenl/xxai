# WW 桌面应用（pywebview + FastAPI 脚手架）

基于 **pywebview + FastAPI** 的基础桌面应用脚手架：单进程内嵌 FastAPI 服务，pywebview 窗口加载服务托管的 HTML 页面。可独立打包为桌面应用，与 `apps/backend`、`apps/front` 完全解耦。

## 目录结构

```text
apps/desktop/
  pyproject.toml          # Poetry 工程配置（Python 3.12）
  package.json            # 插件共享样式编译脚本（build_css.mjs）
  front/                  # 宿主前端主项目（React 19 + Vite + Tailwind v4）
    src/App.tsx           # 宿主壳：应用页 / 设置页 / 插件视图
    src/components/       # plugin-view（iframe+SDK 注入）、settings
    src/lib/              # api.ts、desktop-sdk.ts、tool-bridge.ts、assistant.ts、toast.ts
    dist/                 # 构建产物（由内嵌 FastAPI 托管）
  desktop_app/
    app_config.py         # 应用元信息统一配置（名称 / 版本 / Bundle ID / Logo 路径）
    __main__.py           # python -m desktop_app 入口
    main.py               # 窗口与后台服务线程编排
    server.py             # FastAPI 应用工厂（/api/desktop/* + /apps + 前端托管）
    plugin_data.py        # 子应用本地数据存储（plugin-data，JSON 文件原子写）
    dev_agent.py          # 本地 mock 智能体网关（DESKTOP_DEV_AGENT=1 时启用）
    dev_reload.py         # 开发态插件目录指纹（DESKTOP_DEV_RELOAD=1 时启用）
    market.py             # 插件市场：索引解析、下载、sha256 校验、安装与升级
    transfer.py           # 主源 + 镜像回退的下载 / 落盘 / sha256 校验
    app_update.py         # 宿主更新清单解析、平台资产匹配、下载与校验
    version.py            # 版本号比较（0.10.0 > 0.9.0、正式版 > 预发布）
    plugin_config.py      # 插件宿主配置存储（plugin-config，JSON 原子写）
    plugin_log.py         # 插件生命周期事件日志（plugin.log，JSONL）
    agent_config.py       # 真实 AI Base 配置与短期 token 换发
    registry.py           # 插件扫描（内置 + 用户）
    manager.py            # 插件安装/卸载/启停与状态持久化
    protocol.py           # manifest 协议
    security.py           # zip 安全解压
    host_api.py           # pywebview js_api 桥
    paths.py              # 开发/打包双模式资源路径解析
  assets/                 # 品牌资源（icon.png 源图 + 生成的 icns/ico）
  static/css/tailwind.css # 插件共享样式（编译产物）
  plugins/hello-world/    # 内置示例插件
  market/index.json       # 插件市场索引（静态 JSON，随仓库分发）
  market/packages/        # 上架包（示例包，下载地址指向本仓库 raw）
  releases/latest.json    # 宿主更新清单（由 scripts/make_release.py 生成/合并）
  scripts/                # make_plugin_zip.py、plugin_market.py、make_release.py、make_icons.py、build_css.mjs
  build/desktop.spec      # PyInstaller 打包配置（onedir）
  build/build.py          # 跨平台打包脚本
  tests/                  # 服务层与插件体系测试
```

## 应用名称 / Logo / 版本号（统一配置）

应用品牌信息只维护两处，改完重新构建即可全局生效：

1. **名称、版本号、Bundle ID**：编辑 `desktop_app/app_config.py`（`APP_NAME`、`APP_VERSION`、`APP_BUNDLE_ID`）。
   窗口标题、设置页「框架信息」、`/api/health`、前端 SDK、macOS `Info.plist` 与打包产物名都会自动跟随。
2. **Logo**：替换 `assets/icon.png`（建议 1024×1024 透明底 PNG），然后运行：

   ```bash
   cd apps/desktop
   python scripts/make_icons.py   # 重新生成 assets/icon.icns 与 assets/icon.ico
   ```

   macOS 应用图标使用 `icon.icns`，Windows 可执行文件图标使用 `icon.ico`，
   前端侧栏 Logo 直接引用 `assets/icon.png`（经 Vite `publicDir` 输出）。

> 图标兼容性说明：`make_icons.py` 会剥离 PNG 的附加分块（sRGB / eXIf / pHYs），
> 否则部分 macOS 图标渲染路径会把 Dock/应用图标显示成空白。

开发模式（`poetry run python -m desktop_app`）下没有 `.app` 包，macOS 的
Dock/应用图标由 `main.py` 中的 `webview.start(icon=...)` 运行时设置
（读取 `assets/icon.png`）；打包后则由 `.app` 的 `icon.icns` 提供。

## 环境准备

```bash
cd apps/desktop
poetry env use python3.12
poetry install --with dev
pnpm --dir apps/desktop/front install
```

macOS 上 pywebview 会通过 pip 自动安装 pyobjc 系列依赖，首次安装耗时较长属正常现象。

## 开发运行

```bash
cd apps/desktop
pnpm --dir apps/desktop/front build   # 构建宿主前端（首次或前端改动后）
poetry run python -m desktop_app
```

窗口加载宿主前端（`apps/desktop/front` 的构建产物），左侧导航可在应用页/设置页切换，应用页展示已安装插件。
关闭窗口即停止内嵌服务并退出进程。

点击应用卡片会**自动进入全屏**展示：iframe 铺满整个窗口，侧栏默认隐藏。
子应用里**只有全屏这一种形态**，不再有「常规形态（悬浮头部 + 侧栏）」——宿主不会在插件上方
压一条自己的标题栏（插件通常自带头部，叠一条会重复且显得像浮层盖住应用）。
回到应用列表有三条路：

- `Esc` 键（子窗口里为关闭该窗口）
- 左上角的悬浮「返回」胶囊：进入时亮相约 2.8 秒后自动淡出，指针移回该位置会重新出现，
  因此它不会常驻压住插件自己的 logo / 标题
- 鼠标移到屏幕左边缘唤出侧栏，点侧栏的「全部应用」

右上角不再有「退出全屏」按钮，顶部 48×5 毛玻璃把手也已移除。

## 开发模式（改样式不用每次 build）

普通启动加载的是 `front/dist` 构建产物，前端每次改动都要重新 `pnpm build`。
开发时建议用下面的方式获得热更新与浏览器控制台。

### 方式一：浏览器调试（推荐，改样式即时生效）

1. 终端 A 启动 API 服务（固定端口 8765）：

   ```bash
   cd apps/desktop
   poetry run python -m desktop_app.server
   ```

2. 终端 B 启动 Vite dev server（HMR，端口 8443，自动代理 `/api` `/apps` `/css` 到上面的 API）：

   ```bash
   pnpm --dir apps/desktop/front dev
   ```

3. 用 Chrome 打开 `http://localhost:8443`，按 `Cmd+Option+I` 打开 DevTools 调试样式；
   修改 `front/src/` 代码会热更新，不需要 build。

### 方式二：真实窗口内调试（pywebview + Web Inspector）

```bash
cd apps/desktop
pnpm --dir apps/desktop/front dev        # 先启动 Vite dev server
DESKTOP_DEV_FRONT=1 DESKTOP_DEBUG=1 poetry run python -m desktop_app
```

- `DESKTOP_DEV_FRONT=1`：窗口直接加载 Vite dev server，改样式即时生效，不用 build。
- `DESKTOP_DEBUG=1`：启用 Web Inspector（macOS 上窗口右键 → 检查元素，或启动时自动打开检查器）。

### 插件目录热重载（开发态）

改插件的 `manifest.json` / 入口页 / 静态资源时，不必重启宿主、也不必刷新页面：

```bash
cd apps/desktop
DESKTOP_DEV_RELOAD=1 poetry run python -m desktop_app
```

- 默认关闭，打包态零成本：未设 `DESKTOP_DEV_RELOAD` 时 `GET /api/desktop/plugin-revision` 直接返回 `enabled: false`，前端不发轮询。
- 开启后前端每 1.5s 拉一次指纹：后端对每个插件目录算 `sha256(相对路径 + mtime_ns + 大小)` 取前 12 位（跳过隐藏文件、`node_modules` / `.git` / `__pycache__` / `.venv` / `dist`，单插件最多 2000 个文件）。
- 某个插件指纹变了就重拉插件列表并重建它的 iframe（toast「插件已热重载」）；**已打开的子应用与已注册给助手的方法不会丢**。
- `type=react` 的子应用是宿主编译产物，不参与热重载——改完要 `pnpm --dir apps/desktop/front build` 并重启宿主（前端会提示）。
- 新增/删除插件目录也会被发现（指纹变化），但仍建议通过设置页安装 zip 来走完整校验流程。

### 什么时候才需要 build

- 正式启动（不带 `DESKTOP_DEV_FRONT` 的 `poetry run python -m desktop_app`，加载 `front/dist`）。
- 打包前（`poetry run python build/build.py`）。

> 端口可用环境变量覆盖：`DESKTOP_API_PORT`（开发 API 端口，默认 8765，Vite 代理同步读取）；
> Vite dev server 固定 8443。

## 测试

```bash
cd apps/desktop
poetry run pytest tests/
```

## 打包

```bash
cd apps/desktop
pnpm --dir apps/desktop/front build   # 打包前必须构建宿主前端
poetry run python build/build.py
```

产物输出到 `apps/desktop/dist/`（产物名为 `APP_NAME`，默认 `WW`）：

- macOS：`dist/WW.app`（应用包）与 `dist/WW/`（目录产物）
- Windows / Linux：`dist/WW/` 目录产物

运行打包产物（目录产物）：

```bash
./dist/WW/WW
```

## 基础框架：应用页 / 设置页 + 插件化应用体系

宿主壳由 `apps/desktop/front/`（React 19 + Vite + Tailwind v4）构建，提供两个一级页面（左侧导航切换）：

- **应用页**：图标网格展示已安装插件，点击后按插件的默认打开方式打开（默认在内容区 iframe 加载插件页面，也可开在系统浏览器或新的原生窗口）；声明了 `dashboard` 权限的插件可在首页「概览」区推送实时卡片。
- **设置页**：zip 安装插件、启用/禁用、卸载，在弹窗里修改单个插件的宿主配置、查看运行态与事件日志位置，以及框架信息。

插件 = 一个目录（`manifest.json` + 静态资源）。内置插件位于 `plugins/`（随应用分发、不可卸载）；用户通过 zip 安装的插件存放在 `~/.desktop-app/plugins/`，启停状态持久化到 `~/.desktop-app/state.json`。

### 宿主 SDK（插件可用工具方法）

插件页面由宿主（`front/src/lib/desktop-sdk.ts`）注入 `window.desktop`（在 iframe `load` 完成后触发 `desktop-ready` 事件），能力按 `manifest.permissions` 白名单裁剪：

| 能力 | manifest 权限 | 方法 |
|---|---|---|
| 生命周期 | 默认 | `desktop.ready`、`appInfo()`、`getApps()`、`navigate(path)`、`openApp(id)` |
| 通知 | `notify` | `notify({title, body})` 或 `notify(title, body)`（宿主 toast） |
| 设置 | `settings` | `settings.get(key, default?)` / `settings.set(key, value)`（**同步**，存宿主 localStorage）；`settings.getConfig()` / `settings.onChanged(handler)` 读取 manifest 声明的宿主配置（**只读**，见「插件宿主配置」） |
| 存储 | `storage` | `storage.get(key, default?)` / `set(key, value)` / `delete(key)` / `keys()`（**全异步**，落 `~/.desktop-app/plugin-data/<pluginId>/<key>.json`） |
| 概览卡 | `dashboard` | `dashboard.publish(card)` / `dashboard.clear()`（把关键指标推到宿主首页「概览」区，见「首页概览卡」） |
| 方法注册 | `tools` | `tools.register(defs, handlers)` / `tools.unregister(names)`（把子应用能力交给全局助手调用） |
| 事件总线 | `events` | `events.on(event, handler)` / `events.emit(event, payload)`（宿主跨插件转发） |
| HTTP 代理 | `http` | `http.get(url, opts)` / `http.post(url, opts)`（经 `/api/desktop/proxy`） |
| 平台信息 | `platform` | `platform.info()` |
| 日志 | `log` | `log.info/warn/error(...)` |

未声明权限的方法调用会抛出「权限不足」错误。

### 插件宿主配置（settings[]）

插件可以在 `manifest.json` 里用 `settings[]` 声明需要用户配置的项，宿主设置页会自动渲染表单——点该插件的「配置」按钮在弹窗里修改，**不需要写任何设置界面**：

```json
{
  "settings": [
    { "key": "greeting", "label": "问候语", "type": "text", "default": "你好", "description": "显示在首页的问候语" },
    { "key": "refresh", "label": "刷新间隔", "type": "number", "default": 30, "min": 5, "max": 300 },
    { "key": "notify_on_start", "label": "启动时通知", "type": "boolean", "default": false },
    { "key": "accent", "label": "主题色", "type": "select", "default": "sky",
      "options": [{ "label": "天蓝", "value": "sky" }, { "label": "翠绿", "value": "emerald" }] }
  ]
}
```

- 类型只有四种：`text` / `number` / `boolean` / `select`；`select` 必须给非空 `options` 且 `default` 在其候选项内；`min` / `max` 仅 `number` 可用（闭区间）；`text` 单值上限 4096 字符。
- `key` 需匹配 `^[a-z][a-z0-9_-]{0,63}$`，同一插件内唯一；**不允许重命名**——改名相当于丢配置。单个插件最多 32 项，每项 `options` 最多 50 个。
- 配置值落在 `~/.desktop-app/plugin-config/<pluginId>.json`（原子写），保存时按 manifest 校验，非法值整单拒绝并返回中文原因；文件里已废弃的旧键在读取时被忽略。
- 插件侧只读：`desktop.settings.getConfig()` 取 `{key: value}`，`desktop.settings.onChanged(handler)` 订阅变更（返回取消订阅函数）。设置页保存后宿主会广播 `desktop-config-changed`，运行中的应用立即拿到新值，无需重载 iframe。
- `type=remote` 的插件不注入 SDK，因此不允许声明 `settings[]`。
- 配置弹窗用通用 `Dialog` 组件承载（`apps/desktop/front/src/components/dialog.tsx`：遮罩 + 居中卡片 + 标题/说明/底部按钮，支持 Esc 与点遮罩关闭、打开时锁背景滚动、关闭后归还焦点）；表单本身在 `plugin-config-dialog.tsx`。宿主其它页面要做浮层时复用 `Dialog`，不要各写一套 `fixed inset-0` 遮罩。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/desktop/plugins/{plugin_id}/config` | 返回 `{"values": {...}}`：manifest 默认值 + 已保存值合并，未声明的旧键被丢弃 |
| PUT | `/api/desktop/plugins/{plugin_id}/config` | body `{"values": {...}}`，校验失败返回 400（`detail` 为中文原因拼接，且不落盘） |

这两个接口只要求插件存在且 manifest 合法，**不要求插件已启用**（停用期间也能改配置）。

### 运行态与事件日志

- 设置页每个插件会显示运行态：iframe 加载并注入 SDK 成功后为「运行中 · N 个方法」（N 为已注册的助手方法数），注入失败为「运行失败：原因」。
- 宿主把插件生命周期事件写入 `~/.desktop-app/plugin.log`（JSONL，单行一条，超过 1 MiB 轮转为 `plugin.log.1`）：`install_ok` / `install_failed` / `uninstall` / `enable` / `disable` / `iframe_load` / `sdk_injected` / `sdk_inject_failed` / `tools_registered` / `tool_skipped` / `config_saved`。事件名是白名单，未知事件被拒绝。
- 排序排障用：安装失败先看 `install_failed` 的 `error`；插件白屏看 `iframe_load` 后是否有 `sdk_injected`；助手调不到方法看 `tools_registered` / `tool_skipped`。配置保存只记 `keys`（键名），**不记配置值**，避免把隐私写进日志。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/desktop/plugin-log` | body `{"pluginId", "event", "detail"?}`，前端上报插件运行时事件；事件名不在白名单返回 400 |

### 首页概览卡（dashboard）

子应用可以往宿主首页「概览」区推一张卡，把「本月支出」「书签总数」这类关键数字直接露在首页，用户不用先点开应用：

```json
{ "permissions": ["dashboard"] }
```

```js
window.desktop.dashboard.publish({
  title: "记账概览",
  metrics: [
    { label: "本月支出", value: "¥1,280" },
    { label: "记录笔数", value: "36 笔" }
  ],
  recent: [
    { text: "午餐 · 32 元", hint: "今天" },
    { text: "地铁 · 6 元", hint: "昨天" }
  ],
  emptyText: "本月还没有记账"
});
```

- 权限：manifest 必须声明 `dashboard`，否则调用抛「权限不足」。
- 首屏加载：声明 `dashboard` 的子应用会在宿主启动时静默挂载（隐藏 iframe，只加载不展示，和声明 `tools` 的预挂载同一条路径），这样用户一进首页就能看到卡片；代价是这类子应用每次启动都会跑一次，别在启动脚本里做重活。
- 宿主侧截断（不报错）：`title` ≤40、`metrics` ≤4 条（`label` ≤12 / `value` ≤24）、`recent` ≤5 条（`text` ≤80 / `hint` ≤24）、`emptyText` ≤40；超长自动加 `…`。
- 指标与最近条目都为空时展示 `emptyText`；卡片数据是**内存态**，宿主刷新页面或重新挂载 iframe 后由插件重新 `publish`。
- 点击卡片打开对应子应用；插件停用/卸载后首页不再展示它的卡片；没有任何卡片时首页不出现「概览」区。
- 活样板：内置 `plugins/hello-world` 声明了 `dashboard` 并在 `desktop-ready` 后推送一张演示卡。

### 子应用本地数据（plugin-data）

`storage` 背后是宿主提供的持久化接口，按插件隔离、JSON 文件落盘，重启应用/电脑后仍在：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/desktop/plugin-data/{plugin_id}` | 列出该插件已有的 key |
| GET | `/api/desktop/plugin-data/{plugin_id}/{key}` | 读取 JSON 值，缺失返回 404 |
| PUT | `/api/desktop/plugin-data/{plugin_id}/{key}` | 写入任意 JSON（单值上限 256 KiB，临时文件 + 原子替换） |
| DELETE | `/api/desktop/plugin-data/{plugin_id}/{key}` | 删除（幂等，204） |

接口只对已启用且 manifest 声明了 `storage` 的插件开放；`key` 需匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`。数据目录不随插件卸载自动清理，避免误删用户账本等真实数据。

### 全局助手与子应用方法（ai-sdk）

宿主壳层挂着一个全局 AI 助手（`front/src/lib/assistant.ts`，单例、ai-sdk 自带悬浮窗），整个宿主只有一份，**不随子应用打开/关闭重复创建**。子应用通过 `tools.register` 提供方法后，`front/src/lib/tool-bridge.ts` 把方法集合同步给助手；子应用关闭或卸载时自动注销。

- 方法注册时机：声明了 `tools` 权限的子应用会被宿主**启动即静默挂载**（隐藏 iframe，不点开也加载页面），因此助手一启动就能拿到它的方法；用户真正点开时只是把这一层显示出来，不会再新起一份。
- 方法定义：`{ name, description, inputSchema, sideEffect }`，`sideEffect` 取 `none | navigation | write | financial | external`，宿主据此提示风险（记账的新增/删除声明为 `financial`）。
- 助手只负责「调用」：鉴权、会话、工具策略仍由 AI Base 后端裁决（token 的 `host_tools`、Agent / Embed Client 绑定、schema 指纹必须一致）。
- 本地闭环：`DESKTOP_DEV_AGENT=1` 启动宿主时，`desktop_app/dev_agent.py` 会在 `/api/v1/ws/agents/local` 起一个规则式 mock 网关（实现 ai-agent.v1 握手、`host_tools_register`、`host_tool_call`、流式回复），`GET /api/desktop/agent-config` 返回 `{enabled: true, mode: "dev", ...}`，前端据此连本地网关，无需 AI Base 后端即可调试「子应用方法 + 助手」链路。该网关不接真实模型，只做意图关键词匹配与工具调用。

#### 接真实模型（AI Base）

1. 在 AI Base 后台准备 **Embed Client**（记录 `client_id` / `client_secret`）与目标 **Agent**，把桌面页面的来源加入 Client 的 `allowed_origins`：生产 `http://127.0.0.1:8765`、Vite 调试 `http://127.0.0.1:8443`。
2. 把子应用的方法登记成后台 HostToolPolicy（`side_effect` 与子应用声明一致），并同时绑定到该 Agent 与 Embed Client；`input_schema` 必须与子应用注册的完全一致（网关按「JSON 键排序 + 无空格」的 sha256 比对，不一致会静默忽略并记日志 `Host tool registration rejected`）。
3. 宿主设置页 →「智能体后端」填入 AI Base 地址、Client ID、Client Secret、Agent ID、允许的方法名 → 保存 →「测试连接」。secret 仅写入宿主进程的 `~/.desktop-app/agent.json`（0600），渲染层只拿短期 token。
4. 助手连接流程：前端 `POST /api/desktop/agent-token`（带 `window.location.origin`）→ 宿主用保存的凭证调 AI Base `POST /api/v1/embed/tokens`（带 `host_tool_names`）→ 返回短期 token 与 ws 端点 → ai-sdk 连接；token 到期由 SDK 提前 30 秒经同一接口刷新。`GET /api/desktop/agent-config` 返回 `mode: "remote"`，且**不包含** secret。
5. 一次性批量配置（推荐）：`python apps/desktop/scripts/configure_ai_base.py --client-id <id> --agent-id <id> --dry-run` 先看计划，再去掉 `--dry-run` 执行；脚本会把桌面来源并入 `allowed_origins`、按 `apps/ledger/tools.json` upsert 5 条策略并完成两处绑定（需要管理员账号）。
6. 排障：`mode: "remote"` 但助手连不上时看宿主日志中 token 接口的 HTTP 错误；工具调用返回 `host_tool_not_registered` 说明 token 的 `host_tools` 为空（检查 Client 绑定 + `host_tool_names`），`Host tool registration rejected` 说明 schema 指纹不一致。

#### 附件上传与 HTTP 调用（同源转发）

ai-sdk 的 HTTP 接口（附件上传、会话列表、资源下载）由宿主**同源转发**，渲染层不直连 AI Base：

- 渲染层 `baseUrl` 固定为 `${window.location.origin}/api/v1`；宿主新增 `@app.api_route("/api/v1/{path:path}")`（GET/POST/PUT/PATCH/DELETE/HEAD），把请求转发到 `~/.desktop-app/agent.json` 里的 `baseUrl`，透传 `Authorization` / `Content-Type` / `Accept` / `X-Request-Id` 与原始 body，回传上游状态码与响应体。
- 因此**不需要**把桌面来源加进后端 `CORS_ORIGINS`：浏览器只看到同源的 `127.0.0.1:8765`（Vite 调试是 `8443`，走 dev 代理）。
- 未配置智能体后端时转发返回 503；路径里出现 `..` 返回 400；其它网络错误返回 502。
- 文件选择：SDK 的 `accept` 是纯 MIME 列表（`UPLOAD_ACCEPT`）。macOS 系统文件面板只认 MIME（`UTType.typeWithMIMEType_`），`.xlsx` 这类扩展名 token 会被静默丢弃，表现为「只能选图片」。
- MIME 兜底：浏览器对 xlsx / pptx / csv 等常给出空 `file.type`，SDK 用 `resolveFileMimeType` 按扩展名补全后再上传，否则后端以「不支持的文件类型: application/octet-stream」拒绝。


### 插件 manifest 约定

```json
{
  "id": "hello-world",
  "name": "你好世界",
  "version": "0.1.0",
  "description": "示例应用",
  "icon": "icon.svg",
  "entry": "index.html",
  "open_mode": "inline",
  "permissions": ["notify", "settings", "storage", "tools", "events", "http", "platform", "log", "dashboard"]
}
```

- `id` 必须匹配 `^[a-z0-9][a-z0-9_-]*$` 且与插件目录名一致。
- `entry` / `icon` 必须是包内相对路径，禁止绝对路径与 `..`。
- `open_mode`（可选，默认 `inline`）声明点击卡片时的默认打开方式，用户在卡片上右键可对单次点击临时覆盖：
  - `inline`：在宿主壳内容区展开（全屏沉浸），插件 SDK 与权限白名单照旧；
  - `browser`：在系统默认浏览器打开宿主壳页面（深链不带 `?child=1`，因此 Esc / 返回 退回应用列表）。此时没有 `window.pywebview` 宿主桥，插件需自行降级；macOS 走系统 `open` 命令，打不开浏览器时前端会提示「检查默认浏览器设置」而不是静默失败；
  - `window`：打开一个新的原生窗口，窗口里仍是宿主壳（深链 `#/app/<id>`），SDK 与权限白名单不变；同一插件重复打开只会聚焦已有窗口。
  - `type=remote` 的插件在 `browser` / `window` 下打开它自己的 `url`，且**不会**注入宿主桥；写错的 `open_mode` 会回退为 `inline`（仅记录警告，不影响插件加载）。
- `settings`（可选）：声明式宿主配置项，见上文「插件宿主配置（settings[]）」；`type=remote` 的插件不允许声明。
- `permissions` 支持：`notify` / `settings` / `storage` / `tools` / `events` / `http` / `platform` / `log` / `dashboard`；未声明的能力被调用时抛「权限不足」。
- zip 包结构：根为插件目录，或根下仅一个含 `manifest.json` 的目录（自动归一化）。

### 插件市场（market/index.json + sha256）

设置页的「插件市场」区块让用户不用管 zip：选一个插件点「安装」，宿主下载、校验、落盘一条龙。索引是一份静态 JSON，默认托管在本仓库：

```text
https://raw.githubusercontent.com/xingwenl/xxai/main/apps/desktop/market/index.json
```

- `DESKTOP_PLUGIN_MARKET_URL`：覆盖索引地址（https，本机开发也接受 `127.0.0.1` 的 http 与 `file://`，便于离线与 CI）。
- `DESKTOP_PLUGIN_MARKET=0`（或 `false` / `no` / `off`）：整体关闭市场，设置页显示「市场已关闭」。
- 索引 300 秒内存缓存，设置页「刷新」会带 `refresh=1` 强制重取。

索引格式：

```json
{
  "version": 1,
  "plugins": [
    {
      "id": "hello-world",
      "name": "你好世界",
      "version": "0.1.0",
      "description": "示例应用",
      "download": "https://example.com/hello-world-0.1.0.zip",
      "sha256": "64 位十六进制",
      "size": 4104,
      "permissions": ["notify", "settings"],
      "mirrors": ["https://gitee.com/xingwenl/xxai/raw/main/apps/desktop/market/packages/hello-world-0.1.0.zip"]
    }
  ]
}
```

- `version` 目前只能是 `1`；`plugins` 最多 200 条，`id` 不可重复且须匹配插件 id 规则。
- `download` 只接受 https（回环 http / file 仅用于开发）；`sha256` 必填且为 64 位小写十六进制。
- `size`（可选）出现时宿主会额外校验包体字节数；`permissions`（可选）只用于展示与未知权限告警，真正的权限仍以包内 `manifest.json` 为准。
- `mirrors`（可选）：下载主地址不可达时的备用地址数组（同一份包、同一 sha256）。索引本身也可用 `DESKTOP_PLUGIN_MARKET_MIRRORS` 配逗号分隔的镜像，主源失败自动回退。

安装链路（`POST /api/desktop/plugin-market/install`，请求体 `{"id": "..."}`）：

1. 从索引取条目；2. 下载包（>20 MiB 拒绝）；3. 有 `size` 就校大小；4. 校 `sha256`；5. 读包内 `manifest.json` 并校 `id` / `version` 与索引一致；6. 交给既有安装流程（安全解压 + 目录归一化 + 冲突检测 + 原子落盘 + 事件日志）。

错误语义：索引/包内容不合法或校验失败 → 400（`detail` 是中文原因）；下载或取索引失败 → 502；索引里没有该 id → 404；同名插件已安装 → 409。**校验失败不会落任何文件。**

上架 / 发布子应用（一条命令：确定性打包 + 更新索引 + 打印提交推送命令）：

```bash
cd apps/desktop

# 新版本：manifest.json 里先改好 version，然后（默认 hello-world，可传任意插件 id 或目录）
.venv/bin/python scripts/make_plugin_release.py hello-world
# 也可以让脚本代改版本再发布（--version 可指定版本，仅往下调时需 --force）：
.venv/bin/python scripts/make_plugin_release.py hello-world --bump patch
.venv/bin/python scripts/make_plugin_release.py hello-world --version 0.3.0 --git

# 只校验包与索引是否自洽（CI 用，不出包、不写文件）
.venv/bin/python scripts/make_plugin_release.py hello-world --check-only
```

脚本做的事（`apps/desktop/scripts/make_plugin_release.py`）：

1. 校验 `manifest.json`：id 规则、目录名必须等于 id、`name`/`version`/`entry`/`icon` 文件存在、`permissions` 是字符串数组。
2. 打包到 `market/packages/<id>-<version>.zip`，包内顶层是 `<id>/`；固定时间戳与权限位，**同样的内容重复打包 sha256 完全一致**（不会因每次发版时间不同而变 hash）；跳过 `.DS_Store`、`__pycache__`、`node_modules`、`*.pyc`。
3. 更新 `market/index.json`：`download` 指向本仓库 raw 地址，`mirrors` 指向 Gitee 同路径（主源失败宿主自动回退）；同 id 条目就地替换，不动其他插件与顺序。
4. 打印 sha256 / size / permissions、要做的事和提交推送命令。

护栏：索引里版本比本地高时拒绝发布（市场只提示升级、不会降级，确要回退加 `--force`）；同版本但包内容变了也拒绝（避免缓存过索引的用户装到不一致的内容，加 `--force` 覆盖）；任一护栏触发都不会把 `manifest.json` 改脏。

`--git` 会顺便提交 `manifest.json` / zip / `market/index.json`（只提交不推送）；`--no-index --out-dir dist` 只打包不上架（旧的 `make_plugin_zip.py` 现在等价于这个用法，保留兼容）。

也可以用 CLI 生成/校验条目（与宿主共用 `desktop_app/market.py`，校验口径完全一致）：

```bash
.venv/bin/python scripts/plugin_market.py list                 # 列出索引（--json / --refresh）
.venv/bin/python scripts/plugin_market.py install hello-world  # 按 id 安装（等价于界面点「安装」）
.venv/bin/python scripts/plugin_market.py entry dist/x.zip --download https://example.com/x.zip
.venv/bin/python scripts/plugin_market.py verify dist/x.zip --sha256 <64 位十六进制>
```

> 内置插件随宿主分发（`plugins/`，不可卸载），因此从市场安装同名插件会返回 409；示例索引里的 `hello-world` 条目主要用于演示格式。

### 插件升级（保留旧版本、失败回滚）

市场不只用于首次安装：当索引版本高于本机版本时，条目右侧按钮变成「更新到 vX」，点一下即可原地升级。`GET /api/desktop/plugin-market` 的每条插件除了索引字段，还附带 `installedVersion`（本机已装版本，未装为空串）与 `hasUpdate`（布尔），前端不再自己比版本。

升级链路（`POST /api/desktop/plugin-market/update`，请求体 `{"id": "..."}`）：

1. 下载包并校 `size` / `sha256`，读包内 `manifest.json` 校 `id` / `version` 与索引一致（与安装完全同一套校验）；
2. 旧目录**改名备份**到 `~/.desktop-app/plugin-backups/<id>/<version>-<时间戳>/`，每个插件只保留最近 3 份；
3. 新包先解到 `plugins/.<id>.upgrading`，再同盘 `rename` 覆盖 `plugins/<id>`（原子替换，不会出现半个插件）；
4. 任一步失败：删掉临时目录，把备份改回 `plugins/<id>`，返回 400 说明原因——**本机仍是旧版本，可正常使用**；
5. 成功：`state.json` 保留原 `enabled` 与 `installedAt`，追加 `updatedAt` 与 `previousVersion`；事件日志记 `update_ok` / `update_failed`。

数据不迁移：`plugin-data/<id>/` 与 `plugin-config/<id>.json` 按插件 id 存放，升级不触碰，所以账本、配置、登录态都在。想回滚就把备份目录拷回 `plugins/<id>`（备份目录不参与插件扫描，不会重复出现）。

错误语义：内置插件 / `type=remote` 壳插件 / 新版本不高于已装版本 / 校验失败 → 400；插件未装或索引里没有该 id → 404；下载失败 → 502。

升级对「来源」没有要求：手动 zip 装过的插件，只要市场索引里有同 id 且版本更高，也能直接升级。

### 宿主应用更新（只检查 / 下载 / 校验，安装由用户手动完成）

设置页「应用更新」区块可以检查宿主自身的新版本，但**不会自动替换自己**：下载并校验通过后，由用户退出应用手动覆盖安装。这样避开三件难做对的事——macOS 未签名包被 Gatekeeper 拦、Windows 下替换运行中的 exe、升级中途崩溃留下半个应用。

- `DESKTOP_APP_UPDATE_URL`：覆盖清单地址（https，本机开发接受 `127.0.0.1` 的 http 与 `file://`）。
- `DESKTOP_APP_UPDATE_MIRRORS`：逗号分隔的镜像地址，主源失败自动回退；默认已内置 Gitee raw 镜像，GitHub 不可达时仍能检查更新。
- `DESKTOP_APP_UPDATE=0`（或 `false` / `no` / `off`）：关闭应用更新检查，设置页显示「已关闭」，前端不发请求。
- 清单 600 秒内存缓存；点「检查更新」带 `refresh=1` 强制重取。

清单 `apps/desktop/releases/latest.json`：

```json
{
  "version": 1,
  "latest": "0.2.1",
  "publishedAt": "2026-10-21T08:00:00Z",
  "notes": "修复插件升级后的窗口残留",
  "releaseUrl": "https://github.com/xingwenl/xxai/releases/tag/desktop-v0.2.1",
  "platforms": {
    "macos-arm64": {
      "name": "WW-0.2.1-macos-arm64.zip",
      "url": "https://github.com/xingwenl/xxai/releases/download/desktop-v0.2.1/WW-0.2.1-macos-arm64.zip",
      "mirrors": ["https://gitee.com/xingwenl/xxai/releases/download/desktop-v0.2.1/WW-0.2.1-macos-arm64.zip"],
      "sha256": "64 位十六进制",
      "size": 123456789
    }
  }
}
```

- `version` 目前只能是 `1`；`platforms` 的键固定为 `macos-arm64` / `macos-x64` / `windows-x64` / `linux-arm64` / `linux-x64`，未知平台键忽略。
- **当前平台匹配不到就不更新**（设置页显示「当前平台不在发布清单支持范围」），绝不回退到别的架构——装错架构的包能替换成功但启动即崩，比不更新更糟。
- 资产 `name` 必须是纯文件名（不允许带路径）；只接受 https（本机开发同市场规则）。

端点：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/desktop/app-update` | 检查更新，`?refresh=1` 跳过缓存；永远 200，失败原因在 `error` 字段（不把「检查失败」伪装成「已是最新」） |
| POST | `/api/desktop/app-update/download` | 下载当前平台资产并校 `size` / `sha256`，落 `~/.desktop-app/updates/<version>/<文件名>`；校验失败 400 并删掉残缺文件 |
| POST | `/api/desktop/app-update/reveal` | 在文件管理器里打开更新目录（只打开固定目录，不接受外部路径） |

### 发布桌面版本（GitHub + Gitee）

版本号有三处，必须先统一，`make_release.py --check-only` 会拦住漂移：`desktop_app/app_config.py` 的 `APP_VERSION`、`pyproject.toml` 的 `[project] version`、`front/package.json` 的 `version`。

```bash
cd apps/desktop

# 一条命令走完：递增版本 → 构建前端与产物 → 打平台 zip → 写 releases/latest.json → 提交并打 tag
.venv/bin/python scripts/make_release.py --bump patch --build --git --notes "本次更新了什么"

# 首次使用：把令牌保存到本机（交互输入、不回显），之后不用再 export
.venv/bin/python scripts/make_release.py --set-github-token
.venv/bin/python scripts/make_release.py --set-gitee-token

# 自动上传 Release（自动读取上面保存的令牌，见下）
.venv/bin/python scripts/make_release.py --publish all --notes "本次更新了什么"

# 只预演、不落任何文件；只校验版本号与清单是否自洽（CI 用）
.venv/bin/python scripts/make_release.py --bump minor --build --git --publish all --dry-run
.venv/bin/python scripts/make_release.py --check-only
```

常用参数：`--bump major|minor|patch` 或 `--set-version X.Y.Z` 改三处版本号；`--build` 跑 `pnpm --dir front build` + `python build/build.py`；`--asset <zip>` 直接登记已有产物不重新打包；`--git` 提交 4 个文件并打本地 tag `desktop-v<version>`（**只打 tag 不推送**）；`--publish github|gitee|all` 上传 Release；`--platform` / `--github-repo` / `--gitee-repo` / `--branch` 覆盖默认值。

令牌：GitHub 用 `GITHUB_TOKEN`（或 `GH_TOKEN`，需 `repo` 权限），Gitee 用 `GITEE_TOKEN`（私人令牌，需 `projects` 权限）。查找顺序是「环境变量 → 本地令牌文件」：`--set-github-token` / `--set-gitee-token` 把令牌保存到 `~/.desktop-app/release-tokens.json`（权限 `600`，在仓库之外，不会被提交），不带参数运行时交互输入不回显；也可 `--set-github-token ghp_xxx` 直接传值（会进 shell 历史，不推荐）；`--token-status` 查看配置情况（只显示首尾几位），`--clear-tokens` 清除。CI 里继续用环境变量即可，优先级更高、可临时覆盖。上传逻辑可重复执行：同名资产会先删后传，已存在的 Release 会复用而不是报错。

脚本会把清单里的 `url` 写成 GitHub Release 下载地址、`mirrors` 写成 Gitee 同 tag 地址；多平台发版时在每个平台各跑一次（默认只更新当前平台的条目，`--reset` 可清掉其他平台的旧条目）。推送 `main` 后宿主即可检查到新版本（raw 地址指向 main）。

> 宿主侧只做「检查 → 下载 → 校验 sha256 → 引导手动安装」，不会自动替换自己；发布令牌只存在于发版机器上，绝不写进客户端。

### 开发一个插件

1. 在 `plugins/<id>/` 创建 `manifest.json` 与入口页面。
2. 入口脚本等待 SDK 注入：

```html
<script>
  (async () => {
    await new Promise((resolve) => {
      if (window.desktop) return resolve();
      window.addEventListener("desktop-ready", () => resolve(), { once: true });
    });
    const d = window.desktop;
    await d.notify({ title: "你好", body: "宿主通知" });
  })();
</script>
```

3. 启动应用后在设置页上传打包的 zip、从「插件市场」安装，或直接放入用户插件目录。
4. 需要用户可调参数时，在 `manifest.json` 声明 `settings[]`，插件页用 `desktop.settings.getConfig()` 读取、`onChanged` 订阅变更（示例见内置 `plugins/hello-world`）。
5. 想在首页露数字时，声明 `dashboard` 权限并在 `desktop-ready` 后调 `dashboard.publish(...)`（同样见 `hello-world`；它把通知、存储、方法注册、宿主配置、概览卡五件事演示在一起）。

> 提示：插件入口页建议在 `<head>` 中内联设置背景色（如 `background: #020617`），
> 避免在宿主样式文件加载完成前出现白屏闪动；宿主会在插件页加载完成后淡入显示。

### 样式

- 宿主壳样式：由 `front` 的 Vite + Tailwind v4 构建，改 `front/src/` 后执行 `pnpm --dir apps/desktop/front build`。
- 插件页共享样式：`static/css/tailwind.css`（编译产物，运行时零依赖），修改后重新编译：

```bash
cd apps/desktop
node scripts/build_css.mjs       # 一次性编译（离线）
node scripts/build_css.mjs --watch
```

`src/input.css` 是插件共享样式源文件；候选类名自动从 `static/`、`plugins/`、`src/` 中扫描。

### 自定义页面与接口

- 宿主壳界面代码在 `apps/desktop/front/src/`（App.tsx、components/、lib/），构建产物由内嵌 FastAPI 托管在 `/`。
- 在 `desktop_app/server.py` 的 `create_app()` 中新增 `/api/desktop/*` 路由即可扩展宿主能力。
- `desktop_app/host_api.py` 的 `HostApi` 暴露 pywebview `js_api` 能力（仅宿主壳页面可调用；插件一律走宿主 SDK）。
- `static/` 仅保留插件共享 CSS 与「前端未构建」回退页。

## 记账子应用（apps/ledger）

`apps/ledger` 是第一个按「子应用只提供页面 + 方法、宿主提供数据能力」模式落地的独立子应用：React 19 + Vite 的纯网页，构建后以 `dist/` 作为 iframe 插件安装进宿主，自身不跑服务、不连数据库。

- 数据：走宿主 `storage` → `~/.desktop-app/plugin-data/ledger/ledger.json`；脱离宿主直接打开时回退 `localStorage['ledger:data']`。
- 方法：注册 `ledger_add_entry`、`ledger_list_entries`、`ledger_month_summary`、`ledger_delete_entry`、`ledger_list_categories` 五个 `ledger_*` 方法，交给全局助手调用（新增/删除标记为 `financial`）。
- 该插件声明了 `tools` 权限，宿主启动时会静默预挂载它：**不点开「记账」也能让助手记账**（页面已在后台加载并注册方法）；点开只是把这一层显示出来。

```bash
pnpm install                              # 根目录安装一次
pnpm --dir apps/ledger build              # 产物在 apps/ledger/dist
cd apps/ledger && node scripts/install-to-desktop.mjs   # 装到 ~/.desktop-app/plugins/ledger
# 重启桌面应用，在应用页打开「记账」；用 DESKTOP_DEV_AGENT=1 启动可让助手直接记账
```

本地开发：`pnpm --dir apps/ledger dev`（http://127.0.0.1:5181，无宿主时自动用 localStorage）。详见 `apps/ledger/README.md`。

## 常见问题

- **启动后显示「宿主前端未构建」**：先执行 `pnpm --dir apps/desktop/front build` 生成 `front/dist`。
- **打包后页面 404**：确认 `build/desktop.spec` 的 `datas` 包含 `(front/dist, "front_dist")`、`(static, "static")` 与 `(plugins, "plugins")`，且 `paths.py` 在打包模式下指向 `sys._MEIPASS` 对应目录。
- **插件页报「权限不足」**：检查插件 `manifest.json` 的 `permissions` 是否声明了对应能力（notify/settings/storage/tools/events/http/platform/log）。
- **助手悬浮球不出现 / 子应用方法助手看不到**：先确认宿主能从 `GET /api/desktop/agent-config` 拿到 `enabled: true`（本地调试用 `DESKTOP_DEV_AGENT=1` 启动）；再确认子应用 manifest 声明了 `tools`（宿主启动时会静默预挂载这类子应用，无需点开）；若刚改过前端，需要重启桌面应用让新的 `front/dist` 生效。
- **插件页拿不到 `window.desktop`**：插件必须在 `desktop-ready` 事件后再使用 SDK，参考上文示例写法。
- **设置页没有「配置」按钮 / 保存配置报 400**：按钮只在插件声明了 `settings[]` 且 manifest 无错时出现，点击后在弹窗里改；400 会显示在弹窗底部且 `detail` 是中文原因（例如取值不在候选项、超出 min/max、键未声明），修正后重试即可，非法提交不会落盘、弹窗保持打开。
- **改了插件文件没反应**：确认宿主是以 `DESKTOP_DEV_RELOAD=1` 启动的（默认关闭）；仍在跑旧内容时看 `~/.desktop-app/plugin.log` 里有没有新的 `iframe_load`，并确认改的是插件目录内的文件（隐藏目录与 `node_modules` / `dist` 不参与指纹）；`type=react` 的子应用不参与热重载，需 `pnpm build` 后重启宿主。
- **首页没有「概览」区 / 概览卡不显示**：确认 manifest 声明了 `dashboard` 权限、`publish` 写在 `desktop-ready` 之后；卡片数据是内存态，插件重新挂载后要重新 `publish`；插件停用/卸载后卡片不再展示；`metrics` / `recent` 里空的条目会被丢弃，全空时只显示 `emptyText`。
- **改完配置运行中的应用没反应**：插件页必须用 `desktop.settings.getConfig()` 读取、`desktop.settings.onChanged()` 订阅；旧的 `settings.get/set` 存在宿主 localStorage，与宿主配置是两套数据。
- **插件白屏或显示「运行失败」**：看 `~/.desktop-app/plugin.log`（JSONL）：有 `iframe_load` 但无 `sdk_injected` 说明入口页没等到 SDK 或脚本报错，`sdk_inject_failed` 的 `detail` 带具体原因。
- **插件市场报错 / 安装失败**：400 说明索引或包内容不合法（`detail` 是中文原因，例如 sha256 校验失败、包内 manifest id 与索引不一致、超过 20 MiB），此时不会落任何文件；502 说明索引或包下载失败（检查网络与 `DESKTOP_PLUGIN_MARKET_URL`）；409 说明同名插件已安装。设置页「刷新」可跳过 5 分钟索引缓存。
- **开发时怎么打开控制台**：浏览器模式直接按 `Cmd+Option+I`；pywebview 窗口用 `DESKTOP_DEBUG=1` 启动后右键 → 检查元素。
- **主题 / 星标重启后丢失**：确认以本仓库代码启动（已关闭 pywebview 隐私模式）；旧版本安装的应用不受影响。
- **窗口无法启动**：pywebview 依赖系统 WebView，macOS 需 macOS 10.13+，Linux 需安装 GTK 与 WebKit2 相关库。
