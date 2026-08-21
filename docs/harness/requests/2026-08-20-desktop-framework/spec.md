# 设计说明：Desktop 基础框架（应用页 / 设置页 + 插件化应用体系）

## 目标

- 在 `apps/desktop/`（pywebview + FastAPI 脚手架）之上搭建桌面应用基础框架：
  - 「应用页面」：以图标网格展示已安装应用，点击后在内容区以 iframe 加载应用页面。
  - 「设置页面」：应用管理（zip 安装、启用/禁用、卸载）与框架信息。
  - 应用以插件形式安装：每个插件是一个目录（`manifest.json` + 静态资源），安装后自动出现在应用页并获得 `/apps/<plugin-id>/` 路由。
  - 框架提供宿主 SDK：插件通过 `window.desktop.*` 调用宿主工具方法（通知、设置存储、事件总线、HTTP 代理、平台信息等），并按 manifest 声明的权限白名单裁剪能力。
- 用户已确认的三个决策：插件页面采用 iframe 沙箱；宿主前端为纯静态 JS + Tailwind CSS（编译产物）；应用安装直接做 zip 导入。
- 关键调研结论（详见 `research.md`）：方案 A（iframe 沙箱 + manifest + 宿主 SDK 中转）、宿主前端 A2（静态 + Tailwind）、安装形态 P2（zip 受控解压，复用 skill-zip-import 安全经验）。

## 范围

### 宿主壳（前端，React 构建产物）

- `front/`：宿主主项目（React 19 + Vite 8 + Tailwind v4），以 Figma 启动器 UI 为样式基线：
  - `src/App.tsx`：应用页（图标网格 / 搜索 / 分类 / 星标固定 / 统计条）、插件 iframe 视图、设置页入口；主题与星标偏好持久化（localStorage）。
  - `src/components/plugin-view.tsx`：iframe `sandbox="allow-scripts allow-same-origin allow-forms"`，load 后注入 SDK 并触发 `desktop-ready`；就绪前透明、就绪后淡入，避免闪白。
  - `src/components/settings.tsx`：应用管理（zip 安装 / 启停 / 卸载）+ 框架信息。
  - `src/lib/api.ts` / `src/lib/desktop-sdk.ts` / `src/lib/toast.ts`：API 契约封装、宿主 SDK 构造器、毛玻璃 toast。
  - 构建产物 `front/dist/` 由内嵌 FastAPI 托管（`/`）；未构建时回退 `static/` 提示页。
- `static/css/tailwind.css`：插件共享样式（`node scripts/build_css.mjs` 产物）。

### Python 侧

- `desktop_app/paths.py`：扩展资源路径解析，新增内置插件目录与用户数据目录（`~/.desktop-app/`）。
- `desktop_app/protocol.py`：插件 manifest 的 pydantic 模型与校验规则。
- `desktop_app/registry.py`：`PluginRegistry`，扫描内置 + 用户插件目录，合并启停状态。
- `desktop_app/security.py`：zip 安全解压（大小 / 条目数 / 路径穿越 / 符号链接防护）。
- `desktop_app/manager.py`：`PluginManager`，zip 安装（临时目录 + 原子 rename）、卸载、启停、状态持久化（`state.json`）。
- `desktop_app/host_api.py`：`HostApi`，pywebview `js_api` 桥（宿主页专用，含权限边界）。
- `desktop_app/server.py`：新增 `/api/desktop/*` 接口、`/apps/` 插件静态挂载，宿主静态资源挂载。
- `desktop_app/main.py`：编排更新，窗口加载宿主壳页面，`js_api` 传入 `HostApi`。

### 插件体系

- 内置示例插件 `plugins/hello-world/`（manifest + icon + 页面，演示宿主 SDK 能力）。
- `scripts/make_plugin_zip.py`：把内置插件打成 zip，用于测试与演示安装流程。
- zip 包结构：zip 根为插件目录（含 `manifest.json`），或根下仅一个包含 `manifest.json` 的目录（自动归一化）。

