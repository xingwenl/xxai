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
- Harness 文档齐全：`research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 变更记录

### 初始版本

- 时间：2026-08-20
- 变更原因：首次创建 request
- 变更内容：建立 pywebview + FastAPI 桌面脚手架任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：是（架构边界变化；用户口头确认「可以」，详见停点判断）
