# 业界调研记录：读取 Chrome 标签并在本应用整理汇总

## 调研问题

- 本次要解决什么问题？
  - 读取用户本机 Chrome 浏览器当前打开的标签（标题、URL 等），在 `ai-base` 应用中做整理汇总（去重、分组、AI 摘要），供用户查看。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 影响数据采集通道的选择（扩展 / CDP / AppleScript / Native Messaging）；
  - 影响新增的 API 契约（标签上报接口、整理汇总接口）；
  - 影响展示载体（桌面应用插件或 Web 管理端）；
  - 影响是否新增浏览器扩展子项目。

## 功能复杂度

- 级别：普通业务功能
- 选择理由：涉及新的外部集成面（浏览器）、新的 API 契约和潜在的数据落库，属于需要比较多种方案的普通业务功能。
- 最低调研要求：至少两个权威/官方来源 + 成熟开源案例，比较两到三种方案。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Chrome Extensions - chrome.tabs API
- 链接：https://developer.chrome.com/docs/extensions/reference/api/tabs
- 版本或发布日期：Manifest V3，持续维护（抓取镜像页 2026-08-21）
- 调研日期：2026-08-21
- 核心做法：扩展声明 `tabs` 权限后，可通过 `chrome.tabs.query()` 读取所有标签的 `url`、`title`、`favIconUrl`、`active`、`pinned` 等属性；不声明 `tabs` 权限时拿不到 url/title/favIconUrl。
- 对本项目的启发：读取真实标签的首选通道是 Chrome 扩展，权限模型清晰，且能读到用户日常浏览器的真实标签。

### 来源 2

- 类型：官方文档
- 名称：Chrome for Developers - Remote debugging port（Chrome 136 变更）
- 链接：https://developer.chrome.com/blog/remote-debugging-port
- 版本或发布日期：Chrome 136，2025-04 前后生效
- 调研日期：2026-08-21
- 核心做法：自 Chrome 136 起，对默认 user-data-dir 启动的 Chrome 传 `--remote-debugging-port` / `--remote-debugging-pipe` 不再生效（安全原因）；官方建议改用自定义 `user-data-dir` 或 Chrome for Testing；较新版本可在 `chrome://inspect/#remote-debugging` 中由用户手动为当前实例开启浏览器级远程调试。
- 对本项目的启发：依赖 CDP 直连日常浏览器的旧方案已不可行；若走 CDP，只能读隔离 Profile（非用户日常标签）或依赖用户手动开启调试权限，体验差。

### 来源 3

- 类型：生产实践 / 方案对比
- 名称：Panerelay - 对比 AI Agent 接入现有浏览器的不同方式
- 链接：https://f-loat.github.io/panerelay/zh-CN/compare/
- 版本或发布日期：核对于 2026-08-11
- 调研日期：2026-08-21
- 核心做法：对比了扩展授权类（Panerelay、Playwright Extension）、CDP 原生、托管/隔离浏览器三类路线；结论是"复用日常已登录浏览器 + 标签级授权"场景下，扩展 + 本地桥接是主流，CDP 只适合调试与底层自定义集成。
- 对本项目的启发：业界成熟的"读用户真实标签"模式 = Chrome 扩展 + 本地通道（daemon / native host / localhost API），与本项目桌面应用形态天然契合。

### 来源 4

- 类型：成熟开源项目
- 名称：Tencent/BrowserSkill（bsk：CLI + daemon + Chrome 扩展）
- 链接：https://github.com/Tencent/BrowserSkill
- 版本或发布日期：2026 活跃维护
- 调研日期：2026-08-21
- 核心做法：浏览器侧用扩展提供标签/会话能力，CLI/daemon 在本地消费，borrow/return 机制避免打断用户日常窗口。
- 对本项目的启发：验证了"扩展读取 + 本地服务整理"的工程形态可落地、可长期维护。

### 来源 5

