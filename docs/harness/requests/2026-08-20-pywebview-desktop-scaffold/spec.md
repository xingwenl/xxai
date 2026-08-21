# 设计说明

## 目标

- 在 `apps/desktop/` 下搭建基于 pywebview + FastAPI 的基础桌面应用脚手架，作为后续桌面应用开发的起点。
- 目标用户：需要快速起一个本地桌面应用的原型/产品开发者；调用方为应用入口 `python -m desktop_app` 或打包产物可执行文件。
- 完成后的可验证结果：开发模式下能启动桌面窗口并加载内置 HTML 页面；`python build/build.py` 能产出 PyInstaller 打包产物，产物可直接启动并加载页面；FastAPI 健康检查接口可访问。
- 关键调研结论（详见 `research.md`）：加载自带最小静态页（方案 A）、PyInstaller onedir 完整打包并做开发/打包资源路径兼容（方案 C）、单进程内嵌 uvicorn 在后台线程运行 FastAPI（集成形态 A'）。

## 范围

- 新增目录 `apps/desktop/`，包含：
  - `pyproject.toml`：Poetry 工程配置（pywebview、fastapi、uvicorn 运行依赖；pytest、ruff、pyinstaller 开发依赖）
  - `desktop_app/`：包代码（入口、窗口与线程编排、FastAPI 应用工厂、资源路径解析）
  - `desktop_app/app_config.py`：应用元信息统一配置（名称 / 版本 / Bundle ID / Logo 路径）
  - `assets/`：品牌资源（`icon.png` 源图与生成的 `icon.icns` / `icon.ico`）
  - `static/index.html`：最小示例页面（展示服务状态，并可选演示 `js_api` 互调）
  - `build/desktop.spec` + `build/build.py`：PyInstaller 打包配置与跨平台打包脚本
  - `tests/test_server.py`：FastAPI 路由与静态页测试
  - `README.md`：脚手架使用说明
- 本次为全新独立子项目，与 `apps/backend`、`apps/front` 无任何依赖或联动。

## 非目标

- 不代理或复用现有 `apps/backend` 的 API 与数据层。
- 不构建现有 `apps/front` 的前端产物。
- 不做自动更新、多窗口管理、系统托盘等高级桌面能力（留待后续 request）。
- 不处理 Windows 签名、公证、安装包制作（仅产出可运行目录产物）。

## 风险

- 平台风险：macOS 上 pywebview 依赖 pyobjc 系列包，安装体积较大；Windows/Linux 依赖不同（pywin32 / GTK），打包脚本需按平台分支处理。
- 线程风险：uvicorn 运行在后台线程，窗口关闭时需要可靠地停止服务并退出进程，避免残留线程。
- 打包风险：PyInstaller 对动态导入（如 uvicorn 的 loop 实现）可能需要 `hiddenimports` 补充；资源路径必须兼容开发与打包两种形态。

## 停点判断

- 是否涉及架构边界变化：是（新增独立桌面应用子项目，引入 pywebview 桌面运行形态）
- 是否涉及数据模型变化：否
- 是否涉及 API 契约变化：否（新增脚手架自带的 `/api/health`，不触碰现有 backend API）
- 是否涉及鉴权或权限行为变化：否
- 结论：涉及架构边界变化，进入实现前需人工确认。用户已在 2026-08-20 对话中确认「可以」，同意方案 A + 方案 C 及与现有 backend/front 完全解耦的设计。

## 验收标准

- `apps/desktop/` 下工程结构完整，`python -m desktop_app` 可启动桌面窗口并加载 `static/index.html` 页面。
- FastAPI 服务内嵌运行于窗口生命周期内，`/api/health` 返回 `{"status": "ok", ...}`；窗口关闭后进程正常退出。
- `python build/build.py` 可产出 PyInstaller 打包产物；产物运行后可加载页面，开发与打包两种形态的资源路径均正确。
- `pytest tests/` 通过，覆盖 `/api/health` 与静态首页渲染。
- 交付中文 `README.md`，说明开发运行、测试、打包、产物运行四个环节。
- 应用名称（WW）、版本号与 Logo 通过 `desktop_app/app_config.py` + `assets/` 统一管理，窗口标题、设置页框架信息、`/api/health`、前端 SDK、macOS Info.plist 与打包产物名全部跟随。
- Harness 文档齐全：`research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 变更记录

### 初始版本

- 时间：2026-08-20
- 变更原因：首次创建 request
- 变更内容：建立 pywebview + FastAPI 桌面脚手架任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：是（架构边界变化；用户口头确认「可以」，详见停点判断）

### 2026-08-21 第 1 次变更

- 变更原因：统一应用品牌信息（名称 / Logo / 版本号），集中管理便于后续替换
- 变更内容：新增 `desktop_app/app_config.py` 集中维护 `APP_NAME=WW`、`APP_VERSION=0.2.0`、`APP_BUNDLE_ID` 与 Logo 路径；新增 `assets/`（icon.png 源图 + 生成的 icns/ico）与 `scripts/make_icons.py`；窗口标题、内嵌 FastAPI 标题、`/api/health`、`/api/desktop/settings`（新增 `name` 字段）、前端 SDK 与设置页、PyInstaller 打包（产物名 / 图标 / Info.plist）全部改为从统一配置读取
- 影响章节：范围、验收标准
- 是否触发人工确认：否（均为内部增量：`/api/desktop/settings` 新增 `name` 为向后兼容扩展，SDK `appInfo()` 改为异步且当前无调用方，均不构成对外契约破坏）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-21 fix：macOS 图标空白

- 变更原因：用户反馈 Logo 显示为空白
- 变更内容：`make_icons.py` 剥离 PNG 附加分块（sRGB/eXIf/pHYs）避免 macOS 图标渲染空白；`main.py` 通过 `webview.start(icon=...)` 在开发模式运行时设置 Dock 图标；`desktop.spec` datas 携带 `assets/` 目录
- 影响章节：验收标准（图标在开发与打包形态均可见）
- 是否触发人工确认：否
- 关联计划更新：已同步更新 `verify.md`
