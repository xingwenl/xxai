# Desktop App 脚手架（pywebview + FastAPI）

基于 **pywebview + FastAPI** 的基础桌面应用脚手架：单进程内嵌 FastAPI 服务，pywebview 窗口加载服务托管的 HTML 页面。可独立打包为桌面应用，与 `apps/backend`、`apps/front` 完全解耦。

## 目录结构

```text
apps/desktop/
  pyproject.toml          # Poetry 工程配置（Python 3.12）
  package.json            # 插件共享样式编译脚本（build_css.mjs）
  front/                  # 宿主前端主项目（React 19 + Vite + Tailwind v4）
    src/App.tsx           # 宿主壳：应用页 / 设置页 / 插件视图
    src/components/       # plugin-view（iframe+SDK 注入）、settings
    src/lib/              # api.ts、desktop-sdk.ts、toast.ts
    dist/                 # 构建产物（由内嵌 FastAPI 托管）
  desktop_app/
    __main__.py           # python -m desktop_app 入口
    main.py               # 窗口与后台服务线程编排
    server.py             # FastAPI 应用工厂（/api/desktop/* + /apps + 前端托管）
    registry.py           # 插件扫描（内置 + 用户）
    manager.py            # 插件安装/卸载/启停与状态持久化
    protocol.py           # manifest 协议
    security.py           # zip 安全解压
    host_api.py           # pywebview js_api 桥
    paths.py              # 开发/打包双模式资源路径解析
  static/css/tailwind.css # 插件共享样式（编译产物）
  plugins/hello-world/    # 内置示例插件
  scripts/                # make_plugin_zip.py、build_css.mjs
  build/desktop.spec      # PyInstaller 打包配置（onedir）
  build/build.py          # 跨平台打包脚本
  tests/                  # 服务层与插件体系测试
```

## 环境准备

```bash
cd apps/desktop
poetry env use python3.12
poetry install --with dev
pnpm --dir apps/desktop/front install
```

macOS 上 pywebview 会通过 pip 自动安装 pyobjc 系列依赖，首次安装耗时较长属正常现象。

## 开发运行

```bash
cd apps/desktop
pnpm --dir apps/desktop/front build   # 构建宿主前端（首次或前端改动后）
poetry run python -m desktop_app
```

窗口加载宿主前端（`apps/desktop/front` 的构建产物），左侧导航可在应用页/设置页切换，应用页展示已安装插件。
关闭窗口即停止内嵌服务并退出进程。

点击应用卡片会**自动进入全屏**展示：iframe 铺满整个窗口，头部与侧栏默认隐藏，
仅保留屏幕顶部与左侧边缘的细毛玻璃把手（hover / 点击展开）。
按 `Esc`、头部「退出全屏」或「返回」回到常规形态（侧栏 + 悬浮头部）。

## 开发模式（改样式不用每次 build）

普通启动加载的是 `front/dist` 构建产物，前端每次改动都要重新 `pnpm build`。
开发时建议用下面的方式获得热更新与浏览器控制台。

### 方式一：浏览器调试（推荐，改样式即时生效）

1. 终端 A 启动 API 服务（固定端口 8765）：

   ```bash
   cd apps/desktop
   poetry run python -m desktop_app.server
   ```

2. 终端 B 启动 Vite dev server（HMR，端口 8443，自动代理 `/api` `/apps` `/css` 到上面的 API）：

   ```bash
   pnpm --dir apps/desktop/front dev
   ```

3. 用 Chrome 打开 `http://localhost:8443`，按 `Cmd+Option+I` 打开 DevTools 调试样式；
   修改 `front/src/` 代码会热更新，不需要 build。

### 方式二：真实窗口内调试（pywebview + Web Inspector）

```bash
cd apps/desktop
pnpm --dir apps/desktop/front dev        # 先启动 Vite dev server
DESKTOP_DEV_FRONT=1 DESKTOP_DEBUG=1 poetry run python -m desktop_app
```

- `DESKTOP_DEV_FRONT=1`：窗口直接加载 Vite dev server，改样式即时生效，不用 build。
- `DESKTOP_DEBUG=1`：启用 Web Inspector（macOS 上窗口右键 → 检查元素，或启动时自动打开检查器）。

### 什么时候才需要 build

- 正式启动（不带 `DESKTOP_DEV_FRONT` 的 `poetry run python -m desktop_app`，加载 `front/dist`）。
- 打包前（`poetry run python build/build.py`）。

> 端口可用环境变量覆盖：`DESKTOP_API_PORT`（开发 API 端口，默认 8765，Vite 代理同步读取）；
> Vite dev server 固定 8443。

## 测试

```bash
cd apps/desktop
poetry run pytest tests/
```

## 打包

```bash
cd apps/desktop
pnpm --dir apps/desktop/front build   # 打包前必须构建宿主前端
poetry run python build/build.py
```

产物输出到 `apps/desktop/dist/`：

- macOS：`dist/desktop-app.app`（应用包）与 `dist/desktop-app/`（目录产物）
- Windows / Linux：`dist/desktop-app/` 目录产物

运行打包产物（目录产物）：

```bash
./dist/desktop-app/desktop-app
```

## 基础框架：应用页 / 设置页 + 插件化应用体系

宿主壳由 `apps/desktop/front/`（React 19 + Vite + Tailwind v4）构建，提供两个一级页面（左侧导航切换）：