- 类型：官方文档
- 名称：Chrome Extensions - Native messaging；MDN - runtime.connectNative()
- 链接：https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
- 版本或发布日期：持续维护
- 调研日期：2026-08-21
- 核心做法：扩展可通过 `chrome.runtime.connectNative()` / `sendNativeMessage()` 与注册在系统中的本地程序通信（标准输入/输出 JSON 消息）；需在 OS 侧注册 native messaging host manifest。
- 对本项目的启发：若要求"扩展与桌面应用直连、不走 HTTP 端口"，Native Messaging 是官方通道；代价是安装/注册流程更重。

### 来源 6

- 类型：生产实践 / 社区方案
- 名称：AppleScript 读取 Chrome 标签（Stack Exchange、mcp-browser-tabs 等）
- 链接：https://superuser.com/questions/1009213/ ；https://github.com/kazuph/mcp-browser-tabs
- 版本或发布日期：2025-01 前后
- 调研日期：2026-08-21
- 核心做法：macOS 下 `osascript` 用 `tell application "Google Chrome"` 遍历每个 window 的 tab，取 `title`/`URL`；需要用户授予 Chrome 自动化（Automation）权限。
- 对本项目的启发：macOS-only 的最轻量备选，适合快速原型，不适合跨平台产品。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. Chrome 扩展 + 上报到应用本地 API | 官方 `chrome.tabs` API；能读用户日常浏览器真实标签；数据本地闭环；实现成本适中；扩展可"加载已解压"个人使用 | 需要用户安装扩展；桌面应用需在运行才能接收上报 | 高：与 `apps/desktop` 内嵌 FastAPI 天然契合 |
| B. Chrome 扩展 + Native Messaging | 官方通道直连桌面应用，无 HTTP 端口/跨域问题；进程级隔离 | 需在 OS 注册 native host manifest，安装/打包流程重；跨平台需分别实现 | 中高：比 A 稳但成本高，可后续升级 |
| C. CDP 远程调试（localhost:9222/json） | 无需扩展；可进一步做页面级自动化 | Chrome 136 起默认 Profile 无法开调试端口；隔离 Profile 读不到用户日常标签；无标签级授权 | 低：只适合调试/自动化场景 |
| D. macOS AppleScript/JXA | 无需扩展，实现最快 | 仅 macOS；需自动化权限弹窗；脆、慢，跨平台不可用 | 低-中：可做原型验证，不作为正式方案 |

## 最终决策

- 选择方案：A（Chrome 扩展 + 上报到应用本地 API），预留向 B（Native Messaging）平滑升级的接口抽象。
- 选择原因：唯一能稳定读取用户日常浏览器真实标签的官方通道；与 `apps/desktop`（pywebview + FastAPI 宿主）集成成本最低；数据不出本机，隐私风险可控。
- 不选择其他方案的原因：
  - C：Chrome 136 后默认 Profile 调试端口失效，且无标签级授权，不符合"整理日常标签"目标。
  - D：仅 macOS，且依赖 TCC 权限与 AppleScript 兼容性，不适合作为产品级方案。
  - B：功能等价但安装/注册复杂度明显更高，作为 A 的后置升级项更合理。
- 对后续 spec、plan 或人工确认的影响：本需求新增外部集成面（浏览器扩展）、新 API 契约（标签上报/整理接口）与可能的标签数据落库，触发人工确认，须在方案与用户确认后再进入 spec。

## 剩余风险

- 资料时效性：Chrome 权限模型与扩展规范迭代较快，`tabs` 权限与 MV3 限制需在实现阶段用实际浏览器再验证。
- 与本项目上下文的差异：本仓库尚无扩展代码与标签数据模型，spec 阶段需确认展示载体（桌面应用插件 vs Web 管理端）与整理能力边界（仅去重分组 vs AI 摘要）。
- 尚未验证的假设：扩展向 `http://localhost:8765` 上报在桌面应用运行时可稳定连通；标签整理的后端 AI 能力复用 `apps/backend` 现有 LangChain/Embedding 栈的可行性尚未实现验证。
