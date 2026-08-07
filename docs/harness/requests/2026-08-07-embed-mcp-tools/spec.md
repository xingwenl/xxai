# Embed 对话接入 MCP 工具设计说明

## 目标

让 `apps/ai-sdk` 的 Embed WebSocket 对话使用 Agent 已授权的 MCP 工具。只读工具自动执行；写入、财务、外部调用和导航等有副作用工具必须在 SDK 内置确认界面获得最终用户批准，之后恢复同一次模型工具循环并生成最终回答。

本方案依据 `research.md` 的结论：Gateway 负责统一编排，MCP、Skill 和宿主工具按执行位置分流；人在回路确认必须暂停并恢复原运行；MCP 凭据、校验、执行和审计始终留在后端。

## 调用方与主体

- 调用方：通过 `apps/ai-sdk` 连接 `ai-agent.v1` WebSocket 的 Embed Client。
- 运行主体：Embed token 中的 `platform_end_user_id`。
- 授权边界：工具必须来自当前平台、当前 Agent 已启用绑定、已启用 MCP 服务和 `is_allowed=true` 的工具策略。
- 后台 REST 对话继续使用 `sys_users.id`，不改变已有调用入口。

## 架构与数据流

1. Gateway 认证 Embed token，并通过 `load_runtime_context()` 加载 Agent、知识库、Skill 和 MCP 工具。
2. Gateway 将 MCP、Skill 和当前连接已授权的宿主工具合并为模型工具集合。
3. 工具注册器检查名称冲突；存在冲突的名称全部排除并记录工具类型与来源，其他工具继续运行。
4. 模型发起工具调用后，统一调度器按类型分流：
   - `mcp_tool`：调用 `invoke_tool()` 和 `RepositoryMcpExecutor`；
   - `skill_tool`：调用 Skill Runner 或 Skill instruction loader；
   - `host_tool`：沿用页面函数 Future 与宿主工具审计。
5. MCP `side_effect=none` 时直接执行，并把工具结果作为 ToolMessage 回填模型。
6. MCP 有副作用时创建 MCP audit 和 confirmation，Gateway 发送 `confirmation_required` 并暂停当前工具调用。
7. SDK 显示确认面板；用户批准、拒绝或等待超时后发送或产生决定。
8. Gateway 按 `callId` 找到服务端 MCP confirmation：批准后执行，拒绝或超时则生成未执行的工具结果；随后恢复同一次模型循环。

## 运行时组件

### Gateway 工具注册与分发

- `context.mcp_tools` 必须加入 Embed 模型工具集合。
- 工具集合保留来源元数据，不能再通过“非 Skill 即宿主工具”的隐式判断分流。
- MCP 执行器使用服务端保存的 endpoint 和加密认证头；相关信息不进入 WebSocket 载荷。
- 当前 bridge 的限制性 system prompt 改为通用后台助手约束，实际能力以后端授权工具集合为准。

### MCP 确认协调

- Gateway 为当前连接维护 `callId` 到 MCP confirmation 的映射和等待 Future。
- `callId` 是 WebSocket 公共标识；数据库 `confirmation_id` 不发送给 SDK。
- 单个连接沿用现有单活跃请求约束；同一个 `callId` 的重复决定不得重复执行。
- 用户拒绝时向模型提供“用户拒绝，工具未执行，不得自动重试”的安全结果。
- 十分钟未确认时将 confirmation 和 audit 标记为 `expired`，SDK 面板结束等待。
- WebSocket 断开时取消内存等待，不执行或重试有副作用工具；数据库待确认记录按过期规则收敛。

### SDK 内置确认 UI

- 新增确认面板，展示工具名称、工具类型、副作用等级和服务端脱敏后的参数摘要。
- 提供“允许”和“拒绝”按钮；提交后进入处理中状态并禁止重复操作。
- `financial` 和 `external` 使用更明确的风险文案。
- 未配置 `onConfirmationRequired` 时使用内置 UI。
- 配置 `onConfirmationRequired` 时由宿主完全接管，SDK 不显示默认面板。
- 当前 React navigation bridge 删除 `window.confirm` 回调，使导航和 MCP 使用统一 SDK UI。

## WebSocket 契约

沿用现有事件名并扩展 `confirmation_required` 载荷：

```ts
type ToolConfirmationRequired = {
  callId: string
  name: string
  toolType: 'mcp_tool' | 'host_tool'
  sideEffect: 'navigation' | 'write' | 'financial' | 'external'
  summary: {
    arguments: unknown
  }
  expiresAt?: string
}
```

客户端继续发送：

```ts
type ToolConfirmationResolve = {
  callId: string
  approved: boolean
}
```

新增字段为附加字段，已有 `callId` 和 `name` 保持不变。SDK 不接收 MCP endpoint、认证头、原始敏感参数或数据库 `confirmation_id`。

## 数据模型

修改 `McpToolCallAudit` 和 `McpToolConfirmation`：

- `user_id` 改为可空，继续关联 `sys_users.id`；
- 新增可空 `platform_end_user_id`，关联 `platform_end_users.id`；
- 增加检查约束：`user_id` 与 `platform_end_user_id` 必须且只能填写一个；
- 两个主体字段分别建立索引；
- 所有新增或修改 ORM 字段包含清晰的中文 `comment` 元数据。

REST 对话创建 MCP 审计时填写 `user_id`；Embed Gateway 填写 `platform_end_user_id`。确认查询必须同时校验平台和对应主体，不能只凭 `callId` 或 confirmation 主键访问。

