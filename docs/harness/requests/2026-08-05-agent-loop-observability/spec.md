# AgentLoop 可观测消息与多内容块设计说明

## 目标

- 将聊天消息从单一文本升级为“消息主记录 + 内容块数组 + AgentLoop 过程记录”的结构。
- 支持后续历史会话查看时恢复 Markdown、图片、文件、图表、表格、动作按钮和自定义组件。
- 支持前端在 AI 回复下方展示可折叠的 AgentLoop 摘要，包括思考摘要、工具调用、技能使用和知识库引用。
- 确保过程可追溯但不暴露原始思维链和敏感数据。
- 调研结论采用 `research.md` 中的方案 B：`content_blocks JSON + agent_loop_runs/agent_loop_steps 独立表`。

## 范围

- 后端会话消息模型：
  - `conversation_messages` 增加消息状态、文本摘要、内容块 JSON、元数据等字段。
  - 新增 `agent_loop_runs` 表，记录一次用户请求对应的 AgentLoop 生命周期。
  - 新增 `agent_loop_steps` 表，记录知识库检索、技能、工具、模型生成等步骤。
- 后端事件协议：
  - 新增 AgentLoop 生命周期事件。
  - 扩展 `message_completed` 返回内容块和 loop 摘要。
  - 保持现有 `message_delta`、`citation`、`tool_call`、`tool_result` 的兼容行为。
- SDK 类型和状态：
  - `Message.content` 从单一内容对象升级为 `contentBlocks` 或兼容数组。
  - 新增 `AgentLoopRun`、`AgentLoopStep`、`MessageContentBlock` 类型。
  - 新增 loop store 或在 message store 中维护 loop 更新投影。
- 前端聊天组件：
  - 默认展示最终消息内容块。
  - AI 回复下方展示 AgentLoop 折叠摘要。
  - 展开后展示 step 时间线、状态、耗时、引用和错误摘要。
- 展示分层：
  - 聊天前端只消费面向用户的安全摘要。
  - 后台详细审计页面和管理接口不在本 request 实施，但数据字段和权限边界预留。
- 文档：
  - 更新 `docs/design/agent-sdk-flow.md`，补充 AgentLoop 流程、事件契约和隐私边界。

## 非目标

- 不在本 request 中接入第三方 trace 平台作为唯一存储。
- 不落库原始 chain-of-thought。
- 不实现完整事件溯源重放系统。
- 不实现后台 AgentLoop 详细审计页面和管理接口，仅预留数据字段与权限边界。
- 不重新设计模型供应商抽象。
- 不改变现有鉴权、Token 签发或工具权限决策规则。
- 不强制要求第一版支持所有内容块的复杂预览；第一版至少支持 `markdown`、`image`、`file`、`custom` 的稳定降级渲染。

## 数据模型草案

### `conversation_messages`

- `id`：消息主键。
- `conversation_id`：所属会话。
- `role`：消息角色，保留 `user`、`assistant`、`tool`。
- `status`：消息状态，枚举值建议为 `sending`、`streaming`、`completed`、`failed`、`cancelled`。
- `content`：兼容旧逻辑的纯文本内容或摘要。
- `content_blocks`：JSON 数组，保存可渲染内容块。
- 图片、文件等资源内容块保存稳定的 `asset_id`，历史读取时按当前权限生成临时访问地址；不以短期签名 URL 作为唯一持久化依据。
- `citations`：保留兼容；后续可由内容块和 loop step 引用。
- `knowledge_grounded`：保留兼容。
- `tool_call_id`：保留兼容。
- `metadata`：模型、用量、trace、客户端版本等非核心扩展信息。

### `agent_loop_runs`

- `id`：AgentLoop 主键。
- `conversation_id`：所属会话。
- `assistant_message_id`：关联最终助手消息，可为空以支持失败或中断。
- `user_message_id`：触发本次运行的用户消息 ID。
- `request_id`：前后端请求 ID。
- `status`：`running`、`completed`、`failed`、`cancelled`、`waiting_confirmation`。
- `summary`：面向用户的过程摘要。
- `started_at` / `completed_at`：生命周期时间。
- `metadata`：trace ID、模型、运行配置等。

### `agent_loop_steps`

- `id`：步骤主键。
- `loop_run_id`：所属 AgentLoop。
- `sequence`：步骤顺序。
- `step_type`：`thinking`、`knowledge_retrieval`、`skill_instruction`、`skill_tool`、`host_tool`、`mcp_tool`、`model_generation`、`handoff`、`guardrail`。
- `title`：面向用户的短标题。
- `status`：`queued`、`running`、`succeeded`、`failed`、`cancelled`、`waiting_confirmation`。
- `input_summary`：脱敏后的输入摘要。
- `output_summary`：脱敏后的输出摘要。
- `tool_name`：工具名，可为空。
- `skill_name`：技能名，可为空。
- `citation_refs`：关联引用的 JSON 摘要。
- `error`：错误码和错误摘要。
- `started_at` / `completed_at`：步骤时间。
- `metadata`：非敏感扩展字段。
- `attempt`：同一逻辑步骤的重试次数。
- `parent_step_id`：重试、子步骤或派生步骤的父步骤 ID，可为空。

## 内容块草案

