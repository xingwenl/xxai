# 业界调研记录

## 调研问题

- 本次要解决什么问题？
  - 在 `apps/desktop/` 下搭建一个基于 pywebview + FastAPI 的基础桌面应用脚手架，要求：可独立打包为桌面应用、内置 FastAPI 服务、直接加载 HTML 页面，且与现有 `apps/backend`、`apps/front` 完全解耦。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 影响桌面应用的技术选型（pywebview 加载方式、内嵌服务运行形态）、资源路径在开发/打包环境的兼容策略、打包工具与打包参数，以及脚手架的目录结构。

## 功能复杂度

- 级别：普通业务功能（脚手架搭建，不涉及现有业务数据与接口）
- 选择理由：本任务创建全新独立子项目，无存量代码迁移，但涉及跨平台打包与内嵌服务集成，存在一定的平台与环境风险。
- 最低调研要求：确认 pywebview 加载 HTTP 页面与暴露 Python API 的官方用法、官方冻结（打包）指南、FastAPI 静态资源托管方式、PyInstaller 运行期资源定位，以及 uvicorn 后台线程运行方式。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：pywebview API 文档（create_window / js_api / webview.start）
- 链接：https://pywebview.flowrl.com/3.7/guide/api.html
- 版本或发布日期：pywebview 3.7+（本文档写作时最新稳定为 6.2.1，2026-04-15 发布）
- 调研日期：2026-08-20
- 核心做法：`webview.create_window(title, url=...)` 可加载 HTTP 地址；`js_api` 可将 Python 对象暴露给 JS，JS 侧通过 `window.pywebview.api.<method>()` 调用并返回 Promise（方法名不能以下划线开头）；`webview.start()` 必须在主线程调用；`window.events.closed` 提供窗口关闭回调。
- 对本项目的启发：窗口直接加载 `http://127.0.0.1:<动态端口>`，由内嵌 FastAPI 提供页面与接口；提供 `js_api` 示例演示 Python 与前端互调能力。

### 来源 2

- 类型：官方文档
- 名称：pywebview Freezing Your Application 指南
- 链接：https://pywebview.flowrl.com/guide/freezing.html
- 版本或发布日期：随 pywebview 官方文档维护
- 调研日期：2026-08-20
- 核心做法：Windows/Linux 打包用 PyInstaller 并将静态资源通过 `--add-data index.html:.` 打入产物；pywebview 内置 `webview/__pyinstaller/hook-webview.py`，PyInstaller 可自动收集其依赖。
- 对本项目的启发：采用 PyInstaller onedir 模式 + spec 文件中的 `datas` 参数收集 `static/` 资源，并依赖官方 hook 自动处理 pywebview 隐藏依赖。

### 来源 3

- 类型：官方文档
- 名称：FastAPI Static Files 教程
- 链接：https://fastapi.tiangolo.com/tutorial/static-files/
- 版本或发布日期：FastAPI 0.139.x（backend 已使用的版本区间）
- 调研日期：2026-08-20
- 核心做法：`app.mount("/", StaticFiles(directory=..., html=True))` 可托管前端静态文件并自动返回 `index.html`；新版 FastAPI 也提供 `app.frontend()` 作为前端托管方式。
- 对本项目的启发：脚手架用 `StaticFiles(html=True)` 托管 `static/` 目录即可满足「加载 HTML 页面」需求，同时保留 `/api/health` 健康检查接口。

### 来源 4

- 类型：官方文档
- 名称：PyInstaller Runtime Information
- 链接：https://pyinstaller.org/en/stable/runtime-information.html
- 版本或发布日期：PyInstaller 6.21.0（2026-06-13 发布）
- 调研日期：2026-08-20
- 核心做法：通过 `getattr(sys, "frozen", False)` 判断是否打包运行，打包后资源根目录位于 `sys._MEIPASS`。
- 对本项目的启发：`paths.py` 统一封装资源路径解析：开发模式定位到 `static/` 源目录，打包模式定位到 `sys._MEIPASS/static`。

### 来源 5

- 类型：生产实践 / 社区实践
- 名称：uvicorn 在后台线程中运行
- 链接：https://stackoverflow.com/questions/61577643/how-to-run-fastapi-application-inside-another-thread
- 版本或发布日期：社区讨论，长期维护
- 调研日期：2026-08-20
- 核心做法：`uvicorn.run()` 是阻塞调用，需放入 `threading.Thread(daemon=True)`；部分平台对主线程有特殊检查，需选择兼容的 loop 实现。
- 对本项目的启发：pywebview 主线程独占窗口事件循环，内嵌 uvicorn 必须运行在后台守护线程；窗口 `closed` 事件触发后停止服务并退出。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：加载脚手架自带最小静态页（`static/index.html`） | 与现有 front 完全解耦、零构建依赖、打包简单、开箱即用 | 页面能力有限，需要复杂 UI 时得自行替换或另做对接 | 高，符合「和现有 backend/front 没有关系」的明确要求 |
| 方案 B：对接现有 `apps/front` 构建产物 | 可直接复用现有界面 | 引入前端构建链与目录耦合，违反解耦要求，打包复杂度上升 | 低，用户已明确排除 |
| 方案 C：完整打包（PyInstaller onedir）+ 资源路径兼容 | 产出独立可分发应用、开发/打包双模式路径统一 | 需要处理平台差异（macOS 需 pyobjc、Windows 需 pywin32） | 高，符合「能打包」的核心验收点 |
| 方案 D：仅开发运行不打包 | 实现最快 | 不满足「能打包」需求 | 不采用 |
| 集成形态 A'：pywebview 直接加载内嵌 FastAPI 的 HTTP 页面 | 单进程、无需外部服务、窗口关闭即退出、前后端互通自然 | 需在后台线程运行 uvicorn，注意线程安全 | 高，最简洁可靠 |
| 集成形态 B'：加载本地 HTML 文件 + API 走代理 | 无需内嵌服务 | 本地文件与 API 跨源处理繁琐，与「内置 FastAPI 服务」要求冲突 | 不采用 |

## 最终决策

- 选择方案：方案 A（自带静态页）+ 方案 C（PyInstaller onedir 完整打包 + 开发/打包资源路径兼容）+ 集成形态 A'（单进程内嵌 uvicorn + FastAPI）
- 选择原因：完全满足「能打包、内置 FastAPI 服务、加载 HTML 即可、与现有 backend/front 无关」的验收要求；单进程内嵌服务架构简单，窗口生命周期与服务生命周期一致，便于打包分发。
- 不选择其他方案的原因：方案 B 与用户明确提出的解耦要求冲突；集成形态 B' 无法体现「内置 FastAPI 服务」这一核心要求。
- 对后续 spec、plan 或人工确认的影响：本任务属于新增独立子项目（架构边界变化），按 Harness 策略需在进入实现前获得人工确认；用户已在对话中口头确认「可以」，将以 meta.json 审批记录存档。

## 剩余风险

- 资料时效性：pywebview 6.2.1 为 2026-04 发布版本，API 与官方文档示例基本一致，但打包 hook 行为可能随版本演进变化。
- 与本项目上下文的差异：本仓库 backend 使用 FastAPI 0.139.x；desktop 脚手架将采用独立依赖版本，与 backend 互不影响。
- 尚未验证的假设：macOS 上 pywebview 需 pyobjc 依赖（pip 自动解析）；打包后 GUI 运行需要真实桌面环境验证，无头 CI 环境无法完整验证窗口行为。