## 错误与安全行为

- 参数不符合 MCP input Schema：不调用远程服务，返回稳定安全错误。
- MCP 远程超时或失败：audit 标记 `failed`，错误脱敏后回填模型；有副作用工具不自动重试。
- 用户拒绝：confirmation 和 audit 标记 `rejected`，模型继续回答。
- 确认超时：confirmation 和 audit 标记 `expired`，不执行工具。
- 工具名称冲突：冲突工具不绑定给模型，记录名称、类型和来源，不采用优先级猜测。
- 参数、结果和日志沿用递归敏感字段脱敏与结果长度限制。
- 浏览器不能提交工具类型来扩大权限；工具类型和执行器由服务端运行时对象决定。

## 范围

### 后端

- 修改 MCP 审计与确认主体模型、迁移、schema、repository 和 service。
- 修改 Gateway 工具集合、统一分发、确认暂停/恢复和协议载荷。
- 保持 REST conversation 的 MCP 行为兼容。
- 增加工具冲突、主体隔离、确认状态和断线测试。

### SDK 与前端

- 扩展 `apps/ai-sdk` 协议类型和客户端确认状态。
- 新增 SDK 内置确认 UI、样式和定向测试。
- 修改当前 React bridge 的 system prompt，并移除自定义 `window.confirm`。

## 非目标

- 不支持浏览器直接连接或执行 MCP 服务。
- 不把 MCP 工具合并进宿主工具策略、token `host_tools` claim 或宿主工具审计表。
- 不修改 MCP 服务管理 API、工具同步与 Agent 绑定 API。
- 不迁移 MCP Python SDK v1 到 v2。
- 不支持用户编辑 MCP 参数；本期只有批准和拒绝。
- 不为重名工具自动改名或增加命名空间。

## 风险

- 数据迁移必须兼容已有 `user_id` 非空记录，并在加约束前完成字段可空调整。
- WebSocket 确认期间断线可能留下待确认记录，必须确保过期后审计状态收敛且绝不自动执行。
- 模型供应商对工具名和 Schema 的限制不同，真实 Agent 模型仍需联调。
- SDK 默认确认 UI 会改变有副作用宿主工具的默认体验，需要验证自定义回调覆盖行为。

## 停点判断

- 架构边界变化：是，Embed Gateway 新增 MCP 工具协调和分发职责。
- 数据模型变化：是，MCP audit/confirmation 增加 Embed 主体并修改非空约束。
- API 契约变化：是，扩展 WebSocket `confirmation_required` 载荷和 SDK 公共类型。
- 鉴权或权限行为变化：是，Embed 最终用户在 Agent MCP 策略范围内获得工具调用能力。
- 人工确认：必须在进入实现前由用户审阅本规格并明确批准。

## 验收标准

### 工具可见性与执行

- Embed 模型能同时看到无冲突的 MCP、Skill 和当前连接宿主工具。
- 只读 MCP 工具通过后端执行，结果回填模型并生成最终回答。
- MCP endpoint 和认证头不进入浏览器、模型提示、事件或日志。
- MCP、Skill、Host Tool 调用分别进入正确执行器。

### 确认与状态

- 有副作用 MCP 工具未经批准不执行。
- 批准后恢复原工具循环并生成最终回答；拒绝后模型明确知道工具未执行。
- 重复批准、重复拒绝、十分钟超时和 WebSocket 断线均不造成重复或延迟执行。
- audit 与 confirmation 对后台用户和 Embed 最终用户实行互斥主体约束和查询隔离。

### SDK UI

- 未配置回调时显示内置确认面板，参数为脱敏摘要，按钮只能提交一次。
- 配置 `onConfirmationRequired` 时不显示默认面板，由宿主接管。
- 导航宿主工具与 MCP 工具均可使用统一确认 UI。
- UI 在桌面和移动宽度无溢出、遮挡或文本截断。

### 工程验证

- Alembic upgrade/downgrade、MCP/Gateway/conversation 后端定向测试通过。
- `apps/ai-sdk` 的 Vitest、typecheck 和 build 通过。
- `apps/front` 定向 lint、typecheck/build 通过，或明确记录与本变更无关的既有失败。
- 使用真实 PostgreSQL、WebSocket、模型和至少一个远程 MCP 工具完成只读、批准、拒绝联调。

## 变更记录

### 2026-08-07 第 1 次实施修正

- 变更原因：实现阶段发现同一请求重复调用同名 MCP 时需要避免 WebSocket `callId` 碰撞；确认消息晚于数据库过期时间时不应把对话升级为异常。
- 变更内容：Gateway 使用请求内 MCP 调用序号生成唯一公共 `callId`；过期确认统一返回 `expired` 工具结果并继续模型循环。
- 影响章节：MCP 确认协调、错误与安全行为、验收标准。
- 是否触发人工确认：否，属于已批准方案内的可靠性修正。
- 关联计划更新：已同步落实于 `plan.md` 的 Gateway 确认恢复步骤。

### 2026-08-07 初始版本

- 变更原因：Embed 浮动对话虽然加载 Agent 上下文，但未把 MCP 工具传给模型。
- 变更内容：确定 Gateway MCP 分流、SDK 内置确认 UI、WebSocket 确认恢复和双主体 MCP 审计方案。
- 影响章节：全部。
- 是否触发人工确认：是，涉及架构、数据模型、WebSocket 契约和权限行为。