### 测试

- `tests/test_protocol.py`：manifest 校验（合法 / 非法 id / 缺 entry / 路径穿越 entry）。
- `tests/test_security.py`：zip 安全解压（zip slip、绝对路径、超限、符号链接）。
- `tests/test_manager.py`：安装 / 重复安装 / 卸载 / 启停 / 状态持久化。
- `tests/test_registry.py`：内置 + 用户插件合并扫描、内置优先。
- `tests/test_server.py`：扩展 `/api/desktop/plugins`、`/api/desktop/settings`、`/apps/<id>/` 静态访问。

## 非目标

- 不做插件市场、版本升级、多租户分发。
- 不做插件间深度互操作（仅提供宿主事件总线）。
- 不做系统托盘、多窗口、自动更新等高级桌面能力。
- 不提供通用任意 URL 代理的白名单配置 UI（代理能力记录风险，后续版本再做域名白名单）。
- 插件无需使用宿主 React / Vite 构建链，直接提供静态资源（`manifest.json` + HTML/CSS/JS）即可。
- 不接入 `apps/backend` 或 `apps/front`。

## 页面形式

```text
┌────────┬──────────────────────────────────┐
│ 导航栏  │  内容区                          │
│        │  应用页：图标网格（卡片）           │
│  ▣ 应用 │   或 iframe 沙箱加载插件页        │
│  ⚙ 设置 │  设置页：应用管理 + 框架信息      │
└────────┴──────────────────────────────────┘
```

- 应用页：顶部标题 + 搜索 + 应用网格；卡片含图标、名称、描述、版本标签、星标；点击卡片打开插件 iframe。数据来自 `/api/desktop/plugins`（内置 + 用户安装的已启用插件）。
- 应用视图：iframe 铺满内容区（就绪后淡入），顶部保留原版毛玻璃返回条（返回 + 应用名）。
- 设置页：应用管理分区（安装 zip、启停开关、卸载按钮、内置插件标记）+ 框架分区（插件目录、用户数据目录、版本）。
- 宿主视觉：完全沿用 Figma 启动器 UI（毛玻璃卡片、主题色、侧栏、统计条）；应用数据全部来自插件，原 mock 工具集已移除。

## 架构

```text
┌────────────────────────── pywebview 窗口 ──────────────────────────┐
│ 宿主壳 static/index.html（纯静态 + Tailwind 产物）                  │
│   ├─ hash 路由：#/ 应用页、#/settings 设置页、#/app/<id> iframe     │
│   ├─ host.js：渲染、导航、事件总线、toast、SDK 注入                  │
│   └─ iframe sandbox="allow-scripts allow-same-origin"              │
│        └─ window.desktop（宿主注入 SDK，按 permissions 裁剪）        │
│              └─ fetch /api/desktop/*、/apps/<id>/ 静态资源          │
├─ js_api（window.pywebview.api）：HostApi（宿主页专用能力）            │
└─ 内嵌 FastAPI（uvicorn 后台线程）                                    │
     ├─ /api/desktop/plugins*       插件列表 / 安装 / 启停 / 卸载      │
     ├─ /api/desktop/settings       框架信息                          │
     ├─ /api/desktop/proxy          HTTP 代理（SDK 权限门控）          │
     ├─ /apps/  → 插件静态资源（内置 + 用户目录合并）                   │
     └─ /      → 宿主静态资源                                          │
        └─ PluginRegistry / PluginManager / security / state.json     │
             └─ 内置 plugins/ + 用户 ~/.desktop-app/plugins/           │
└─────────────────────────────────────────────────────────────────────┘
```

## 插件协议（manifest.json）

