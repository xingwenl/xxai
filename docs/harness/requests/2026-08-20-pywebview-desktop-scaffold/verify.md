# 验证记录

## 执行命令

以下命令均在 `apps/desktop/` 目录下、Poetry 虚拟环境（Python 3.12.4）中执行：

1. `poetry check`
2. `poetry run pytest tests/ -v`
3. `poetry run ruff check .`
4. `PYINSTALLER_CONFIG_DIR=$PWD/build/pyinstaller-cache poetry run python build/build.py`
5. 打包产物结构与路径解析脚本（模拟 `sys.frozen` / `sys._MEIPASS` 的验证脚本）

## 预期结果

1. 配置文件合法，依赖解析无冲突。
2. 3 个测试全部通过：`/api/health` 返回 `{"status": "ok", ...}`；首页 `200` 且包含 `pywebview`/`Desktop App`；缺失资源 `404`。
3. ruff 静态检查无告警。
4. 打包成功，产出 `dist/desktop-app/`（onedir）与 macOS `dist/desktop-app.app`，`static/index.html` 打入 `_internal/static/`。
5. 打包模式路径解析指向 `_MEIPASS/static` 且页面与服务接口可访问。

## 实际结果

1. `poetry check` 通过；期间修复了 pyinstaller 与 `requires-python (>=3.12,<4.0)` 的求解冲突（为其增加 `python_version < '3.16'` marker）。
2. `pytest`：3 passed（`test_health`、`test_index_page`、`test_static_asset`），仅有 starlette/httpx 弃用警告，不影响结果。
3. `ruff check .`：All checks passed。
4. 打包成功：`dist/desktop-app/` 与 `dist/desktop-app.app` 均生成；`_internal/static/index.html` 存在；`.app` 内含 WebKit、AppKit 等框架与签名。期间修复 spec 中 `project_root` 层级错误（`SPECPATH` 的 `.parent` 即项目根）。
5. 模拟打包环境验证通过：`static_dir()` 解析为 `dist/desktop-app/_internal/static`，首页 `200`、`/api/health` 返回 `{"status": "ok", "service": "desktop-app", "version": "0.1.0"}`。

## 失败项与例外

- GUI 启动验证（开发模式 `python -m desktop_app` 与打包产物）因沙箱禁止绑定 `127.0.0.1` 端口、且审批服务故障（HTTP 503）未能由 AI 直接执行，需用户在本机桌面环境人工运行确认。
- 沙箱内首次启动 `python -m desktop_app` 复现了预期失败路径：绑定端口被拒后 `_wait_until_ready` 抛出「内嵌 FastAPI 服务启动超时」，进程正常退出，说明错误处理符合设计。
- 打包命令在沙箱内因 PyInstaller 需要写 `~/Library/Application Support/pyinstaller` 被拒，已通过 `PYINSTALLER_CONFIG_DIR` 重定向缓存到工作区解决（等价于官方支持的配置目录覆盖）。
