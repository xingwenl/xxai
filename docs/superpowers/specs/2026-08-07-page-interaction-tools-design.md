# AI SDK 页面自动发现与基础操作工具设计

本设计为 `apps/ai-sdk` 增加当前宿主页面的自动发现和基础操作能力。完整调研、范围、风险和验收标准见 [Harness request](../../harness/requests/2026-08-07-page-interaction-tools/spec.md)。

## 核心决策

- 采用“语义页面快照 + 临时 `ref` + 独立操作工具”，不把原始 HTML、CSS/XPath、JavaScript 或任意 URL 暴露给模型。
- 第一版只扫描当前顶层文档的当前视口；滚动后重新快照。
- 内置工具为 `page_snapshot`、`page_click`、`page_type`、`page_scroll`、`page_wait`、`page_extract`。
- 复用现有宿主工具注册、WebSocket、确认 UI、审计和大小限制。
- 使用 `dom-accessibility-api`、`aria-query`、`tabbable` 等轻量库辅助计算语义，不引入 Playwright、Stagehand 或 browser-use。

## 快照与执行

快照包含 `snapshotId`、脱敏 URL、标题、视口信息、可见文本和元素数组。元素以临时 `ref` 表示，附带 role、accessible name、值及 disabled/checked/expanded 等状态。点击和输入携带 `snapshotId/ref`，执行前重新校验元素存在、可见、未禁用且语义未发生明显变化；失效时返回 `page_snapshot_stale`，由模型重新读取。

## 风险边界

读取、滚动和等待为无副作用操作；普通输入为 `write`；导航、提交、删除、支付等操作进入现有确认 UI。密码框、文件框、跨域 iframe、Shadow DOM、任意 selector、任意脚本和任意 URL 默认拒绝。页面内容视为不可信输入，不能改变工具权限和系统规则。

## 交付边界

本设计不包含实现代码。进入实现前应基于 request 的 `plan.md` 完成依赖版本锁定、快照/引用状态、协议接入、浏览器集成测试和包体积验证，并再次确认 API 契约与权限行为。