```json
{
  "id": "hello-world",
  "name": "你好世界",
  "version": "0.1.0",
  "description": "示例应用",
  "icon": "icon.svg",
  "entry": "index.html",
  "permissions": ["notify", "settings", "storage", "events", "http", "platform", "log"]
}
```

校验规则：
- `id` 必须匹配 `^[a-z0-9][a-z0-9_-]*$` 且与插件目录名一致。
- `entry` 与 `icon` 必须是包内相对路径，禁止绝对路径与 `..` 穿越。
- `permissions` 必须是宿主白名单能力，未知能力在安装时警告但允许（向后兼容），未声明则不可用。
- 必填字段缺失或类型错误 → 安装失败并返回可读错误。

## 宿主 SDK（window.desktop）

宿主在 iframe `load` 完成后把 SDK 函数对象注入 `window.desktop` 并触发 `desktop-ready` 事件；插件入口脚本需先等待 `desktop-ready` 事件（若 SDK 已注入则直接可用），再调用各能力。

| 能力 | 权限 | 方法 |
|---|---|---|
| 生命周期 | 默认 | `ready`（Promise）、`appInfo()`、`getApps()`、`navigate(path)` |
| 通知 | `notify` | `notify({title, body})`（宿主 toast） |
| 设置 | `settings` | `settings.get(key, default?)` / `settings.set(key, value)`（按插件 id 命名空间隔离） |
| 存储 | `storage` | `storage.get(key, default?)` / `storage.set(key, value)`（同上，独立命名空间） |
| 事件总线 | `events` | `events.on(event, handler)` / `events.emit(event, payload)`（宿主跨 iframe 转发） |
| HTTP 代理 | `http` | `http.get(url, opts)` / `http.post(url, opts)`（经 `/api/desktop/proxy`） |
| 平台信息 | `platform` | `platform.info()` |
| 日志 | `log` | `log.info/warn/error(...)` |

未声明权限的能力调用返回明确拒绝错误。

## API 契约（内嵌 FastAPI）

- `GET /api/health`：保留。
- `GET /api/desktop/plugins` → `{items: [...]}`（含 `id/name/version/description/icon/entry/permissions/builtin/enabled/iconUrl/entryUrl/error?`）。
- `POST /api/desktop/plugins/install`：请求体为 zip 原始字节流（`Content-Type: application/zip`）→ 200 `{plugin}`；400 校验失败；409 已存在。
- `PATCH /api/desktop/plugins/{plugin_id}`：body `{enabled: bool}` → 200 `{plugin}`。
- `DELETE /api/desktop/plugins/{plugin_id}` → 204；内置插件返回 403。
- `GET /api/desktop/settings` → `{version, pluginsDir, userDataDir}`。
- `POST /api/desktop/proxy`：body `{method, url, headers?, body?}` → 200 代理响应（仅 http/https，宿主 SDK 按权限门控）。
- `GET /apps/{plugin_id}/...`：插件静态资源（`html=True` 目录回退 index.html）。
- `GET /`：宿主壳。

## 数据与状态

- 用户数据目录：`~/.desktop-app/`（跨平台一致），包含：
  - `plugins/<plugin-id>/`：用户 zip 安装的插件。
  - `state.json`：`{"plugins": {"<id>": {"enabled": bool, "installedAt": ISO时间}}}`。
- 内置插件目录：开发模式 `apps/desktop/plugins/`，打包模式 `sys._MEIPASS/plugins/`。
- 同 id 冲突时内置插件优先（标记 `builtin`，禁止卸载；用户同 id 安装返回 409）。
- 宿主设置与插件存储：宿主页 `localStorage`，键前缀 `desktop:settings:<id>:` 与 `desktop:storage:<id>:` 实现按插件隔离。

## 安全设计

