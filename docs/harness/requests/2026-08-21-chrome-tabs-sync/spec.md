# 设计说明：读取 Chrome 标签并在应用内整理汇总

## 目标

- 解决什么问题：用户本机 Chrome 收藏的书签（标题、URL、所属文件夹）散落在浏览器收藏夹里，无法在 `ai-base` 桌面应用中统一查看和整理。
- 目标用户/调用方：桌面应用宿主前端「书签整理」页面；Chrome 扩展 popup（数据采集入口）。
- 完成后可验证结果：
  - 用户在 Chrome 扩展 popup 点击「整理书签」后，桌面应用页面能展示去重、按用户书签文件夹（分类）归组的书签汇总；
  - 重启桌面应用后仍可查看最近一次整理快照。
- 引用 `research.md` 关键结论：采用方案 A（Chrome 扩展 + 上报到应用本地 API）；数据源为用户收藏的书签（`chrome.bookmarks`），不再读取当前打开的标签。

## 范围

- 新增 Chrome 扩展子项目 `apps/chrome-extension/`：
  - MV3 `manifest.json`：声明 `bookmarks` 权限（读取书签树）与 `host_permissions`（`http://127.0.0.1:8765/*`）；
  - popup 页面：点击「整理书签」→ `chrome.bookmarks.getTree()` 读取书签树，扁平化为书签列表（含所属文件夹路径）→ POST 到 `http://127.0.0.1:8765/api/desktop/bookmarks/collect` → 展示上报结果（成功数量或失败原因）；
  - 使用方式为「加载已解压的扩展程序」，不上架商店。
- 桌面端新增 `apps/desktop/desktop_app/bookmarks.py`：
  - 过滤内部页面（`chrome://`、`chrome-extension://`、`edge://`、`about:`、`devtools://` 等）；
  - URL 归一化去重（去除 fragment，query 保留）；
  - 按用户书签文件夹路径（`folderPath`）分组，空路径归入「未分类」，组内按标题排序，统计每组数量；
  - 生成汇总快照（总书签数、去重后数量、分组列表）并持久化到 `user_data_dir()/bookmarks-snapshot.json`。
- 桌面端新增 API（注册于 `apps/desktop/desktop_app/server.py`）：
  - `POST /api/desktop/bookmarks/collect`：接收扩展上报的书签数组，返回整理结果并保存快照；
  - `GET /api/desktop/bookmarks/summary`：返回最近一次快照（无快照时 404）。
- 宿主前端：
  - `apps/desktop/front/src/lib/api.ts` 增加对应封装；
  - 新增 `apps/desktop/front/src/components/bookmarks-page.tsx` 页面：展示快照、刷新按钮、扩展安装引导；
  - `apps/desktop/front/src/App.tsx` 增加「书签整理」导航入口。
- 测试：新增 `apps/desktop/tests/test_bookmarks.py`，覆盖过滤、去重、分组与接口。
- 文档：`apps/chrome-extension/README.md` 说明安装步骤；宿主页面内置安装引导。

## 非目标

- 不做 AI 智能摘要/主题聚类：需要 LLM 配置与跨服务接入（`apps/backend` 与桌面端解耦），列为 Phase 2 增强，本次不做。
- 不做书签变化自动同步/持续监听：本次为手动「一键整理」，自动同步列为 Phase 2。
- 不做 Native Messaging 升级（方案 B）：接口与数据模型按可平滑升级方式设计，本次不实现。
- 不接入 `apps/backend`，不新增数据库表（快照用 JSON 文件，避免数据模型变更）。
- 不做 Windows/Linux 专项适配与自动化测试：扩展本身跨平台，本轮在 macOS 验证。
- 不读取当前打开的标签（`chrome.tabs` 相关实现已移除）；若后续需要「打开的标签」整理，另行新增 request。

## 风险

- 桌面应用未启动或端口被占用时，扩展上报失败：扩展 popup 展示明确错误提示，并引导先启动桌面应用。
- `chrome://` 等内部书签 URL：按过滤策略剔除，汇总中不计入。
- 快照文件并发写入：桌面应用为单进程服务，风险低；写入采用临时文件 + rename 的原子替换。
- 新增接口无鉴权：`collect` 接口仅绑定 `127.0.0.1` 且只接收标签元数据（不含登录态/Cookie），数据不落库到公网，风险可控；后续如需收紧可加本机 token。
- 回归风险：`server.py` 与 `App.tsx` 均为增量改动，现有插件体系与设置页不受影响；以现有 pytest 与前端构建作为回归基线。

## 停点判断

- 是否涉及架构边界变化：是（新增浏览器扩展集成面，属于本 request 已确认的方案 A）。
- 是否涉及数据模型变化：否（JSON 快照文件，不新增数据库表；快照结构随数据源调整为书签字段）。
- 是否涉及 API 契约变化：是（新增 `/api/desktop/bookmarks/collect` 与 `/api/desktop/bookmarks/summary`，替换原 tabs 接口）。
- 是否涉及鉴权或权限行为变化：是（扩展声明 `bookmarks` 权限；新增本机上报接口）。
- 结论：进入实现前需人工确认。用户已明确指示数据源为「收藏的书签」，确认方案 A 与「展示载体=桌面应用宿主页面、交互=手动一键整理、MVP 不含 AI 摘要」设计假设后进入实现。

