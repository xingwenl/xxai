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

## 轻量变更验证（2026-08-21：统一应用元信息配置）

1. `pytest tests/`：54 passed（含 `/api/health` `service=WW`、首页包含 `WW`、`/api/desktop/settings` 含 `name=WW` 的新断言）。
2. `pnpm --dir apps/desktop/front build`：构建成功，`front/dist` 输出 `icon.png` / `icon.icns` / `icon.ico` 与前端产物。
3. PyInstaller 打包（`PYINSTALLER_CONFIG_DIR=/tmp/...`）：产出 `WW` 目录产物与 `WW.app`；`Info.plist` 校验 `CFBundleName/CFBundleDisplayName=WW`、`CFBundleShortVersionString/CFBundleVersion=0.2.0`、`CFBundleIdentifier=com.ww.desktop`、`CFBundleIconFile=icon.icns`，`Resources/icon.icns` 存在。
4. `python scripts/make_icons.py`：由 `assets/icon.png`（1024×1024）生成 `icon.icns`（icp4–ic10 分块）与 `icon.ico`（16/32/48/64/128/256 六尺寸），`file` 校验为合法 icns / ico。注：沙箱内 `iconutil` 不可用（对系统自带图标做往返转换同样失败），故脚本用标准库直接打包 PNG 分块（macOS 10.7+ 官方支持的 icns 形态）。

### fix：macOS 图标空白问题（同日追加）

- 问题：`sips` 缩放输出会携带 `eXIf` / `sRGB` 分块，部分 macOS 图标渲染路径会将 Dock/应用图标显示为空白；且开发模式（`python -m desktop_app`）没有 `.app` 包，本就不会使用自定义图标。
- 修复：`make_icons.py` 打包前剥离附加分块（只保留 IHDR/IDAT/IEND，与 `iconutil` 产物一致）；`main.py` 在 macOS 上通过 `webview.start(icon=assets/icon.png)` 运行时设置 Dock 图标；`desktop.spec` datas 增加 `assets/` 目录，使打包产物也携带运行时图标。
- 复核：重新生成 icns 内部仅含 IHDR/IDAT/IEND；`pytest tests/` 55 passed；PyInstaller 重新打包成功，`WW.app` 的 `Resources/icon.icns` 无 eXIf、`Resources/assets/icon.png` 存在。

## 失败项与例外

- GUI 启动验证（开发模式 `python -m desktop_app` 与打包产物）因沙箱禁止绑定 `127.0.0.1` 端口、且审批服务故障（HTTP 503）未能由 AI 直接执行，需用户在本机桌面环境人工运行确认。
- 沙箱内首次启动 `python -m desktop_app` 复现了预期失败路径：绑定端口被拒后 `_wait_until_ready` 抛出「内嵌 FastAPI 服务启动超时」，进程正常退出，说明错误处理符合设计。
- 打包命令在沙箱内因 PyInstaller 需要写 `~/Library/Application Support/pyinstaller` 被拒，已通过 `PYINSTALLER_CONFIG_DIR` 重定向缓存到工作区解决（等价于官方支持的配置目录覆盖）。
