# 业界调研记录

## 调研问题

本次调研确认：如何在浏览器内的 `ai-sdk` 中自动读取当前页面视口、让模型定位可交互元素并执行点击/输入，同时控制上下文大小、动态页面失效和高风险操作。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及 SDK 架构、WebSocket 宿主工具协议、DOM 语义解析、权限确认和浏览器兼容性。
- 最低调研要求：官方可访问性规范、成熟浏览器自动化案例、浏览器内可复用的开源解析库，并比较至少三种实现路线。

## 参考依据

### 来源 1

- 类型：官方规范
- 名称：WAI-ARIA Authoring Practices Guide
- 链接：https://www.w3.org/WAI/ARIA/apg/
- 版本或发布日期：持续维护，调研日期 2026-08-07
- 核心做法：使用 role、accessible name、状态和键盘交互语义描述控件，而不是依赖视觉坐标或实现细节。
- 对本项目的启发：页面快照应优先输出角色、可访问名称、值和状态；操作前应验证控件仍符合语义。

### 来源 2

- 类型：官方文档
- 名称：Playwright Locators
- 链接：https://playwright.dev/docs/locators
- 版本或发布日期：Playwright 文档，调研日期 2026-08-07
- 核心做法：优先使用 role、label、text 等用户可感知定位方式；定位在操作时重新解析，以适应 DOM 更新；避免脆弱 CSS/XPath。
- 对本项目的启发：SDK 使用临时 `ref` 加快模型交互，但执行前必须重新确认元素存在、可见、可操作，不能把任意 selector 暴露给模型。

### 来源 3

- 类型：成熟开源项目
- 名称：browser-use
- 链接：https://github.com/browser-use/browser-use
- 版本或发布日期：持续维护，调研日期 2026-08-07
- 核心做法：把页面内容压缩成带元素索引的可操作状态，模型通过索引执行点击、输入和滚动，并在页面变化后重新观察。
- 对本项目的启发：采用快照 `snapshotId` 与元素 `ref`，限制只读取当前视口，并把观察与行动拆成独立工具。

### 来源 4

- 类型：成熟开源库
- 名称：dom-accessibility-api、aria-query、tabbable
- 链接：https://github.com/eps1lon/dom-accessibility-api；https://github.com/A11yance/aria-query；https://github.com/focus-trap/tabbable
- 版本或发布日期：持续维护，调研日期 2026-08-07
- 核心做法：分别提供 accessible name/description 计算、ARIA 角色数据和可聚焦元素识别。
- 对本项目的启发：可复用轻量浏览器库完成语义快照，不将 Playwright、Stagehand 或 browser-use 这类 Node/Python 浏览器控制框架打进 SDK。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 原始 HTML/DOM 输出 | 开发快，信息完整 | 上下文大、噪声多，容易受到页面提示注入，难以稳定定位 | 低 |
| 语义快照 + 临时元素引用 | 上下文小，接近用户语义，适应动态 DOM，易接入现有宿主工具确认链路 | 需要实现可见性、ARIA 和引用失效校验 | 高 |
| 截图 + 视觉坐标 | 可覆盖画布等视觉界面 | 坐标漂移，输入/动态页面不稳定，难做权限审计 | 中/低 |
| Playwright/Stagehand 远程控制 | 浏览器自动化能力成熟 | 运行在 Node/远程浏览器，不适合当前页面内 SDK，部署边界不同 | 低 |

## 最终决策

- 选择方案：浏览器内“语义页面快照 + 临时 `ref` + 独立操作工具”。
- 选择原因：复用现有 `ToolRegistry`、WebSocket、确认 UI 和宿主工具审计；优先支持现代 Chrome、Edge、Safari、Firefox；避免向模型暴露任意 selector 或脚本。
- 不选择其他方案的原因：原始 DOM 噪声和安全风险较高；截图不是第一版稳定基础；Playwright 类库运行环境与 SDK 不匹配。
- 对后续 spec、plan 或人工确认的影响：会新增 SDK 内置工具与协议载荷，调整操作风险分类，进入实现前必须完成 API/权限行为人工确认。

## 剩余风险

- 资料时效性：开源库 API 可能变化，实施时需锁定版本并检查产物体积。
- 与本项目上下文的差异：成熟浏览器自动化框架通常拥有浏览器控制端；本方案只运行在宿主页面顶层文档。
- 尚未验证的假设：复杂自定义控件、Shadow DOM、同源 iframe、虚拟列表和遮挡判断需要通过真实页面样例验证。