- zip 安装限制：总大小 ≤ 20MB、条目 ≤ 200、单文件 ≤ 10MB。
- 拒绝：路径穿越（`..` / 绝对路径 / 反斜杠变体）、空路径、符号链接条目、异常 zip。
- 解压流程：上传到临时文件 → 受控解压到临时目录 → 校验 manifest 与 entry → 原子 rename 到用户插件目录，避免半安装状态。
- iframe 使用 `sandbox="allow-scripts allow-same-origin"`；SDK 由宿主注入，插件不能直接访问 pywebview `window.pywebview.api`。
- 威胁模型：用户主动安装的插件视为可信（同源 iframe 理论上可访问宿主 DOM，宿主页面无敏感数据）。后续升级方向：独立 origin/端口 + postMessage RPC 强隔离。
- HTTP 代理不设域名白名单（本阶段），风险记录于本 spec，后续 request 增加白名单与权限 UI。

## 目录结构（新增/调整）

```text
apps/desktop/
  front/                        # 宿主主项目：React + Vite + Tailwind（Figma 启动器 UI 样式基线）
    src/App.tsx                 # 应用页 / 插件 iframe 视图 / 设置入口（原版样式最小侵入接入）
    src/index.css               # Figma 原版全局样式 + 插件 iframe 淡入
    src/components/plugin-view.tsx  # iframe 沙箱 + SDK 注入 + desktop-ready
    src/components/settings.tsx     # 设置页：zip 安装 / 启停 / 卸载 + 框架信息
    src/lib/api.ts              # /api/desktop/* 契约封装
    src/lib/desktop-sdk.ts      # 宿主 SDK（按 manifest permissions 裁剪）
    src/lib/toast.ts            # 毛玻璃 toast
    dist/                       # 构建产物（内嵌 FastAPI 托管）
  static/css/tailwind.css       # 插件共享样式（build_css.mjs 产物）
  desktop_app/protocol.py       # 新增
  desktop_app/registry.py       # 新增
  desktop_app/security.py       # 新增
  desktop_app/manager.py        # 新增
  desktop_app/host_api.py       # 新增
  desktop_app/paths.py          # 扩展
  desktop_app/server.py         # 扩展
  desktop_app/main.py           # 扩展
  plugins/hello-world/          # 新增：内置示例插件
  scripts/make_plugin_zip.py    # 新增
  scripts/build_css.mjs         # 新增：插件共享样式编译
  tests/test_protocol.py        # 新增
  tests/test_security.py        # 新增
  tests/test_manager.py         # 新增
  tests/test_registry.py        # 新增
  tests/test_server.py          # 扩展
  build/desktop.spec            # 更新：datas 增加 plugins 与 front_dist
```

## 风险

- iframe 同源隔离风险：`allow-same-origin` 下插件可访问宿主 DOM；采用「用户安装即信任」威胁模型，宿主壳无敏感数据，记录为已知限制。
- pywebview 桥风险：插件 iframe 无法直接使用顶层 `window.pywebview.api`，SDK 完全由宿主注入，需在 GUI 验证中实测。
- Tailwind 编译依赖 Node 环境：运行时无依赖，开发/打包前置步骤需执行 `pnpm css`；缺失时页面样式退化但功能可用。
- zip 安全风险：沿用 skill-zip-import 的硬限制与受控解压，测试覆盖恶意样本。
- 状态一致风险：卸载、启停与 registry 扫描需要保持 `state.json` 与目录一致，用单写入口管理。

## 停点判断

- 是否涉及架构边界变化：是（新增桌面插件协议、宿主 SDK 契约、权限模型、zip 安装体系）
- 是否涉及数据模型变化：否（不触碰 `apps/backend` 数据库）
- 是否涉及 API 契约变化：是（新增内嵌 FastAPI 的 `/api/desktop/*` 接口族，但为桌面应用内部契约，不影响现有 backend API）
- 是否涉及鉴权或权限行为变化：是（插件能力白名单，宿主 SDK 权限门控）
- 结论：触发人工确认。用户已在 2026-08-20 对话中确认三项决策：iframe 沙箱、纯静态 Tailwind、zip 导入（见 approvalRecords）。

