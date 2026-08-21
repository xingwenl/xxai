# 验证记录：读取 Chrome 标签并在应用内整理汇总

## 验证范围

- Chrome 扩展（`apps/chrome-extension/`）：manifest（`bookmarks` 权限）、popup 脚本语法。
- 桌面端整理逻辑与接口（`bookmarks.py`、`server.py` 新增接口）。
- 宿主前端「书签整理」页面与导航接入。
- 第 2 次变更：分组维度从域名改为用户书签文件夹（`folderPath`），空路径归入「未分类」。
- 第 3 次变更：页面改为左侧分类导航 + 右侧书签列表；顶部搜索（标题/URL/分类）；书签行「复制链接」与「全部打开」（pywebview 宿主桥 `open_urls`）。
- 第 4 次变更（fix）：单条书签改原生 `<a target="_blank">` 打开；「全部打开」保留宿主桥并补充错误提示。
- 第 5 次变更：插件协议新增 `type`（`iframe`/`react`）；书签整理迁移为本项目第一个内置 React 子应用，宿主按类型分流渲染。
- 后端回归与静态检查。

## 实际执行的验证

### 1. 桌面端单测（新增用例）

- 命令：`cd apps/desktop && poetry run pytest tests/test_bookmarks.py -q`
- 结果：`7 passed`（过滤、URL 归一化、去重、按文件夹分组与排序、未分类兜底、快照读写、collect/summary 接口、超大上报拒绝）

### 1.1 宿主桥新增用例

- 命令：`cd apps/desktop && poetry run pytest tests/test_host_api.py -q`
- 结果：`1 passed`（`open_urls` 仅打开 http/https，拒绝 file:/javascript:/非字符串）

### 2. 桌面端全量回归

- 命令：`cd apps/desktop && poetry run pytest tests/ -q`
- 结果：`61 passed`，既有插件体系与接口用例无回归（新增 protocol `type` 校验 3 例、registry react/iframe 校验 2 例）

### 3. Python 静态检查

- 命令：`cd apps/desktop && poetry run ruff check desktop_app tests`
- 结果：`All checks passed!`

### 4. 宿主前端构建（含 TypeScript 编译）

- 命令：`pnpm --dir apps/desktop/front build`
- 结果：`vite build` 成功（25 modules），React 子应用注册表与类型分流编译通过

### 6. 真实内置目录扫描

- 命令：`poetry run python -c "... PluginRegistry().scan() ..."`
- 结果：`bookmarks-organizer: react | builtin: True | error: None`

### 5. 扩展脚本语法与 manifest 校验

- 命令：`node --check apps/chrome-extension/popup.js` + Python JSON 解析 `manifest.json`
- 结果：通过（无输出错误），manifest 为合法 JSON

## 失败项与例外

- 真实端口 HTTP 联调（启动 `desktop_app.server` 监听 127.0.0.1:8765 + curl 模拟扩展上报）未在会话内自动执行：沙箱禁止端口绑定，且审批服务暂时不可用（HTTP 503）。接口行为已由 `fastapi.testclient` 完整覆盖（走同一套 ASGI 应用栈），不等价于真实 socket 联调，需人工补验。
- Chrome 扩展的真实加载（`chrome://extensions` → 加载已解压）与 popup 点击上报无法自动化，需人工在浏览器中执行。
- 宿主「书签整理」页面真实渲染（pywebview 窗口）需人工启动应用确认。

## 验收标准对照

| 验收标准 | 状态 |
|---|---|
| 扩展可加载、读取书签并上报 | 代码完成 + 语法校验通过；真实加载/点击待人工 |
| collect 返回分组汇总（去重、过滤内部页、按用户文件夹分类） | pytest 覆盖通过 |
| 宿主页面支持搜索、左侧分类导航、复制链接、全部打开 | 前端构建通过；交互真实体验待人工 |
| 点击书签标题在系统默认浏览器打开 | 改为原生链接（pywebview 默认外链打开）；真实点击待人工 |
| 插件协议支持 iframe / react 类型区分，书签整理为内置 React 子应用 | pytest 与真实目录扫描通过；宿主渲染待人工 |
| 宿主页面展示统计与分组、刷新可用 | 前端构建通过；真实渲染待人工 |
| 重启后 summary 仍可读取快照 | 快照持久化单测通过 |
| `pytest tests/` 全部通过、前端构建成功 | 已完成 |
| 扩展安装说明文档 | 已提供（README + 页面引导） |
