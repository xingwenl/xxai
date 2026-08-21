# 验证记录：Desktop 基础框架（应用页 / 设置页 + 插件化应用体系）

## 验证信息

- 验证日期：2026-08-20
- 环境：macOS（Apple Silicon）、Python 3.12.4（apps/desktop/.venv）、Node v20.19.5、pnpm 9.15.9
- 工作目录：`apps/desktop/`

## 验证命令与结果

### 1. 单元与接口测试

```bash
poetry run pytest tests/ -q
```

结果：`46 passed`，覆盖：

- `test_protocol.py`：manifest 校验（合法 / 非法 id / entry 穿越 / 未知权限）
- `test_security.py`：zip 安全解压（路径穿越、绝对路径、反斜杠变体、符号链接、条目数/单文件/总大小限制）
- `test_manager.py`：zip 安装（根目录 / 包一层目录）、重复安装 409、非法 manifest 拒绝、卸载、内置不可卸载、启停持久化、异常插件标记
- `test_registry.py`：内置 + 用户合并、内置优先、state 合并、非法内置静默跳过
- `test_server.py`：健康检查、宿主壳首页、插件静态资源、路径穿越 404、安装/启停/卸载往返、内置删除 403、设置接口、代理（非 http 拒绝 + mock 往返）

### 2. 代码规范

```bash
poetry run ruff check desktop_app/ tests/ scripts/
```

结果：`All checks passed!`

### 3. 前端语法与样式编译

```bash
node --check static/js/host.js
node --check static/js/sdk.js
node scripts/build_css.mjs
```

结果：

- 两个 JS 文件语法检查通过。
- `static/css/tailwind.css` 编译成功：25711 字节、458 个候选类名（Tailwind v4.2.2，离线复用 `apps/front` 的 `@tailwindcss/node`）。

### 4. 插件打包脚本

```bash
poetry run python scripts/make_plugin_zip.py
```

结果：生成 `apps/desktop/dist/hello-world-0.1.0.zip`（dist/ 为 gitignore 产物，可随时重新生成）。

### 5. 宿主前端迁移到 React（追加验证，2026-08-20）

```bash
cd apps/desktop/front && pnpm build
cd apps/desktop && node scripts/build_css.mjs && poetry run pytest tests/ -q && poetry run ruff check desktop_app/ tests/ scripts/
```

结果：

- `pnpm build` 成功：产出 `front/dist/index.html` + assets（React 19 + Vite 8 + Tailwind v4，21 个模块）。
- `build_css.mjs` 成功：插件共享样式 9876 字节、184 个候选类名。
- `pytest tests/ -q`：47 passed（新增 `/css/tailwind.css` 共享样式测试；首页断言更新为 React 构建产物标记）。
- `ruff`：通过。
- `vite.config.ts` 已剥离 Figma Make 插件与 `.figma/` 引用；`.figma/make/` 下文件已删除（空目录残留不影响构建）。

### 6. Figma 原版样式恢复 + 真实插件数据接入（追加验证，2026-08-20）

```bash
cd apps/desktop/front && pnpm build
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json
cd apps/desktop && poetry run pytest tests/ -q
cd apps/desktop && poetry run ruff check desktop_app tests scripts
```

结果：

- `pnpm build` 成功：21 个模块，CSS 16.84 kB / JS 228.37 kB。
- `tsc --noEmit` 通过；同时修复了 `desktop-sdk.ts` 中 `denied()` 的类型与运行时错误（未声明权限时 `settings.get` 等调用现在给出明确拒绝错误）。
- `pytest tests/`：47 passed；`ruff`：`All checks passed!`。
- 前端回归 Figma 原版样式基线：`App.tsx` 恢复为原版 1474 行后最小侵入接入插件数据；mock APPS 与内置 JsonFormatter 示例已移除；侧栏新增设置入口；主题与星标偏好持久化。

### 7. 开发环境与持久化修复（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
cd apps/desktop && poetry run pytest tests/ -q && poetry run ruff check desktop_app tests scripts
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过（`vite.config.ts` 代理配置类型检查通过）。
- `pytest tests/`：47 passed；`ruff`：`All checks passed!`。
- `desktop_app.server` 与 `desktop_app.main` 模块导入正常（新增 `__main__` 开发入口与 `DESKTOP_DEV_FRONT` / `DESKTOP_DEBUG` 环境变量分支）。
- `main.py` 已关闭 pywebview 隐私模式（`private_mode=False`），修复主题 / 星标 / 插件存储重启丢失问题。

### 8. 插件视图常规 / 全屏双形态（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 常规形态复用原版毛玻璃返回条（抽出 `PluginTopBar`）；全屏形态为根层 `fixed` 覆盖层（避开 `<main>` 的 transform 包含块），iframe 铺满窗口（`plugin-frame--fullscreen` 去圆角），Esc 可退出；打开 / 返回 / 切换页面自动复位常规形态。
- 全屏切换交互属 GUI 人工验证项（沙箱内无法渲染窗口）。

