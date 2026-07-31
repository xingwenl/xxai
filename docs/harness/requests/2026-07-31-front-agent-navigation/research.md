# 前端 Agent 页面导航调研记录

## 调研问题

本次需要在 `apps/front` 接入已发布的 `xxai-agent`，让用户通过自然语言打开后台已有页面。重点确认 SDK 的宿主工具调用方式、前端路由导航方式、Embed token 的安全边界，以及如何避免把 `client_secret` 暴露到浏览器。

调研日期：2026-07-31。

## 参考来源

### 来源 1：本仓库 AI Agent SDK 与宿主工具设计

- 链接：`apps/ai-sdk/README.md`、`docs/harness/requests/2026-07-28-agent-sdk-host-tools/research.md`
- 版本：仓库当前 `xxai-agent@0.1.0`；调研日期：2026-07-31。
- 结论：SDK 通过 `createAgentClient` 创建客户端，通过 `registerTool` 注册浏览器宿主函数；后端使用 Client、Agent 和宿主工具三重白名单决定工具是否可调用。有副作用的 `navigation` 工具由后端决定是否需要确认。

### 来源 2：TanStack Router 官方文档

- 链接：https://tanstack.com/router/latest/docs/framework/react/guide/navigation
- 版本或发布日期：当前在线文档；调研日期：2026-07-31。
- 结论：React 应用内导航应使用 Router 提供的 `navigate` 能力，保持路由状态、加载和类型检查一致；不应在应用内部导航中使用任意 URL 的 `window.location`。

### 来源 3：OWASP WebSocket Security Cheat Sheet

- 链接：https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html
- 版本或发布日期：当前在线版本；调研日期：2026-07-31。
- 结论：WebSocket 握手和业务事件都应基于当前主体授权；浏览器不应通过自报身份或能力扩大权限。短期 token 代理必须绑定当前登录态，并由服务端保存的 Embed Client secret 完成签发。

## 方案比较

| 方案 | 做法 | 收益 | 限制 | 结论 |
|---|---|---|---|---|
| A：受保护 token 代理 + SDK 宿主导航 | 后端用当前后台登录态调用现有 Embed token 签发逻辑；前端注册固定内部路由白名单工具 | 不暴露 secret，复用现有三重授权和 SDK 协议；所有后台页面可用 | 需要新增一个后端接口和一层 React bridge | 采用 |
| B：仅在聊天页挂载 SDK | 只在 `/chats` 中初始化 SDK | 改动较少 | 其他页面无法直接使用；后续工具能力难以复用 | 不采用 |
| C：直接用后台 JWT 连接 Agent WebSocket | 前端把现有登录 JWT 直接当 Agent token 使用 | 接入代码最少 | 绕过 Embed token 受众、Client 白名单和宿主工具权限模型 | 不采用 |

## 最终决策

采用方案 A。后端新增受当前后台用户保护的 `/api/v1/embed/agent-token`，只接收可选的最终用户展示信息和固定工具名，服务端使用已有环境配置完成 Embed token 签发；前端在 `AuthenticatedLayout` 全局创建 SDK 客户端，并只注册 `navigate_to_page`。路由白名单由前端代码维护，工具只接受白名单中的内部路径，不接受外部 URL。

## 剩余风险

- 部署环境必须配置 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID`、`EMBED_ORIGIN`，并完成 Agent、Embed Client、`navigate_to_page` 的后台绑定。
- 当前 SDK 的 floating UI 由 Vue 挂载，React 侧需要在 effect 清理阶段调用 `destroy()`，否则可能残留 DOM、事件和 WebSocket。
- Agent 是否会稳定地产生目标工具调用取决于后台 Agent system prompt；前端工具描述和后端策略只能约束执行，不能替代模型配置。