## 验收标准

- `pnpm css` 可编译 Tailwind 产物；`python -m desktop_app` 启动后显示宿主壳，左侧导航可在应用页/设置页间切换。
- 应用页展示内置 hello-world 插件；点击后 iframe 正常加载插件页，插件可调用 `window.desktop` 各能力（appInfo、notify、settings、storage、events、http、platform、log）。
- 设置页支持 zip 安装（上传内置插件 zip）、启用/禁用、卸载；刷新/重启后状态保持。
- zip 安全测试覆盖路径穿越、超限、符号链接、非法 manifest，均被拒绝。
- `pytest tests/` 全部通过。
- PyInstaller 打包产物可运行且包含插件资源（`build/desktop.spec` 已含 `plugins`）。
- Harness 文档齐全并进入验收。

## 变更记录

### 2026-08-21 第 12 次变更（进入子应用自动全屏 + 全屏沉浸模式）

- 变更原因：用户提出「点击进入子应用自动进入全屏模式，全屏下侧边栏与头部隐藏，保留细毛玻璃把手」
- 变更内容：
  - 点击应用卡片（含 SDK `openApp`）自动进入全屏（`enterFullscreen`）
  - 全屏沉浸模式：头部（返回 / 应用名 / 全屏切换）与侧栏默认隐藏；屏幕顶部保留细毛玻璃横条把手、左侧保留竖条把手（复用侧栏把手），hover / 点击展开
  - 头部展开后提供「收起」与「退出全屏」（返回常规形态）；`Esc` 退出全屏并重置沉浸状态
  - 常规形态保留（退出全屏后可见侧栏 + 悬浮头部），`PageHeader` / `FullscreenToggle` 复用
- 影响章节：页面形式、宿主壳前端
- 是否触发人工确认：否（纯 UI 交互调整）

### 2026-08-21 第 11 次变更（统一页面头部组件 PageHeader）

- 变更原因：用户提出「设置的头部需要和其他页面的头部样式一样，最好用同一个头部组件」
- 变更内容：
  - 新增 `front/src/components/page-header.tsx`：统一毛玻璃圆角头部（左侧返回按钮 / 图标 / 标题 / 副标题，中间内容区，右侧内容区）
  - 应用页顶栏、插件视图返回条（原 `PluginTopBar` 删除，全屏按钮拆为 `FullscreenToggle`）、设置页头部三处统一改用 `PageHeader`
  - 设置页头部移除不透明背景遮罩（`var(--background)`），滚动时与其他页一致呈现悬浮毛玻璃
- 影响章节：宿主壳前端视觉
- 是否触发人工确认：否（纯 UI 重构，行为不变）

### 2026-08-21 第 10 次变更（侧边栏折叠按钮内聚化）

- 变更原因：用户反馈独立悬浮的折叠按钮位置突兀
- 变更内容：
  - 移除侧栏右侧的独立悬浮折叠按钮
  - 折叠按钮并入侧栏底部（avatar 下方，与主题 / 设置图标同款样式与 Tooltip）
  - 侧栏收起后在屏幕左边缘显示极细毛玻璃竖条把手（5px，hover 加宽并自动展开；键盘聚焦点击也可展开）
- 影响章节：宿主壳前端视觉
- 是否触发人工确认：否（纯 UI 交互调整）

### 2026-08-21 第 9 次变更（字体加深 + 毛玻璃更通透）

- 变更原因：用户反馈「字体颜色看不清，毛玻璃背景透明度再透明一点」
- 变更内容：
  - 毛玻璃面板背景透明度整体降低（更通透）：侧栏 0.72→0.5、顶部条 / 返回条 0.75→0.55、统计条 0.65→0.45、空状态 / 设置页内层 0.55→0.4、toast 0.88→0.7，边框同步调淡
  - 浅色文字加深：侧栏未选中图标、返回条分隔符、统计条副文字、空状态与设置页次要文字由 `--color-faint` 提升为 `--color-mid`；返回条按钮文字与插件名加粗（font-600 / font-700）