### 9. 全屏覆盖全部应用视图 + 悬浮导航（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 全屏层 iframe 铺满整窗（无内边距 / 圆角）；顶部返回条与左侧悬浮导航（复用 `Sidebar`）叠加于插件之上，点分类 / 设置退出全屏，切主题与收起侧栏不退出。
- 悬浮导航与 iframe 的叠放层级（iframe < 返回条 < 侧栏）以及交互属 GUI 人工验证项。

### 10. 字体加深 + 毛玻璃更通透（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 毛玻璃透明度整体调低（侧栏 0.5 / 顶部条 0.55 / 统计条 0.45 / toast 0.7 等），`--color-faint` 文字提升为 `--color-mid`，返回条按钮与插件名加粗。
- 视觉效果对比属 GUI 人工验证项（沙箱内无法渲染窗口，截图读取工具当前不可用）。

### 11. 侧边栏折叠按钮内聚化（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 折叠按钮并入侧栏底部（avatar 下方），收起后左边缘细毛玻璃把手（5px，hover 加宽至 10px 并自动展开）；独立悬浮按钮已移除。
- hover / 自动展开交互属 GUI 人工验证项。

### 12. 统一页面头部组件 PageHeader（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 新增 `components/page-header.tsx`，应用页顶栏 / 插件返回条 / 设置页头部三处共用；原 `PluginTopBar` 删除，全屏切换按钮拆为 `FullscreenToggle`；设置页头部改为悬浮毛玻璃（移除不透明背景）。
- 三处头部视觉一致性属 GUI 人工验证项。

### 13. 进入子应用自动全屏 + 全屏沉浸模式（追加验证，2026-08-21）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit -p tsconfig.json && pnpm build
```

结果：

- `tsc --noEmit` 与 `pnpm build` 通过。
- 点击应用卡片（及 SDK `openApp`）自动全屏；全屏下头部与侧栏默认隐藏，顶部横条把手（5px）与左侧竖条把手展开；头部可「收起」或「退出全屏」，`Esc` 退出并复位。
- 沉浸模式交互（把手 hover / 自动展开灵敏度、头部动画）属 GUI 人工验证项。

## 待人工验证步骤（用户在本地执行）

```bash
cd apps/desktop
pnpm --dir apps/desktop/front build
poetry run python -m desktop_app
```

1. 宿主壳显示 Figma 原版启动器 UI（主题色、侧栏、搜索、统计条）；应用页仅展示已启用插件（内置「你好世界」），不再出现 mock 工具。
2. 点击「你好世界」：插件 iframe 就绪后淡入加载（无闪白），SDK 能力按钮（通知、设置、存储、事件、HTTP、平台、日志）均正常。
3. 卡片星标固定后出现在「快速访问」，统计条「收藏工具 / 平台工具」随之更新；刷新/重启后保持。
4. 侧栏「设置」入口进入设置页：上传 `dist/hello-world-0.1.0.zip` 提示已存在（409 预期）；上传其他合法 zip 可安装、启停、卸载；重启后状态保持。
5. 主题切换后重启，主题偏好保持（localStorage）。

### 开发模式验证（2026-08-21 追加）

```bash
cd apps/desktop
poetry run python -m desktop_app.server   # 终端 A：API 服务（127.0.0.1:8765）
pnpm --dir apps/desktop/front dev          # 终端 B：Vite dev server（8443，HMR）
```

- 浏览器打开 `http://localhost:8443`：应用页 / 设置页 / 插件 iframe 均正常（API 与插件资源经代理），改 `front/src/` 样式即时生效。
- `DESKTOP_DEV_FRONT=1 DESKTOP_DEBUG=1 poetry run python -m desktop_app`：真窗口加载 HMR 前端，右键 → 检查元素打开 Web Inspector。
- 端口监听与 Inspector 打开依赖本机 GUI，沙箱内未执行，属本地人工验证项。

### 2026-08-21 轻量变更验证（应用卡片组件抽离）

```bash
cd apps/desktop/front
./node_modules/.bin/tsc --noEmit      # 通过
pnpm --dir apps/desktop/front build   # 通过（26 modules，产物正常输出）
```

- 类型检查与生产构建均通过；`AppCard` / `AppItem` / `StarIcon` 已从 `App.tsx` 移除，无残留引用。
- 卡片视觉（毛玻璃、主题色跟随、hover 光晕、键盘焦点）依赖 GUI 渲染，留待本地人工确认。

## 未验证项与例外

- 真实 HTTP 服务与 GUI 窗口验证未在当前会话执行：沙箱禁止监听本地端口/启动浏览器，且审批服务暂时不可用（503），无法运行 `python -m desktop_app` 与 curl/无头浏览器端到端验证。接口行为已由 `TestClient`（进程内 ASGI）覆盖。
- 插件 iframe 内宿主 SDK 调用（`desktop-ready` 事件、权限裁剪、事件总线跨 iframe 转发）依赖 pywebview 实际渲染，需人工 GUI 验证。
- PyInstaller 打包未重新执行：`desktop.spec` 已加入 `front_dist` datas，打包产物验证留待后续。
