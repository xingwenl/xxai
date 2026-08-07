# Embed 对话接入 MCP 工具设计

## 结论

采用 Gateway 统一编排、按工具类型分流的方案。模型可同时看到 Agent 已授权的 MCP、Skill 和当前连接宿主工具；MCP 始终由后端执行，宿主工具仍由浏览器执行。

## 核心数据流

1. Gateway 加载 Agent 运行时上下文并合并三类工具。
2. 工具名称冲突时排除全部同名工具并记录来源，避免错误路由。
3. 模型调用 MCP 只读工具时，后端执行并把结果回填模型。
4. 模型调用有副作用 MCP 工具时，Gateway 创建审计与确认并暂停当前调用。
5. SDK 默认确认面板展示脱敏参数；宿主配置回调时由宿主接管 UI。
6. 批准、拒绝或超时结果回填原模型上下文，继续生成最终回答。

## 安全与主体

- MCP endpoint、认证头、数据库 confirmation ID 和原始敏感参数不进入浏览器。
- MCP 审计与确认支持 `sys_users` 和 `platform_end_users` 二选一主体，并通过数据库检查约束保证互斥。
- 有副作用工具未经批准不执行，断线和重复决定不触发自动重试。
- MCP、Skill 和宿主工具保留独立执行器与审计边界。

## 正式规格

完整调研、协议、数据模型、错误语义和验收标准见：

- `docs/harness/requests/2026-08-07-embed-mcp-tools/research.md`
- `docs/harness/requests/2026-08-07-embed-mcp-tools/spec.md`
