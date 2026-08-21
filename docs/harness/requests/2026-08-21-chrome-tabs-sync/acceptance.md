# 验收记录：读取 Chrome 标签并在应用内整理汇总

## 验收结论

- 自动化验收项全部通过：桌面端 54 个测试、ruff 静态检查、宿主前端构建、扩展脚本语法校验。
- 端到端人工联调项（真实端口上报、Chrome 扩展加载与点击、宿主页面渲染）尚未执行，当前不标记为 `done`，等待用户按下方步骤补验。

## 变更文件

- 新增：`apps/chrome-extension/`（manifest.json、popup.html/js/css、README.md，`bookmarks` 权限）
- 新增：`apps/desktop/desktop_app/bookmarks.py`、`apps/desktop/tests/test_bookmarks.py`
- 修改：`apps/desktop/desktop_app/server.py`（新增两个接口）
- 修改：`apps/desktop/front/src/lib/api.ts`、新增 `apps/desktop/front/src/components/bookmarks-page.tsx`、修改 `apps/desktop/front/src/App.tsx`
- 修改：`apps/desktop/desktop_app/host_api.py`（新增 `open_urls`）、新增 `apps/desktop/tests/test_host_api.py`
- 修改：`apps/desktop/desktop_app/protocol.py`、`apps/desktop/desktop_app/registry.py`（manifest `type` 字段）
- 新增：`apps/desktop/plugins/bookmarks-organizer/`（内置 React 应用）、`apps/desktop/front/src/lib/react-apps.tsx`、`apps/desktop/front/src/components/react-app-view.tsx`
- 修改：`apps/desktop/front/src/App.tsx`（按 `type` 分流渲染、侧栏快捷跳转）、`bookmarks-page.tsx`（改为子应用组件）
- 删除：原 tabs 实现（`tabs.py`、`test_tabs.py`、`tabs-page.tsx`），数据源改为书签
- 文档：本 request 的 research/spec/plan/verify

## 剩余风险

- Chrome 权限模型与 MV3 规范迭代较快，`bookmarks` 权限与 `host_permissions` 需在用户实际浏览器版本验证。
- 端口 8765 被占用或桌面应用未启动时扩展会上报失败（popup 已有错误提示，但未做端口自动探测）。
- 仅 macOS 本地验证，Windows/Linux 行为未验证。
- 快照为单文件 JSON，多人/多实例场景未设计。

## 人工回归要求（等待用户执行）

1. `cd apps/desktop && poetry run python -m desktop_app` 启动桌面应用。
2. Chrome 打开 `chrome://extensions`，开启开发者模式，选择「加载已解压的扩展程序」加载 `apps/chrome-extension/`。
3. 打开若干收藏的书签，点击工具栏「书签整理助手」→「整理书签」，确认 popup 显示成功与数量。
4. 在桌面应用左侧导航进入「书签整理」，确认按你自己的文件夹分类展示（如「书签栏/开发」），统计卡片与书签条目正确；重启应用后快照仍可查看。
5. 体验增强项：顶部搜索（标题/URL/分类）；左侧分类导航点击切换；书签行「复制链接」；分类卡片「全部打开」在系统默认浏览器打开该分类全部书签。
6. 打开链接验证：点击单条书签标题应在系统默认浏览器打开；「全部打开」批量打开并在异常时给出提示。
7. 子应用类型验证：应用列表出现「书签整理」卡片（React 类型），点击后以宿主组件形态打开（非 iframe）；三方 zip 插件（如 hello-world）仍以 iframe 打开；侧栏「书签整理」快捷入口可直达。

## 下一步

- 用户完成上述人工联调并反馈结果后，更新本记录并同步 `meta.json`（phase → acceptance，status → done）。