## 验收标准

- `apps/chrome-extension` 在 Chrome「加载已解压」后可读取当前浏览器全部书签；点击「整理书签」后成功上报并显示书签数量；桌面应用未运行时显示可理解的错误提示。
- `POST /api/desktop/bookmarks/collect` 返回分组汇总：同 URL 只保留一条；内部页面不出现；分组按用户文件夹（`folderPath`）归类，含分类名、数量与书签列表。
- 宿主「书签整理」页面展示：总书签数、去重后数量、各分类书签列表；「刷新」可拉取最新快照。
- 重启桌面应用后 `GET /api/desktop/bookmarks/summary` 仍能返回上次快照。
- `cd apps/desktop && poetry run pytest tests/` 全部通过；`pnpm --dir apps/desktop/front build` 构建成功。
- `apps/chrome-extension/README.md` 与宿主页面包含扩展安装步骤说明。

## 变更记录

### 初始版本

- 时间：2026-08-21
- 变更原因：首次创建 request
- 变更内容：确定方案 A（Chrome 扩展 + 本地 API），完成范围、风险、停点判断与验收标准
- 影响章节：全部
- 是否触发人工确认：是（方案 A 已获用户确认；spec 待确认）

### 2026-08-21 第 1 次变更

- 变更原因：用户澄清需求——要整理的是「收藏的书签」，不是当前打开的标签
- 变更内容：数据源从 `chrome.tabs` 改为 `chrome.bookmarks`；扩展权限 `tabs` → `bookmarks`；接口从 `/api/desktop/tabs/*` 替换为 `/api/desktop/bookmarks/*`；快照结构增加 `folderPath` 字段；前端页面与文案同步改为「书签整理」
- 影响章节：目标、范围、非目标、风险、停点判断、验收标准
- 是否触发人工确认：是（用户明确指示数据源为书签，视为需求方向确认；原 tabs 功能移除）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-21 第 2 次变更

- 变更原因：用户要求按自己的书签分类（文件夹）整理，而非按域名分组
- 变更内容：整理维度从「按域名分组」改为「按书签文件夹路径（`folderPath`）分组」，空路径归入「未分类」；快照 `groups` 字段从 `domain` 改为 `folderPath`；扩展 popup 与前端统计文案同步改为「文件夹分类」
- 影响章节：目标、范围、验收标准
- 是否触发人工确认：否（展示维度调整，不改变数据源、接口路径与权限模型；快照 `groups` 结构字段名变化由本变更记录说明）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-21 第 3 次变更

- 变更原因：用户选择提升「书签整理」页可用性，实施搜索、左侧分类导航、复制链接与全部打开
- 变更内容：页面布局改为左侧分类导航 + 右侧书签列表；顶部新增搜索框（匹配标题/URL/分类）；书签行新增「复制链接」；分类头部新增「全部打开」（经 pywebview js_api 调系统默认浏览器打开，避免窗口内 `target=_blank` 不可用问题）；宿主桥 `HostApi` 新增 `open_urls` 方法
- 影响章节：范围、验收标准
- 是否触发人工确认：否（纯 UI/交互增强，不改 HTTP API 路径、数据模型与权限模型；新增宿主桥方法属桌面应用内部能力）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-21 第 4 次变更（fix）

- 变更原因：用户反馈点击书签无法打开链接（静默无反应）
- 变更内容：单条书签由 JS 桥调用改为原生 `<a target="_blank">` 链接（pywebview 默认 `OPEN_EXTERNAL_LINKS_IN_BROWSER=True`，点击自动在系统默认浏览器打开，浏览器调试模式同样可用）；「全部打开」保留宿主桥调用，前端补错误提示与浏览器模式弹窗拦截提示；`open_urls` 对单个链接打开失败容错并返回 `failed` 计数
- 影响章节：范围（交互方式）、验收标准
- 是否触发人工确认：否（bugfix，不改数据模型、HTTP API 路径与权限模型）
- 关联计划更新：无（实施方式在变更记录内说明）

### 2026-08-21 第 5 次变更

- 变更原因：用户要求子应用支持类型区分——三方 zip 应用走 iframe，本项目自己的应用以 React 组件形式存在
- 变更内容：插件 manifest 新增 `type` 字段（`iframe` / `react`，默认 `iframe`，向后兼容）；`PluginInfo` 与插件列表接口带出 `type`；registry 对 `react` 类型跳过 entry 文件校验；宿主按 `type` 分流渲染（iframe 走 `PluginView`，react 走 `ReactAppView` + 组件注册表 `REACT_APPS`）；书签整理改为本项目第一个内置 `react` 应用（`apps/desktop/plugins/bookmarks-organizer`），宿主侧栏快捷入口改为跳转到该应用
- 影响章节：范围、风险、停点判断、验收标准
- 是否触发人工确认：是（插件协议与架构边界变化；用户已在对话中确认该方向）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-21 第 6 次变更（fix）

- 变更原因：用户反馈书签整理迁移为 React 子应用后，打开时头部样式错乱（搜索框与刷新按钮上下堆叠）
- 变更内容：书签页头部改为单行 flex 布局——搜索框 `flex-1`，刷新按钮固定右侧，恢复原 PageHeader 的一行观感
- 影响章节：范围（交互样式）
- 是否触发人工确认：否（纯样式修复）
- 关联计划更新：无
