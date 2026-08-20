# Desktop App 脚手架（pywebview + FastAPI）

基于 **pywebview + FastAPI** 的基础桌面应用脚手架：单进程内嵌 FastAPI 服务，pywebview 窗口加载服务托管的 HTML 页面。可独立打包为桌面应用，与 `apps/backend`、`apps/front` 完全解耦。

## 目录结构

```text
apps/desktop/
  pyproject.toml          # Poetry 工程配置（Python 3.12）
  desktop_app/
    __main__.py           # python -m desktop_app 入口
    main.py               # 窗口与后台服务线程编排
    server.py             # FastAPI 应用工厂（/api/health + 静态托管）
    paths.py              # 开发/打包双模式资源路径解析
  static/index.html       # 最小示例页面（含 js_api 互调演示）
  build/desktop.spec      # PyInstaller 打包配置（onedir）
  build/build.py          # 跨平台打包脚本
  tests/test_server.py    # 服务层测试
```

## 环境准备

```bash
cd apps/desktop
poetry env use python3.12
poetry install --with dev
```

macOS 上 pywebview 会通过 pip 自动安装 pyobjc 系列依赖，首次安装耗时较长属正常现象。

## 开发运行

```bash
cd apps/desktop
poetry run python -m desktop_app
```

窗口加载 `static/index.html`，页面通过 `fetch("/api/health")` 探测内嵌服务状态，点击按钮可演示 `window.pywebview.api.app_info()` 调用 Python 侧方法。关闭窗口即停止内嵌服务并退出进程。

## 测试

```bash
cd apps/desktop
poetry run pytest tests/
```

## 打包

```bash
cd apps/desktop
poetry run python build/build.py
```

产物输出到 `apps/desktop/dist/`：

- macOS：`dist/desktop-app.app`（应用包）与 `dist/desktop-app/`（目录产物）
- Windows / Linux：`dist/desktop-app/` 目录产物

运行打包产物（目录产物）：

```bash
./dist/desktop-app/desktop-app
```

## 自定义页面与接口

- 替换或新增 `static/` 下的静态资源即可改变界面，无需额外构建步骤。
- 在 `desktop_app/server.py` 的 `create_app()` 中新增 FastAPI 路由即可扩展后端能力。
- 在 `desktop_app/main.py` 的 `Api` 类中新增方法即可暴露新的 `js_api` 接口（方法名不能以下划线开头）。

## 常见问题

- **打包后页面 404**：确认 `build/desktop.spec` 的 `datas` 包含 `(static 目录, "static")`，且 `paths.py` 在打包模式下指向 `sys._MEIPASS/static`。
- **窗口无法启动**：pywebview 依赖系统 WebView，macOS 需 macOS 10.13+，Linux 需安装 GTK 与 WebKit2 相关库。