`MessageContentBlock` 至少包含公共字段：

```ts
type MessageContentBlock = {
  id: string
  type: string
  status?: 'pending' | 'streaming' | 'completed' | 'failed'
  metadata?: Record<string, unknown>
}
```

第一版支持：

- `text`：普通纯文本。
- `markdown`：正文回答，支持引用标记。
- `image`：`asset_id`、alt、尺寸、标题；读取时生成临时访问地址。
- `file`：`asset_id`、文件名、MIME、大小；读取时生成下载或预览地址。
- `table`：结构化表格数据。
- `chart`：图表类型和结构化数据。
- `actions`：快捷动作按钮。
- `custom`：接入方自定义组件，必须包含 `fallback`。
- `error`：局部内容块错误。

`custom` 内容块必须遵守：

- `componentName` 只能匹配 SDK 侧已注册组件。
- `props` 必须限制大小并经过 JSON 序列化校验。
- 必须提供 `fallback`，未注册组件时降级展示。

## 协议事件草案

新增服务端事件：

- `agent_loop_started`：一次回复过程开始。
- `agent_step_started`：某个步骤开始。
- `agent_step_completed`：步骤完成或失败。
- `agent_loop_completed`：一次回复过程结束。

`agent_step_delta` 作为后续可选扩展预留，第一版不发送。

兼容策略：

- 现有 `message_started`、`message_delta`、`citation`、`tool_call`、`tool_result`、`message_completed` 保留。
- 新 SDK 优先消费 AgentLoop 事件，旧 SDK 忽略未知事件或继续消费原事件。
- `message_completed.payload` 增加 `contentBlocks`、`loop`、`usage` 等可选字段，不改变既有字段含义。
- 第一版不要求发送 `agent_step_delta`；步骤状态和安全摘要在开始、完成或失败时发送即可。

## 隐私与安全边界

- 不落库原始 chain-of-thought。
- 不落库完整 system prompt、浏览器 token、client secret、用户隐私原文和工具敏感入参。
- 工具和技能步骤只保存脱敏后的 `input_summary`、`output_summary`、状态和必要审计字段。
- 知识库引用允许保存标题、来源、片段摘要和 chunk/document 标识，但应遵守知识库权限。
- 后台历史查看必须继续复用现有会话和平台权限边界。

## 风险

- 数据迁移风险：现有 `content` 字段需要兼容历史纯文本消息。
- 协议兼容风险：旧 SDK 不认识新事件，需要确认事件解析是否能忽略未知类型或采用能力协商。
- UI 风险：多内容块和自定义组件可能导致渲染失败，必须有 fallback。
- 协议投影风险：聊天端与未来后台需要不同详情级别，必须区分公开摘要字段和管理员详情字段。
- 数据安全风险：过程落库可能误存敏感数据，必须实现脱敏和字段白名单。
- 存储膨胀风险：AgentLoop step 和内容块可能快速增长，需要限制大小和保留策略。

## 停点判断

- 是否涉及架构边界变化：是。AgentLoop 成为会话运行过程的独立概念。
- 是否涉及数据模型变化：是。需要新增字段和表。
- 是否涉及 API 契约变化：是。需要新增事件和响应字段。
- 是否涉及鉴权或权限行为变化：否。第一版不改变权限规则，但历史查看必须沿用现有权限。
- 结论：进入实现前需人工确认。

## 验收标准

- `research.md` 记录至少 3 个成熟来源、方案比较和最终决策。
- `spec.md` 明确定义消息内容块、AgentLoop run/step、协议事件和隐私边界。
- `plan.md` 明确后端、SDK、前端、迁移、测试和回滚步骤。
- 实现阶段完成后，历史会话接口能返回多内容块消息和 AgentLoop 摘要。
- 实现阶段完成后，前端能展示 Markdown、图片、文件和自定义组件 fallback。
- 实现阶段完成后，AI 回复过程能显示知识库、技能、工具和生成步骤的状态。
- 实现阶段完成后，聊天端只显示脱敏后的 AgentLoop 摘要；后台详细审计能力保持未实现但不阻塞后续扩展。
- 验证阶段必须包含后端测试、SDK 类型/协议测试、前端构建或组件测试。

## 变更记录

### 初始版本

- 时间：2026-08-05
- 变更原因：首次创建 request，承接“优化 agents 和整个对话流程，加入 AgentLoop、多内容块消息和过程可观测”的需求。
- 变更内容：建立数据模型、协议事件、SDK 类型、前端展示和隐私边界的初始设计。
- 影响章节：全部
- 是否触发人工确认：是，涉及数据模型变化和 API 契约变化。

### 2026-08-05 第 1 次设计确认

- 变更原因：根据设计讨论明确 AgentLoop 的用户展示、后台预留和资源持久化边界。
- 变更内容：第一版采用“前端安全摘要 + 后台详细审计预留”；图片和文件保存 `asset_id`；不实现 `agent_step_delta`、后台审计页面和运行重放。
- 影响章节：范围、非目标、数据模型草案、协议事件草案、风险、验收标准。
- 是否触发人工确认：是，仍涉及数据模型变化和 API 契约变化；进入实现前等待人工审批。
- 关联计划更新：已同步更新 `plan.md`。
