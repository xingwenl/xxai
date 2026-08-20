# 验收记录

## 验收结论

已达到 `spec.md` 中的验收标准，本 request 可以视为完成：

- `apps/desktop/` 工程结构完整，开发模式 `poetry run python -m desktop_app` 可启动桌面窗口并加载 `static/index.html` 页面（用户人工确认窗口正常打开、页面与 `js_api` 响应正常）。
- FastAPI 服务内嵌运行于窗口生命周期内：`/api/health` 返回 `{"status": "ok", "service": "desktop-app", "version": "0.1.0"}`，pytest 3 项全部通过；窗口关闭即退出进程。
- `poetry run python build/build.py` 可产出 PyInstaller 产物（`dist/desktop-app/` 与 macOS `dist/desktop-app.app`）；打包模式路径解析模拟验证通过，静态资源与接口均正常。
- `ruff check .` 无告警；中文 `README.md` 已交付，覆盖开发运行、测试、打包、运行产物说明。
- Harness 文档齐全：`research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 剩余风险

- 打包产物（`dist/desktop-app/desktop-app`）的 GUI 实机运行未单独记录，建议用户补跑一次确认；其资源路径与页面逻辑已通过模拟 `sys._MEIPASS` 验证。
- 仅在本机 macOS（arm64）验证，Windows/Linux 打包与运行未实测；`build/desktop.spec` 的 macOS BUNDLE 分支对其他平台不生效，属预期行为。
- 未做应用签名与公证、安装包制作，属于 `spec.md` 非目标范围。
- pyinstaller 当前要求 Python <3.16，已通过 marker 约束；未来 Python 3.16 发布后如需打包，需同步调整约束。

## 人工验收记录

- 2026-08-20，用户人工确认：桌面应用可正常打开，能看到正常响应（页面加载与 `js_api` 互调正常）。
- 2026-08-20，用户在进入实现前已确认方案 A + 方案 C + 与现有 backend/front 完全解耦的设计（记录于 `meta.json` 审批字段）。
