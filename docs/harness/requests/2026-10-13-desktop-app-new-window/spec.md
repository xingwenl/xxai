---
id: 2026-10-13-desktop-app-new-window
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["API 契约变化：宿主 js_api 新增 open_app / close_current_window，README 契约节需同步", "插件契约变化：manifest 新增可选字段 open_mode，registry 与前端 Plugin 类型同步", "生命周期变化：主窗口关闭须连带销毁子窗口，否则子窗口会失去内嵌服务"]
---

## 目标与范围

一句话：子应用的打开方式交给**插件自己声明**（当前页面 / 浏览器 / 新原生窗口），用户可以在应用卡片上**右键临时切换**打开方式。

- 使用者：使用 `apps/desktop` 桌面客户端的本人。
- 三种打开方式（针对「应用」这个目标）：
  - `inline`（默认）：现状，宿主壳内展开子应用（`#/app/<id>` + 全屏沉浸）。
  - `browser`：系统默认浏览器打开。普通插件的目标是壳深链，`remote` 插件的目标是它自己的 `url`。
  - `window`：新的 pywebview 原生窗口。窗口里加载的仍是宿主壳页面 + 深链 `#/app/<id>`，因此插件的 iframe 沙箱、`window.desktop` SDK 注入、权限白名单**完全不变**。
- 非目标（不做）：
  - 不做「在当前页面打开任意外链」（壳内网页视图）：需要新做浏览面板，且多数站点用 `X-Frame-Options`／`CSP: frame-ancestors` 禁止被 iframe（见 MDN 该头文档），投入产出比不成立。本轮三种方式只作用于「应用」目标。
  - 不做多实例：同一应用只保留一个窗口，重复操作用 `restore()` + `show()` 聚焦已有窗口。
  - 不做窗口尺寸/位置记忆，也不做插件自定义尺寸（v1 固定 1100×760，min 800×600）——因此不改 `manifest.json` 除 `open_mode` 以外任何字段。
  - 不做窗口间实时状态同步（主题、星标继续走 localStorage，各窗口加载时各读一次）。
  - 不做托盘、自动更新、多显示器定位；不改 `apps/backend`、`apps/front`。
  - **已知降级**：`browser` 模式打开的是浏览器里的壳页面，没有 `window.pywebview`，宿主桥（文件对话框等）不可用；本轮不做桥接，由插件自行降级。`remote` 插件直接开自己的 `url`，不受此影响。

## 来源与方案比较

调研对象：**pywebview 6.2.1**（本机 `apps/desktop/.venv` 已安装源码；官方仓库 <https://github.com/r0x0r/pywebview>；调研日期 2026-10-13，逐条核对行号）。

决定可行性的关键结论：
- `webview/__init__.py:399-410`：`create_window()` 在 `start()` 之后、且当前线程**不是** `MainThread` 时会立即建窗（`guilib.create_window(window)`）；主线程调用则只登记。
- `webview/util.py:335`：`js_api` 方法在独立 `Thread` 中执行 —— 从 `HostApi` 里建窗天然满足上面的条件，不必另开线程。
- `webview/platforms/cocoa.py:1418-1428`：非 master 窗口走 `AppHelper.callAfter(create)` 派发回 GUI 线程，不阻塞调用方。
- `webview/http.py:39`（`global_server = None`）与 `webview/util.py:75-84`：`http://127.0.0.1:<port>` 不被判为 local url，因此新窗口直接加载我们自己的服务地址，pywebview 不会再起一个内部静态服务。
- `webview/__init__.py:501-509` + `webview/platforms/cocoa.py:1404-1415`：`webview.active_window()` 能定位「发起本次调用的窗口」，多窗口下必须用它替代 `windows[0]`。
- `webview/window.py` 提供 `show()/hide()/restore()/destroy()`，足以实现去重聚焦与子窗口关闭。

方案比较（打开方式放在哪里）：

| 方案 | 做法 | 结论 |
|---|---|---|
| A 插件 manifest 声明 + 卡片右键覆盖（采纳） | `open_mode` 决定默认，右键临时改 | 默认行为可被插件作者定义，用户又不被绑死；三种方式复用同一套桥 |
| B 只做全局设置开关 | 用户在设置里选一种，所有应用统一 | 简单，但无法表达「这个应用适合独立窗口、那个适合内嵌」 |
| C 每个插件用代码自己调宿主桥 | 插件在入口自己调 `open_app` | 行为对用户不可预期，卡片点击语义漂移，且老插件无声明 |

最终选 A：默认值来自插件（数据），覆盖来自用户（交互），宿主只提供能力。

## 被否决的选项

- **子窗口直连插件页 `/apps/<id>/`**：`window.desktop` 由 `front/src/components/plugin-view.tsx` 在 iframe load 后注入，脱离宿主壳只剩静态页，SDK 与权限白名单同时失效。
- **新窗口里不复用壳、另写一套精简页面**：等于把壳的路由、主题、SDK 注入复制一遍，两套 UI 必然漂移。
- **每点一次开一个新窗口**：同一应用反复点击会堆积窗口；改为按 app_id 去重聚焦。
- **每个应用单独起服务/进程**：成本与打包复杂度远超需求，内嵌服务本就同源同端口。
- **`open_mode` 非法值时让 manifest 整体校验失败**：该字段只是展示策略、不是安全边界，一个笔误不该让插件整个装不上；改为宽容回退 `inline` 并记警告，与 `permissions` 的 `unknown_permissions()` 宽容策略一致。
- **右键菜单写在卡片组件内部**：卡片有 `overflow-hidden` 与 hover 变换，菜单必被裁剪；改为壳层单例浮层菜单。
- **`close_current_window` 由前端判断「我是不是子窗口」**：壳在两种窗口里长得一样，靠 hash 判断会被插件的 `navigate()` 误伤；改为建窗时带 `?child=1` 标记 + 后端 `webview.active_window()` 判定。