- 影响章节：宿主壳前端视觉
- 是否触发人工确认：否（纯样式微调）

### 2026-08-21 第 8 次变更（全屏覆盖全部应用视图 + 导航悬浮在插件上方）

- 变更原因：用户提出「全屏覆盖全部应用视图，导航栏变成悬浮在子页面上方」
- 变更内容：
  - 全屏层 iframe 铺满整个窗口（去掉内边距与圆角，真正覆盖全部应用视图）
  - 顶部悬浮返回条（返回 / 应用名 / 退出全屏）与左侧悬浮导航条（复用 `Sidebar`：应用分类 / 设置 / 主题 / 头像）以毛玻璃形式叠加在插件 iframe 上方
  - 全屏时点击分类或「设置」自动退出全屏回到对应页；切换主题、收起/展开侧栏不退出全屏
- 影响章节：页面形式、宿主壳前端
- 是否触发人工确认：否（纯 UI 交互调整，不涉及架构 / API 契约 / 权限模型）

### 2026-08-21 第 7 次变更（插件视图支持常规 / 全屏两种形态）

- 变更原因：用户提出「子应用改成可以全屏展示也可以以当前的形式展示」
- 变更内容：
  - 插件视图顶部返回条新增「全屏 / 退出全屏」切换（沿用原版毛玻璃返回条样式，抽出为 `PluginTopBar`）
  - 全屏形态：`fixed inset-0 z-50` 覆盖层置于根层（`<main>` 有 transform，不能作为 fixed 包含块），iframe 去圆角铺满窗口；Esc 或按钮退出
  - 常规形态：保持原样（侧栏 + 浮动返回条 + 圆角 iframe）；打开 / 返回 / 切换页面时自动复位为常规形态
- 影响章节：页面形式、宿主壳前端
- 是否触发人工确认：否（纯 UI 交互增强，不涉及架构 / API 契约 / 权限模型）

### 2026-08-21 第 6 次变更（开发环境 + 持久化修复）

- 变更原因：用户提出「每次都要 build 吗 / 有没有开发环境 / 怎么打开控制台调试样式」
- 变更内容：
  - `desktop_app/server.py` 新增 `python -m desktop_app.server` 开发入口（默认 `127.0.0.1:8765`，`DESKTOP_API_PORT` 可覆盖）
  - `front/vite.config.ts` 新增 dev proxy：`/api`、`/apps`、`/css` → 本地 FastAPI，浏览器打开 `http://localhost:8443` 即可用 Chrome DevTools 调试，改样式热更新免 build
  - `desktop_app/main.py` 新增 `DESKTOP_DEV_FRONT=1`（窗口加载 Vite dev server，HMR）与 `DESKTOP_DEBUG=1`（启用 Web Inspector，macOS 右键 → 检查元素）
  - 修复持久化 bug：`webview.start(private_mode=False)`；此前 pywebview 默认隐私模式导致 localStorage（主题 / 星标 / 插件设置与存储）重启即丢
- 影响章节：开发运行（README）、验收标准（状态持久化）
- 是否触发人工确认：否（纯开发工具与 bug 修复，不涉及架构 / API 契约 / 权限模型）

### 2026-08-20 第 5 次变更（样式基线恢复 + 最小侵入接入真实插件数据）

