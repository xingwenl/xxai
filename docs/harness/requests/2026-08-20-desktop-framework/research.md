# 业界调研记录：Desktop 基础框架（应用页 / 设置页 + 插件化应用体系）

## 调研问题

- 本次要解决什么问题？
  - 在现有 `apps/desktop`（pywebview + FastAPI 脚手架）之上搭建桌面应用的基础框架：包含「应用页面」与「设置页面」两个一级页面；应用以插件形式安装，安装后自动获得路由；框架为应用提供可复用的工具方法（SDK）。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 影响桌面宿主的前端形态（静态页 vs React 构建）、插件协议（manifest 结构）、插件页面加载方式（iframe 沙箱 vs SPA 路由注册）、宿主 SDK 的能力清单、应用安装与分发形态（本地目录 vs zip 导入）、Python 侧插件管理模块的边界。

## 功能复杂度

- 级别：核心功能（桌面框架是全新架构模块，涉及插件协议、权限与隔离模型）
- 选择理由：新增独立架构边界（桌面插件体系）、引入新的 API 契约（manifest + SDK + 插件静态服务）、涉及权限行为（插件能力白名单）
- 最低调研要求：核心功能，需要比较两到三种方案，并覆盖安全（隔离）、生产实践（成熟编辑器/桌面应用插件模型）

## 参考依据

### 来源 1：VS Code 插件系统（官方文档）

- 类型：官方文档 / 成熟开源项目
- 名称：VS Code Extensibility / Extension System
- 链接：
  - https://vscode-docs.readthedocs.io/en/stable/extensions/our-approach/
  - https://mintlify.wiki/microsoft/vscode/concepts/extension-system
- 版本或发布日期：持续维护（2026 年仍活跃）
- 调研日期：2026-08-20
- 核心做法：
  - 插件通过 manifest（`package.json` 的 `contributes` 字段）声明贡献点：命令、视图、菜单、语言等。
  - extension host 与主进程分离，插件 API 由宿主在运行时注入，插件与宿主通过 RPC 通信。
- 对本项目的启发：
  - 插件元数据声明式（manifest 声明路由入口、图标、权限），宿主在运行时注入 SDK，是最成熟的插件协议形态。
  - 独立运行边界能防止插件拖垮宿主，对应到本项目为「iframe 隔离 + 宿主 SDK 中转」。

### 来源 2：Obsidian 插件 API（官方文档）

- 类型：官方文档 / 成熟开源项目
- 名称：Obsidian API（插件结构）
- 链接：https://raw.githubusercontent.com/obsidianmd/obsidian-api/master/README.md
- 版本或发布日期：持续维护（2026 年仍活跃）
- 调研日期：2026-08-20
- 核心做法：
  - 每个插件是独立目录，包含 `manifest.json`（id、name、author、version、minAppVersion、isDesktopOnly 等）与主入口文件。
  - 插件加载后由宿主调用其生命周期方法（onload/onunload），API 通过模块注入。
- 对本项目的启发：
  - 「目录即插件、manifest 定义元数据」简单可靠，适合作为桌面插件包的物理形态。
  - 宿主定义生命周期（加载/卸载/启停）与 API 注入，插件只面向稳定 SDK 编程。

### 来源 3：pywebview 架构与 js_api（官方文档 + 社区分析）

- 类型：官方文档 / 成熟开源项目
- 名称：pywebview（GUI 库）核心架构与 js_api
- 链接：
  - https://pywebview.flowrl.com/guide/api.html
  - https://deepwiki.com/r0x0r/pywebview/2-core-architecture
- 版本或发布日期：pywebview 3.x（持续维护）
- 调研日期：2026-08-20
- 核心做法：
  - pywebview 是平台 WebView 的三层封装（macOS WKWebView / Windows WebView2 / Linux WebKit2）。
  - `js_api` 把 Python 对象暴露为 `window.pywebview.api.*`，实现 JS ↔ Python 双向调用。
- 对本项目的启发：
  - 宿主 SDK 的「Python 能力」通道直接复用 js_api，但需要按插件白名单做权限校验，不能把全部 Python 方法暴露给任意插件。
  - 静态资源由内嵌 FastAPI 托管，插件页面天然可通过独立 URL 加载，适合 iframe 沙箱。

### 来源 4：Electron 插件系统的隔离实践（社区生产实践）

- 类型：生产实践 / 社区项目
- 名称：CipherTalk 插件系统设计（iframe 按插件绑定 pluginId）
- 链接：https://github.com/ILoveBingLu/CipherTalk/blob/main/PLUGIN_SYSTEM_PLAN.md
- 版本或发布日期：2026-01
- 调研日期：2026-08-20
- 核心做法：
  - 插件以 iframe 加载，按 iframe 来源绑定 pluginId（不可伪造）；sandbox + 跨 origin 使插件拿不到宿主特权，所有能力必须经宿主中转。