- **应用页**：图标网格展示已安装插件，点击后在内容区 iframe 加载插件页面。
- **设置页**：zip 安装插件、启用/禁用、卸载，以及框架信息。

插件 = 一个目录（`manifest.json` + 静态资源）。内置插件位于 `plugins/`（随应用分发、不可卸载）；用户通过 zip 安装的插件存放在 `~/.desktop-app/plugins/`，启停状态持久化到 `~/.desktop-app/state.json`。

### 宿主 SDK（插件可用工具方法）

插件页面由宿主（`front/src/lib/desktop-sdk.ts`）注入 `window.desktop`（在 iframe `load` 完成后触发 `desktop-ready` 事件），能力按 `manifest.permissions` 白名单裁剪：

| 能力 | manifest 权限 | 方法 |
|---|---|---|
| 生命周期 | 默认 | `desktop.ready`、`appInfo()`、`getApps()`、`navigate(path)`、`openApp(id)` |
| 通知 | `notify` | `notify({title, body})`（宿主 toast） |
| 设置 | `settings` | `settings.get(key, default?)` / `settings.set(key, value)` |
| 存储 | `storage` | `storage.get(key, default?)` / `storage.set(key, value)` |
| 事件总线 | `events` | `events.on(event, handler)` / `events.emit(event, payload)`（宿主跨插件转发） |
| HTTP 代理 | `http` | `http.get(url, opts)` / `http.post(url, opts)`（经 `/api/desktop/proxy`） |
| 平台信息 | `platform` | `platform.info()` |
| 日志 | `log` | `log.info/warn/error(...)` |

未声明权限的方法调用会抛出「权限不足」错误。

### 插件 manifest 约定

```json
{
  "id": "hello-world",
  "name": "你好世界",
  "version": "0.1.0",
  "description": "示例应用",
  "icon": "icon.svg",
  "entry": "index.html",
  "permissions": ["notify", "settings", "storage", "events", "http", "platform", "log"]
}
```

- `id` 必须匹配 `^[a-z0-9][a-z0-9_-]*$` 且与插件目录名一致。
- `entry` / `icon` 必须是包内相对路径，禁止绝对路径与 `..`。
- zip 包结构：根为插件目录，或根下仅一个含 `manifest.json` 的目录（自动归一化）。

### 开发一个插件

1. 在 `plugins/<id>/` 创建 `manifest.json` 与入口页面。
2. 入口脚本等待 SDK 注入：

```html
<script>
  (async () => {
    await new Promise((resolve) => {
      if (window.desktop) return resolve();
      window.addEventListener("desktop-ready", () => resolve(), { once: true });
    });
    const d = window.desktop;
    await d.notify({ title: "你好", body: "宿主通知" });
  })();
</script>
```

3. 启动应用后在设置页上传打包的 zip，或直接放入用户插件目录。

> 提示：插件入口页建议在 `<head>` 中内联设置背景色（如 `background: #020617`），
> 避免在宿主样式文件加载完成前出现白屏闪动；宿主会在插件页加载完成后淡入显示。

### 样式

- 宿主壳样式：由 `front` 的 Vite + Tailwind v4 构建，改 `front/src/` 后执行 `pnpm --dir apps/desktop/front build`。
- 插件页共享样式：`static/css/tailwind.css`（编译产物，运行时零依赖），修改后重新编译：

```bash
cd apps/desktop
node scripts/build_css.mjs       # 一次性编译（离线）
node scripts/build_css.mjs --watch
```

`src/input.css` 是插件共享样式源文件；候选类名自动从 `static/`、`plugins/`、`src/` 中扫描。

### 自定义页面与接口

- 宿主壳界面代码在 `apps/desktop/front/src/`（App.tsx、components/、lib/），构建产物由内嵌 FastAPI 托管在 `/`。
- 在 `desktop_app/server.py` 的 `create_app()` 中新增 `/api/desktop/*` 路由即可扩展宿主能力。
- `desktop_app/host_api.py` 的 `HostApi` 暴露 pywebview `js_api` 能力（仅宿主壳页面可调用；插件一律走宿主 SDK）。
- `static/` 仅保留插件共享 CSS 与「前端未构建」回退页。

## 常见问题

- **启动后显示「宿主前端未构建」**：先执行 `pnpm --dir apps/desktop/front build` 生成 `front/dist`。
- **打包后页面 404**：确认 `build/desktop.spec` 的 `datas` 包含 `(front/dist, "front_dist")`、`(static, "static")` 与 `(plugins, "plugins")`，且 `paths.py` 在打包模式下指向 `sys._MEIPASS` 对应目录。
- **插件页报「权限不足」**：检查插件 `manifest.json` 的 `permissions` 是否声明了对应能力（notify/settings/storage/events/http/platform/log）。
- **插件页拿不到 `window.desktop`**：插件必须在 `desktop-ready` 事件后再使用 SDK，参考上文示例写法。
- **开发时怎么打开控制台**：浏览器模式直接按 `Cmd+Option+I`；pywebview 窗口用 `DESKTOP_DEBUG=1` 启动后右键 → 检查元素。
- **主题 / 星标重启后丢失**：确认以本仓库代码启动（已关闭 pywebview 隐私模式）；旧版本安装的应用不受影响。
- **窗口无法启动**：pywebview 依赖系统 WebView，macOS 需 macOS 10.13+，Linux 需安装 GTK 与 WebKit2 相关库。
