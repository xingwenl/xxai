# 实施计划：Desktop 基础框架（应用页 / 设置页 + 插件化应用体系）

## 步骤

### 1. 文档与元数据（已完成）

- 创建 `research.md`、`spec.md`、更新 `meta.json`（phase=plan、approvalGranted=true）。

### 2. 前端工程化（Tailwind）

- 新增 `apps/desktop/package.json`：devDependency `@tailwindcss/cli`，脚本 `css` / `css:watch`。
- 新增 `apps/desktop/src/input.css`（Tailwind v4 `@import "tailwindcss"` + `@theme` 自定义主题）。
- `pnpm --dir apps/desktop install` 后执行 `pnpm --dir apps/desktop css`，产物 `static/css/tailwind.css`。

### 3. Python 协议与安全层

- `protocol.py`：`PluginManifest`（pydantic）+ 校验（id 正则、entry/icon 相对路径、permissions 白名单）。
- `security.py`：`safe_extract_zip(zip_path, dest)`，限制大小/条目/单文件、拒绝穿越/绝对路径/符号链接。
- 单元测试 `test_protocol.py`、`test_security.py`。

### 4. 插件管理（Registry / Manager）

- `paths.py`：新增 `builtin_plugins_dir()`、`user_data_dir()`、`user_plugins_dir()`、`state_file()`。
- `registry.py`：`PluginRegistry` 扫描内置 + 用户目录，解析 manifest，合并 `state.json` 启停状态，内置优先。
- `manager.py`：`PluginManager` — `install_zip()`（临时目录 + 归一化 + 原子 rename）、`uninstall()`、`set_enabled()`、状态读写。
- 单元测试 `test_registry.py`、`test_manager.py`。

### 5. 内嵌服务与桥接

- `server.py`：注册 `/api/desktop/plugins`（列表/安装/启停/卸载）、`/api/desktop/settings`、`/api/desktop/proxy`；挂载 `/apps/` 与宿主静态资源；保留 `/api/health`。
- `host_api.py`：`HostApi`（app_info、plugins_summary、open_file_dialog 预留），只对宿主页开放。
- `main.py`：窗口加载宿主壳，`js_api=HostApi(...)`。
- 扩展 `tests/test_server.py`（插件列表、安装、静态访问、启停、卸载、proxy）。

### 6. 宿主壳前端

- `static/index.html`：宿主壳布局（导航 + 内容区，Tailwind 样式）。
- `static/js/sdk.js`：SDK 构造器（ready、appInfo、getApps、navigate、notify、settings、storage、events、http、platform、log；按 manifest permissions 裁剪）。
- `static/js/host.js`：hash 路由、应用页渲染、iframe 创建 + SDK 注入 + `desktop-ready`、事件总线转发、toast、设置页交互。

### 7. 内置示例插件 + zip 打包脚本

- `plugins/hello-world/`：manifest + icon.svg + index.html（演示全部 SDK 能力）。
- `scripts/make_plugin_zip.py`：生成 `dist/hello-world-<version>.zip`。

### 8. 打包与文档

- `build/desktop.spec`：datas 增加 `plugins` 目录。
- `README.md`：补充框架说明（宿主壳、插件开发指南、SDK 能力表、zip 安装）。

### 9. 验证

- `pytest tests/` 全绿。
- 编译产物存在：`static/css/tailwind.css` 非空。
- 启动内嵌服务（不建窗口的验证模式或直接运行应用），用 curl 验证 `/api/desktop/plugins`、`/apps/hello-world/`、安装 zip 往返。
- 人工 GUI 验证：宿主壳导航、插件 iframe 加载、SDK 能力调用、设置页安装/启停/卸载、重启后状态保持。

## 验证命令

```bash
cd apps/desktop
pnpm css
poetry run pytest tests/ -q
poetry run python -m desktop_app          # GUI 人工验证
poetry run python scripts/make_plugin_zip.py
```

## 回滚

- 全部改动集中在 `apps/desktop/`，单次提交即可回滚。
- 若 Tailwind 编译异常：保留 `static/css/tailwind.css` 产物即可继续，回退 `package.json` 与 `src/` 不影响运行。
- 若插件体系异常：宿主壳保留，回退 `registry/manager/security` 层不影响既有 health 页面功能。

## 追加计划：宿主前端迁移到 React（`apps/desktop/front`）

### R1. 前端工程整理

- `apps/desktop/front/`：剥离 Figma Make 专用配置（`.figma/`、vite 配置中的 figma 插件与 site.json 引用），只保留 `react()` + `tailwindcss()` + `@` 别名；`index.html` 去掉 figma 占位符，标题改为 Desktop App。
- `src/App.tsx`：把启动器数据源从 mock `APPS` 切换到 `/api/desktop/plugins`；打开应用改为渲染插件 iframe 视图；侧栏保留「应用 / 设置」导航。
- 新增 `src/lib/desktop-sdk.ts`：从 `static/js/sdk.js` 迁移 SDK（权限裁剪、settings/storage/events/http/platform/log、事件总线）。
- 新增 `src/components/plugin-view.tsx`：iframe + sandbox + `desktop-ready` 注入 + 深色底淡入（沿用闪白修复）。
- 新增 `src/components/settings.tsx`：应用管理（zip 上传安装、启停、卸载）+ 框架信息，沿用现有主题变量。
- 新增轻量 toast 组件与设置持久化（主题偏好写入 localStorage）。
- `src/index.css`：Google Fonts 保留 fallback（离线时回退系统字体）。

### R2. 构建与托管

- `apps/desktop/front`：`pnpm build` 产物 `front/dist`；`paths.py` 新增 `front_dist_dir()`（开发 = `front/dist`，打包 = `sys._MEIPASS/front_dist`）。
- `desktop_app/server.py`：根路径静态托管切换到 `front_dist_dir()`；`/apps/<id>/` 与 `/api/desktop/*` 不变。
- `build/desktop.spec`：datas 增加 `(front/dist, "front_dist")`。
- 插件共享 CSS：`scripts/build_css.mjs` 继续产出 `static/css/tailwind.css`（`static/` 仅保留该产物）。
- `tests/test_server.py`：首页断言更新为 React 构建产物标记（`<div id="root">` / assets）；其余接口测试不变。

### R3. 文档与验证

- 更新 `apps/desktop/front/AGENTS.md`（去掉 Figma 开发服务器说明，改为桌面宿主构建说明）与根 `README.md`。
- 验证：`pnpm --dir apps/desktop/front build` 成功、`pytest tests/` 全绿、`node scripts/build_css.mjs` 成功。
- 人工 GUI 验证：启动器真实插件渲染、打开插件 iframe、SDK 能力、设置页安装/启停/卸载、主题切换与重启持久化。

### 回滚

- `apps/desktop/front/` 为新增主项目，回滚时恢复 `static/` 宿主壳（git 保留）并将 `paths.front_dist_dir()` 切回 `static_dir()` 即可。
