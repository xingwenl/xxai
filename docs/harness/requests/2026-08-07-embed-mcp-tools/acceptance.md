# Embed 对话接入 MCP 工具验收记录

## 验收结论

代码实现和自动化验证达到本次批准范围：Embed Gateway 会动态合并 Agent 上下文中的 MCP 工具，按工具类型分流；只读 MCP 自动执行，有副作用 MCP 通过 WebSocket 确认事件暂停并在批准/拒绝/过期后恢复原模型循环；SDK 在没有自定义回调时显示确认 UI，有自定义回调时交由宿主接管；MCP 审计与确认支持后台用户和 Embed 最终用户互斥主体。

后端定向测试、SDK 测试/类型检查/构建、bridge lint、迁移 upgrade/downgrade 往返均通过。用户已确认当前对话可以使用真实 MCP 服务。前端全量 build 仍受既有 `src/features/agents/index.tsx` 类型错误阻断，该错误不在本 request 的 bridge 改动中，作为仓库级剩余风险保留。

## 验收状态

- 自动化验收：通过。
- 真实 MCP 可用性验收：用户确认通过。
- 当前 request：`done`，阶段为 `acceptance`。