- 变更原因：用户明确「样式不要动，用 Figma 设计的样式」，此前接入插件化的宿主页需回归 Figma 原版视觉
- 变更内容：
  - 恢复 Figma 原版 `App.tsx`（1474 行）与 `index.css` 为基线，完整保留主题、侧栏毛玻璃、卡片、搜索、统计条等原版样式
  - 在原版基础上最小侵入接入：应用数据由 mock APPS 改为 `/api/desktop/plugins`（仅展示已启用插件）；卡片图标改为插件 `iconUrl`，卡片强调色由插件 id 稳定派生
  - 打开应用改为插件 iframe（`PluginView`），顶部保留原版返回条；iframe 就绪后淡入以消除闪白
  - 侧栏新增「设置」入口（沿用原版毛玻璃按钮样式），设置页复用 `settings.tsx`
  - 主题偏好与星标固定持久化到 localStorage；星标驱动「快速访问」与统计条数据
  - 删除内置 JsonFormatter 示例工具（此前已确认删除内置工具页示例）
  - 修复宿主 SDK 权限拒绝路径：`denied()` 由抛错函数改为抛错 Proxy，未声明权限时 `settings.get` 等调用给出明确拒绝错误
- 影响章节：范围、页面形式、非目标、目录结构、宿主 SDK
- 是否触发人工确认：否（不涉及架构 / 数据模型 / API 契约 / 权限模型变化；样式恢复与数据源接入均在已确认的 React 宿主闭环内）

### 2026-08-20 第 4 次变更（架构调整：宿主前端迁移到 React）

- 变更原因：用户确认使用 `apps/desktop/front/`（React + Vite + Tailwind 启动器 UI）作为宿主主项目
- 变更内容：
  - 宿主壳前端由纯静态（`static/`）改为 React 工程（`apps/desktop/front`），构建产物 `front/dist` 由内嵌 FastAPI 托管
  - 宿主 SDK 从 `static/js/sdk.js` 迁移为 TypeScript 模块，插件协议（`manifest.json`）与 `/api/desktop/*` 接口保持不变
  - 设置页（应用管理 + 框架信息）在 React 工程内新增；静态宿主壳退役，`static/` 仅保留插件共享 CSS
  - 后端路径解析与打包配置同步调整（`paths.py` 新增 `front_dist_dir()`，`desktop.spec` datas 加入 front 产物）
- 影响章节：页面形式、架构、宿主 SDK、目录结构、API 契约（不变）、测试
- 是否触发人工确认：是（宿主前端架构调整；方向由用户提出，实施细节待确认后进入实现）

### 2026-08-20 第 3 次变更（fix）

- 变更原因：打开子应用时存在闪白过程（iframe 白底 + 插件页样式加载前的 FOUC）
- 变更内容：iframe 改为深色底并在加载完成后淡入；示例插件入口内联设置背景色；README 补充插件防闪白约定
- 影响章节：宿主 SDK、示例插件、README
- 是否触发人工确认：否

### 2026-08-20 第 2 次变更（实现期修正）

- 变更原因：iframe 内联脚本先于宿主注入 SDK 执行，直接访问 `window.desktop` 会得到 undefined
- 变更内容：明确 SDK 就绪契约为「等待 `desktop-ready` 事件」，示例插件按该契约初始化
- 影响章节：宿主 SDK、示例插件
- 是否触发人工确认：否

### 2026-08-20 第 1 次变更（实现期调整）

- 变更原因：避免引入 `python-multipart` 运行时依赖，且前端直接 `fetch(body=file)` 更简洁
- 变更内容：安装接口由 `multipart/form-data` 改为 zip 原始字节流上传；HTTP 代理的 `urlopen` 封装为可注入函数以便测试
- 影响章节：API 契约、测试
- 是否触发人工确认：否（桌面应用内部契约的传输形式调整，业务语义不变）

### 初始版本

- 时间：2026-08-20
- 变更原因：首次创建 request
- 变更内容：建立 Desktop 基础框架的设计说明（宿主壳、插件协议、宿主 SDK、zip 安装、安全与验收标准）
- 影响章节：全部
- 是否触发人工确认：是（架构边界变化；用户在 2026-08-20 确认 iframe 沙箱 / 纯静态 Tailwind / zip 导入三项决策）