- 对本项目的启发：
  - iframe 隔离 + 宿主能力中转是桌面插件体系的安全底线，本项目的 SDK 调用全部走宿主校验，插件 id 由服务端按 URL 路径绑定。

### 来源 5：TanStack Router 路由机制（方案 B 对比依据）

- 类型：官方文档
- 名称：TanStack Router Routing Concepts
- 链接：https://tanstack.com/router/v1/docs/routing/routing-concepts
- 版本或发布日期：v1（2026 年维护中）
- 调研日期：2026-08-20
- 核心做法：
  - 文件路由 + 运行时路由注册，支持动态路由段；路由表由构建插件自动生成。
- 对本项目的启发：
  - 若采用 React SPA 方案，插件可作为前端模块注册进路由表；但要求插件与宿主同技术栈、同构建链，隔离性弱于 iframe。

### 来源 6：仓库内既有模式（Skill Zip 导入 + Desktop 脚手架）

- 类型：仓库内成熟实践
- 名称：
  - `docs/harness/requests/2026-08-04-skill-zip-import/spec.md`（zip 受控解压、包清单、启停、权限开关）
  - `docs/harness/requests/2026-08-20-pywebview-desktop-scaffold/spec.md`（pywebview + FastAPI 脚手架）
- 调研日期：2026-08-20
- 核心做法：
  - zip 导入模式：限制大小/条目数、拒绝路径穿越、解压到受控存储区、包级权限默认关闭。
  - 桌面脚手架：单进程内嵌 uvicorn + FastAPI 静态托管 + js_api 桥。
- 对本项目的启发：
  - 应用 zip 安装可直接复用 skill-zip-import 的解析与安全约束经验。
  - 宿主壳与插件静态托管基于现有 `server.py` 扩展，无需推翻脚手架。

## 方案比较

### 插件页面加载形式

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：宿主 Shell + iframe 沙箱 | 隔离强、插件可用任意技术栈、崩溃不拖垮宿主、天然支持权限模型 | 应用间通信需走宿主 SDK；iframe 内不共享宿主组件库 | 高：与 pywebview + FastAPI 静态托管天然契合，零构建 |
| 方案 B：SPA 路由注册（React + TanStack Router） | 开发体验好、共享宿主组件库 | 插件必须与宿主同栈、需要 Vite 构建链、隔离弱、插件升级需重编译 | 中：需要引入前端工程化，插件生态成本高 |
| 方案 C：混合（manifest 声明 iframe 或路由类型） | 灵活 | 需要同时维护两套加载机制，复杂度高 | 低：起步阶段 YAGNI，不引入 |

### 宿主前端技术

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A1：纯静态 HTML/CSS/JS | 零构建、打包简单、延续现有脚手架 | 壳页面复杂后维护成本上升 | 高：壳仅两个页面 + SDK，够用 |
| A2：纯静态 + Tailwind CSS 编译产物 | 保留零构建运行形态，样式开发效率高 | 需要开发期 CSS 编译步骤 | 高：用户确认采用 Tailwind 技术栈，运行时仍为静态资源 |
| A3：desktop 内建 Vite + React | 组件化、与 front 技术栈一致 | 引入构建链与依赖，打包体积与复杂度上升 | 中：本阶段非必需 |

### 应用安装与分发

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| P1：本地目录扫描（开发期） | 简单直接，插件即目录 | 无版本/市场概念 | 高：本阶段先打通闭环 |
| P2：zip 导入 + 受控解压 | 可分发、可复用 skill-zip-import 经验 | 需要额外安全校验与 UI | 中：放入下一 request |

## 最终决策

- 选择方案：
  - 插件加载形式：方案 A（iframe 沙箱 + manifest 声明 + 宿主 SDK 中转）
  - 宿主前端：A2（纯静态 HTML/CSS/JS + Tailwind CSS，开发期编译 CSS 产物，运行时零构建）
  - 安装形态：P2（zip 导入 + 受控解压，复用 skill-zip-import 的安全约束经验；本地目录扫描作为内置插件来源）
- 选择原因：
  - iframe 沙箱与 pywebview + FastAPI 的「URL 即页面」模型完全一致，插件天然解耦、可任意技术栈，且满足第三方插件安全隔离的基本要求。
  - 宿主壳页面极少（应用页 + 设置页），纯静态 + Tailwind 编译产物符合现有脚手架定位（轻量、单进程、PyInstaller 打包简单），同时保留 Tailwind 的开发效率。
  - 仓库已有 skill-zip-import 的受控解压经验，zip 导入直接复用其大小限制、路径穿越防护与启停权限模型。
