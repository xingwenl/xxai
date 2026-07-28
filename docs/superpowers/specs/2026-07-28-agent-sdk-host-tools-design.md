# Phase 2B 宿主页面工具设计

## 结论

采用后端授权、SDK 在宿主页面执行的方案。工具可调用集合为：

`token 允许工具 ∩ Agent 发布策略 ∩ 当前页面已注册工具`

后端保存策略、绑定和独立调用审计；SDK 只执行显式注册且 Schema 一致的函数。MCP 工具继续使用现有独立模型和审计链。

## 调用流程

1. 平台管理员配置工具 Schema、副作用类型、确认策略，并绑定 Agent 与 Embed Client。
2. Token exchange 将页面请求的工具名称与 Client 白名单求交，写入 `host_tools` claim。
3. SDK 通过 `host_tools_register` 声明当前页面能力，后端再次与 Agent 策略和 token claim 求交。
4. Agent Runtime 绑定授权工具描述；模型产生工具调用后，网关创建唯一 `callId` 并进入确认或执行状态。
5. SDK 对参数做 Draft 2020-12 校验；需要确认的工具等待最终用户批准，再执行注册函数。
6. SDK 回传结果或错误；后端使用条件状态更新记录终态，重复消息只返回已有状态，不重复执行。

## 安全边界

- 页面声明不能扩大后端白名单。
- 后端不执行浏览器脚本、任意 DOM 操作或 URL 导航。
- 有副作用工具默认确认；断线不自动重试。
- 参数、结果和日志均做大小限制与敏感字段过滤。

详细范围、风险、验收标准和实施步骤见：

- `docs/harness/requests/2026-07-28-agent-sdk-host-tools/spec.md`
- `docs/harness/requests/2026-07-28-agent-sdk-host-tools/plan.md`
