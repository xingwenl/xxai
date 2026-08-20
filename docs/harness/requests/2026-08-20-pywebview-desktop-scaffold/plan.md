# 实施计划

## 变更文件

| 文件 | 职责 |
|---|---|
| `apps/desktop/pyproject.toml` | Poetry 工程配置：运行依赖 pywebview/fastapi/uvicorn；开发依赖 pytest/ruff/pyinstaller；`python = "3.12"` |
| `apps/desktop/desktop_app/__init__.py` | 包元信息与版本号 |
| `apps/desktop/desktop_app/__main__.py` | `python -m desktop_app` 入口，调用 `main.run()` |
| `apps/desktop/desktop_app/main.py` | 启动后台 uvicorn 线程 + pywebview 窗口编排，窗口关闭后停止服务退出 |
| `apps/desktop/desktop_app/server.py` | FastAPI 应用工厂：`/api/health` + `StaticFiles(html=True)` 托管 `static/` |
| `apps/desktop/desktop_app/paths.py` | 资源路径解析：开发模式相对包目录，打包模式 `sys._MEIPASS` |
| `apps/desktop/static/index.html` | 最小示例页：展示服务状态，演示 `js_api` 互调 |
| `apps/desktop/build/desktop.spec` | PyInstaller spec：onedir、收集 `static/` 资源、uvicorn 相关 hiddenimports |
| `apps/desktop/build/build.py` | 跨平台打包脚本：调用 PyInstaller 并输出产物路径 |
| `apps/desktop/tests/test_server.py` | 测试 `/api/health` 与静态首页渲染 |
| `apps/desktop/README.md` | 中文使用说明：开发运行、测试、打包、运行产物 |
| `docs/harness/requests/2026-08-20-pywebview-desktop-scaffold/*` | Harness 文档（research/spec/plan/verify/acceptance/meta） |

实施步骤落实 `research.md` 最终决策：pywebview 主线程加载内嵌 FastAPI 的 HTTP 页面（集成形态 A'），静态资源由 `paths.py` 统一解析（方案 C），页面为自带最小示例（方案 A）。

## 实施步骤

1. 先落 Harness 文档（research/spec/plan/meta.json），固定设计与审批记录。
2. 编写 `pyproject.toml`，初始化 Poetry 虚拟环境并安装依赖（macOS 需确认 pyobjc 自动解析）。
3. 实现包代码：`paths.py` → `server.py` → `main.py` → `__init__.py`/`__main__.py`。
4. 编写 `static/index.html` 最小示例页与 `tests/test_server.py`。
5. 编写 `build/desktop.spec` 与 `build/build.py`，执行打包并验证产物。
6. 编写 `README.md`。
7. 执行验证并填写 `verify.md`、`acceptance.md`，更新 `meta.json` 至 `phase: acceptance`。

## 测试步骤

- `poetry run pytest tests/`：预期全部通过（覆盖 `/api/health`、静态首页 `200`）。
- `poetry run python -m desktop_app`：预期弹出桌面窗口并加载页面（GUI 操作，需真实桌面环境；若环境无头则记录限制）。
- `poetry run python build/build.py`：预期生成 `dist/` 下 onedir 产物。
- 运行打包产物：预期可启动窗口并加载页面（GUI 操作，需真实桌面环境）。

## 回滚说明

- 本次为新增目录与新增文档，不影响现有 backend/front 代码，回滚直接删除 `apps/desktop/` 与本次 request 文档目录即可。
- 若 `pyproject.toml` 或依赖安装失败，可先删除 `apps/desktop/.venv` 与 `pyproject.toml` 重新初始化。
- 注意：不要将本任务改动混入其他 request 的提交。

## 人工确认点

- 架构边界变化（新增独立桌面应用子项目）：用户在 2026-08-20 对话中已确认「可以」，同意方案 A + 方案 C + 与现有 backend/front 完全解耦，此处作为已确认记录。