- 不选择其他方案的原因：
  - 方案 B（SPA 路由注册）要求插件与宿主同栈同构建链，会把「安装插件」变成「重新编译宿主」，违背插件化的本质。
  - A3（Vite + React）会显著加重 PyInstaller 打包复杂度，宿主壳仅两个页面，本阶段不需要组件化工程。
  - 方案 C（混合）在起步阶段没有实际用例支撑，属于过度设计。
- 对后续 spec、plan 或人工确认的影响：
  - 本任务属于架构边界变化（新增插件协议、SDK 契约、权限模型），按 Harness 规则必须在 spec 定稿后、进入实现前获得人工确认。

## 剩余风险

- 资料时效性：VS Code / Obsidian / pywebview 文档均为长期维护版本，方案以 2026-08-20 检索结果为准。
- 与本项目上下文的差异：参考案例以 Electron/Node 生态为主，本项目为 Python + pywebview，js_api 桥接语义需要实测验证（iframe 内调用 `window.pywebview.api` 的可用性）。
- 尚未验证的假设：
  - iframe 内插件页面无法直接使用 pywebview 顶层 `window.pywebview.api`，SDK 采用宿主注入（同源 iframe 直接注入函数对象）并需实测可用性。
  - 同源 iframe + `allow-same-origin` 下插件理论上可访问宿主 DOM，威胁模型为「用户主动安装的插件视为可信」，隔离强度需在 spec 风险中明示。
  - 插件静态服务按 `apps/<plugin-id>/` 路由挂载后，相对路径资源加载是否始终正确。
  - 插件启停状态持久化到用户数据目录（`~/.desktop-app/state.json`）的跨平台行为需在实现时确认。

## 补充调研：宿主前端改用 React 主项目（2026-08-20）

### 背景

用户提供 `apps/desktop/front/`（Figma Make 生成的 React 19 + Vite 8 + Tailwind v4 项目），其中 `src/App.tsx`
已包含完整应用启动器 UI（主题系统、侧栏分类、应用卡片网格、搜索、置顶、内嵌工具页示例）。
用户希望以此作为桌面宿主「主项目」，替换纯静态宿主壳。

### 参考依据

- 类型：官方文档 / 仓库内成熟案例
- 名称：Vite 构建、Tailwind CSS v4（`@tailwindcss/vite`）、仓库 `apps/front`（React + Vite + Tailwind 生产案例）、`apps/desktop/front`（Figma Make 启动器 UI）
- 链接：
  - https://vitejs.dev/guide/
  - https://tailwindcss.com/docs/installation/using-vite
  - 仓库内 `apps/front/vite.config.ts`、`apps/desktop/front/`
- 版本或发布日期：Vite 8 / Tailwind v4.2（2026 年维护中）
- 调研日期：2026-08-20
- 核心做法：
  - Vite 把 React + Tailwind 源文件构建为 `dist/` 静态产物，可由任意静态服务器托管；`base: '/'` 与内嵌 FastAPI 根路径托管天然匹配。
  - `apps/desktop/front` 已离线验证 `pnpm build` 成功（产出 index.html + assets）。
- 对本项目的启发：
  - 宿主壳改由 React 工程构建，插件协议、SDK 契约与 `/api/desktop/*` 接口保持不变，只替换宿主前端与静态托管路径。

### 方案比较

| 方案 | 优点 | 限制 | 匹配度 |
|---|---|---|---|
| A1：纯静态宿主壳（现状） | 零构建、简单 | 页面形态受限，未复用用户已有的 Figma 启动器 UI | 低（用户已明确弃用） |
| A3：React 宿主主项目（`apps/desktop/front`） | 复用成熟启动器 UI 与主题系统、组件化、构建产物静态托管 | 需要维护 Vite 构建链；PyInstaller 打包需先构建 front | 高（用户指定） |

### 决策

- 采用 A3：`apps/desktop/front` 作为宿主主项目，构建产物 `front/dist` 由内嵌 FastAPI 托管。
- 插件共享样式继续由 `scripts/build_css.mjs` 产出到 `static/css/tailwind.css`（插件协议不变）。
- 静态宿主壳（`static/index.html`、`static/js/host.js`、`static/js/sdk.js`）退役，SDK 逻辑迁移为 TypeScript 模块。
- 人工确认：方向由用户提出（2026-08-20），实施细节（路由方案、vite 插件剥离、静态壳去留）待用户确认后进入实现。
