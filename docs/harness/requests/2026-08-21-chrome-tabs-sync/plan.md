# 实施计划：读取 Chrome 标签并在应用内整理汇总

## 变更文件

- 新增 `apps/chrome-extension/manifest.json`：MV3 配置，声明 `bookmarks` 权限与 `http://127.0.0.1:8765/*` host 权限。
- 新增 `apps/chrome-extension/popup.html`、`popup.js`、`popup.css`：popup 界面，读取书签树并上报，展示结果。
- 新增 `apps/chrome-extension/README.md`：扩展安装（加载已解压）与使用说明。
- 删除 `apps/desktop/desktop_app/tabs.py`，新增 `apps/desktop/desktop_app/bookmarks.py`：书签整理逻辑（过滤、去重、分组、快照读写）。
- 修改 `apps/desktop/desktop_app/server.py`：注册 `POST /api/desktop/bookmarks/collect` 与 `GET /api/desktop/bookmarks/summary`，移除原 tabs 接口。
- 删除 `apps/desktop/tests/test_tabs.py`，新增 `apps/desktop/tests/test_bookmarks.py`：整理逻辑与接口测试。
- 修改 `apps/desktop/front/src/lib/api.ts`：书签快照类型与 `getBookmarkSummary` 封装。
- 删除 `apps/desktop/front/src/components/tabs-page.tsx`，新增 `apps/desktop/front/src/components/bookmarks-page.tsx`：书签整理页面（快照展示、刷新、安装引导）。
- 修改 `apps/desktop/front/src/App.tsx`：新增「书签整理」导航入口与页面切换。
- 修改 `apps/desktop/desktop_app/host_api.py`：新增 `open_urls`（系统默认浏览器批量打开 http/https URL）。
- 新增 `apps/desktop/tests/test_host_api.py`：`open_urls` 的协议过滤与计数测试。
- 修改 `apps/desktop/desktop_app/protocol.py`：manifest 新增 `type` 字段（`iframe`/`react`，默认 `iframe`）。
- 修改 `apps/desktop/desktop_app/registry.py`：`PluginInfo` 带出 `type`；`react` 类型跳过 entry 文件校验。
- 新增 `apps/desktop/plugins/bookmarks-organizer/`：内置 react 应用（manifest + icon，无 iframe 页面）。
- 修改 `apps/desktop/front/src/lib/api.ts`：`Plugin` 增加 `type` 字段。
- 新增 `apps/desktop/front/src/lib/react-apps.tsx`：React 子应用注册表（`bookmarks-organizer` → 书签整理组件）。
- 新增 `apps/desktop/front/src/components/react-app-view.tsx`：按注册表渲染 React 子应用。
- 修改 `apps/desktop/front/src/components/bookmarks-page.tsx`：改为 React 子应用组件（去掉自带返回头）。
- 修改 `apps/desktop/front/src/App.tsx`：打开应用按 `type` 分流渲染；侧栏「书签整理」快捷入口跳转到应用。
- 更新 `apps/desktop/tests/`：protocol/registry 对 `type` 的校验与透传测试；server 插件列表包含 react 内置应用。
- 修改 `docs/harness/requests/2026-08-21-chrome-tabs-sync/meta.json`：随阶段推进同步更新。

落实 `research.md` 方案 A 的方式：扩展作为唯一采集通道（官方 `chrome.bookmarks` API），数据经本机 HTTP 上报到桌面应用内嵌 FastAPI，整理与展示全部在 `apps/desktop` 闭环完成，不依赖 `apps/backend`。

## 实施步骤

1. 先写扩展子项目：`manifest.json`（`bookmarks` 权限）→ `popup.html/js/css`（`chrome.bookmarks.getTree()` 扁平化）→ `README.md`，保证扩展可独立加载与调试。
2. 再写桌面端整理逻辑 `bookmarks.py`（纯函数为主，便于单测）：过滤、去重、按用户文件夹（`folderPath`）分组、快照读写；并补 `tests/test_bookmarks.py`。
3. 在 `server.py` 注册两个接口并接线快照存储。
4. 宿主前端：`api.ts` 封装 → `bookmarks-page.tsx` 页面 → `App.tsx` 导航接入。
5. 构建宿主前端并运行桌面端测试。
6. 手动端到端验证：启动桌面应用 → Chrome 加载扩展 → 点击「整理书签」→ 宿主页面查看分组汇总；重启桌面应用验证快照恢复。
7. 更新 request 文档（`verify.md`、`acceptance.md`、`meta.json`）。

## 测试步骤

- 单测：`cd apps/desktop && poetry run pytest tests/test_bookmarks.py`，预期全部通过。
- 回归：`cd apps/desktop && poetry run pytest tests/`，预期现有用例不回归。
- 前端构建：`pnpm --dir apps/desktop/front build`，预期构建成功。
- 手动验证（本机执行）：
  - `cd apps/desktop && poetry run python -m desktop_app` 启动应用；
  - Chrome `chrome://extensions` 开启开发者模式 →「加载已解压的扩展程序」选择 `apps/chrome-extension`；
  - 打开若干收藏的书签，点击扩展 popup「整理书签」，确认返回成功与数量；
  - 宿主页面「书签整理」展示分组汇总；重启应用后快照仍在。

## 回滚说明

- 直接删除新增目录/文件：`apps/chrome-extension/`、`apps/desktop/desktop_app/bookmarks.py`、`apps/desktop/tests/test_bookmarks.py`、`apps/desktop/front/src/components/bookmarks-page.tsx`。
- 对修改文件执行 `git checkout -- apps/desktop/desktop_app/server.py apps/desktop/front/src/lib/api.ts apps/desktop/front/src/App.tsx` 即可恢复。
- 快照文件 `user_data_dir()/bookmarks-snapshot.json` 仅为本功能私有数据，删除不影响其他功能。
- 需要关注的行为：`server.py` 中新增接口在回滚后消失，宿主页面「书签整理」入口同步移除，不影响插件体系与设置页。

## 人工确认点

- 方案 A（Chrome 扩展 + 本地 API）已获用户确认；数据源为用户收藏的书签（用户明确指示，原 tabs 功能移除）。
- 进入实现前需确认 spec 中三项设计假设：展示载体=桌面应用宿主页面；交互=手动一键整理；MVP 不含 AI 摘要（AI 摘要列为 Phase 2）。