## 停点判断

- 架构边界变化：无（仍在 `apps/desktop/` 内，不新增模块目录）。
- 数据模型变化：无（不改 `state.json` 结构）。
- API 契约变化：**命中** —— js_api 新增 `open_app` / `close_current_window`；插件 manifest 新增 `open_mode`；`/api/desktop/plugins` 返回体新增 `openMode`。
- 鉴权或权限行为变化：无（插件仍走宿主 SDK 与权限白名单；右键覆盖只影响宿主壳自己的打开动作）。
- 核心资料缺失：不命中（pywebview 源码已核实）。
→ `approval.required: true`，实现前必须获得用户确认。

## 变更点

- `apps/desktop/desktop_app/protocol.py`：`PluginManifest` 新增可选字段 `open_mode`（`inline`/`browser`/`window`），非法值由字段校验器**归一化为 `inline`** 而非报错。
- `apps/desktop/desktop_app/registry.py`：`PluginInfo` 增加 `open_mode`，`to_dict()` 输出 `openMode`。
- 新增 `apps/desktop/desktop_app/windows.py`：`AppWindowManager`，按 app_id 维护子窗口注册表，提供 `open(app_id, url, title, js_api=None)` / `close(window)` / `close_all()` / `is_child(window)`；`create_window` 以参数注入，便于单测用替身。子窗口地址由 `child_url(base_url, app_id)` 生成，形如 `<壳基址>/?child=1#/app/<id>`。
- `apps/desktop/desktop_app/host_api.py`：新增 `open_app(app_id, mode=None)`（mode 为空时取插件的 `open_mode`，再缺省 `inline`；`inline` 不建窗，交回前端）与 `close_current_window()`；`open_file_dialog` 改用 `webview.active_window()`（为空回退 `windows[0]`）。子窗口与主窗口**复用同一个 `HostApi` 实例**，因此插件在子窗口里的 SDK 与权限白名单不变；但 `type=remote` 的插件在 `browser`/`window` 下只开它自己的 `url`，**不注入宿主桥**（`js_api=None`），避免把宿主能力交给外部站点。
- `apps/desktop/desktop_app/main.py`：注入壳基址（dev 为 `http://127.0.0.1:8443`，否则内嵌服务地址）与窗口管理器；master 窗口 `closed` 事件先 `close_all()` 再 `server.stop()`。
- `apps/desktop/front/src/lib/api.ts`：`Plugin` 增加 `openMode: 'inline' | 'browser' | 'window'`。
- `apps/desktop/front/src/components/app-card.tsx`：新增可选 `onContextMenu(x, y)`（右键触发，带上触发点坐标），卡片本身保持无菜单；未传回调时不拦截浏览器默认右键。
- `apps/desktop/front/src/App.tsx`：壳层新增右键浮层菜单（三种方式 + 标出插件默认项）；`openAppByMode(id, mode?)` 统一入口——`inline` 走现有 `navigateTo`，其余调桥并 toast 结果；挂载时补跑一次 hash 解析，使新窗口冷启动直达目标应用；插件清单 `loaded` 前不渲染「未安装」态；子窗口（URL 带 `child=1`）里 Esc/返回改为调 `close_current_window()`。
- `apps/desktop/front/src/vite-env.d.ts`：补 `open_app`、`close_current_window` 类型。
- `apps/desktop/README.md`：契约节补 `open_mode` 与两个新 js_api 方法；`docs/CHANGELOG.md` 同步。
- 测试：`apps/desktop/tests/test_windows.py`（去重/聚焦/close_all/子窗口判定）、`tests/test_protocol.py` 与 `tests/test_registry.py` 补 `open_mode` 用例、`tests/test_host_api.py` 补 `open_app`/`close_current_window` 用例；`tools/harness/verify/2026-10-13-desktop-app-new-window.sh` 另跑一次端到端装配探针（真起内嵌服务 + 真 `main.run()`，只替换 pywebview 窗口层）。

## 验收标准

1. 未声明 `open_mode` 的插件（现有 hello-world / bookmarks-organizer）左键点击行为与现在完全一致：壳内打开。
2. 卡片右键弹出菜单，含「在当前页面 / 在浏览器 / 在新窗口」三项，并标出插件声明的默认项；选「在新窗口」出现新原生窗口，标题为插件名，应用可用且 `window.desktop` 生效。
3. 重复对同一应用执行「在新窗口打开」不开新窗口，已有窗口被置前。
4. 子窗口里 Esc / 返回关闭该子窗口；主窗口 Esc 仍是退出全屏。
5. 关闭主窗口后子窗口全部关闭、内嵌服务停止、进程无残留。
6. 浏览器调试模式（`pnpm dev`，无 `window.pywebview`）：inline 正常，选「浏览器/新窗口」时给出明确 toast 而不是静默失败。
7. `manifest.json` 写 `open_mode: "window"` 的插件点击直接开新窗口；写成非法值时插件仍能加载且按 `inline` 打开。
8. `cd apps/desktop && python -m pytest tests -q` 全绿；`pnpm --dir apps/desktop/front build` 与 `tsc --noEmit` 通过。
