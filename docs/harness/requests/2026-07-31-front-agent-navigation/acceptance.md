# 验收记录

验收日期：2026-07-31。

## 结论

功能代码已完成，后端宿主工具 seed、对话/网关回归测试 `23 passed`、Ruff、前端新增代码 ESLint/Prettier 和导航白名单运行验证通过。前端全量 build 仍受现有 agents/knowledge 表单类型错误阻断，因此当前结论为“代码验收通过，仓库全量构建待既有问题修复后复验”。

## 验收项

- 受保护 token 代理：通过。新增 `/api/v1/embed/agent-token`，依赖当前登录用户，secret 只在后端读取。
- 全局 floating 助手：通过代码核对。`AuthenticatedLayout` 挂载 bridge，卸载调用 SDK `destroy()`。
- 内部页面导航：通过。只允许静态白名单页面，使用 TanStack Router，不接受外部 URL、绝对路径或未知页面。
- 副作用确认：通过代码核对。导航请求使用浏览器原生确认框，拒绝不会执行。
- 真实联调：未完成。需要配置 Embed、Agent、宿主工具绑定并在浏览器中验证 WebSocket 和模型工具调用。
- 宿主工具配置：通过。已将 `navigate_to_page` 写入当前配置 Embed Client/Agent 的三重白名单。
- Schema 注册：通过。前端注册 Schema 与后台策略 Schema 已统一，网关日志可明确显示接受或拒绝原因。
- 全量构建：未完成。受既有 agents/knowledge 类型错误影响。

## 剩余风险

- 如果后台没有绑定 `navigate_to_page` 或 token 代理配置不完整，助手会连接失败，但不会阻塞业务页面。
- `VITE_AGENT_PLATFORM_ID`、`VITE_AGENT_ID` 默认值为 `1`，生产环境必须显式配置正确值。
