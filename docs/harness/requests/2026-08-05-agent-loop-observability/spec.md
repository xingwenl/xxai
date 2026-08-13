# AgentLoop 可观测消息与多内容块设计说明

## 目标

- 将聊天消息从单一文本升级为“消息主记录 + 内容块数组 + AgentLoop 过程记录”的结构。
- 支持后续历史会话查看时恢复 Markdown、图片、文件、图表、表格、动作按钮和自定义组件。
- 支持前端在 AI 回复下方展示可折叠的 AgentLoop 摘要，包括思考摘要、工具调用、技能使用和知识库引用。
- 支持 AI 回答按真实执行时间顺序内联展示“思考中、正文、知识库引用、工具调用、继续正文”等过程。
- 知识库引用能说明“引用了哪个知识库、哪一段文字”，工具调用能说明“发送了什么参数、得到了什么结果”。
- 思考中步骤能实时展示模型思考内容（reasoning/thinking），与正文分离，支持折叠查看。
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
  - SDK 在流式过程中维护“正文片段 + 步骤卡片”的按序时间线，事件到达顺序即渲染顺序，正文与引用、工具按真实时机交错。
  - 历史消息或旧消息无时间线时，降级为“过程在上、正文在下”的兼容布局。
  - 知识库引用卡片展示知识库名称与命中片段文字摘要。
  - 工具卡片展示参数摘要（`inputSummary`）与结果摘要（`outputSummary`），长内容使用可折叠容器。
  - “生成回答/思考中”卡片流式展示模型思考内容（通过 `agent_step_delta` 事件），思考与正文分离，支持折叠；普通模型无思考内容时显示占位文案与思考动效。
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
- `thinking_text`：模型思考内容（reasoning/thinking）全文，流式累计后落库；普通模型无思考内容时为 NULL。
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
- `agent_step_delta`：步骤过程的增量安全摘要（第一版用于思考内容增量），payload 含 `stepId`、`stepType`、`field`、`content`。
- `agent_step_completed`：步骤完成或失败。
- `agent_loop_completed`：一次回复过程结束。

兼容策略：

- 现有 `message_started`、`message_delta`、`citation`、`tool_call`、`tool_result`、`message_completed` 保留。
- 新 SDK 优先消费 AgentLoop 事件，旧 SDK 忽略未知事件或继续消费原事件。
- `message_completed.payload` 增加 `contentBlocks`、`loop`、`usage` 等可选字段，不改变既有字段含义。
- `agent_step_started.payload` 兼容性新增可选字段 `inputSummary`，用于工具步骤展示脱敏截断的参数摘要；不改变既有字段含义。
- `agent_step_completed.payload` 的 `outputSummary` 语义从“固定状态文案”扩展为“脱敏截断的结果摘要”，失败与等待确认时仍为状态文案。
- 知识库步骤 `citationRefs` 中的引用对象兼容性新增可选 `knowledgeBase`（id/name/slug）字段，并保留 `text` 命中片段，供前端展示知识库名与段落。
- `agent_step_delta` 只承载面向用户的安全增量（如思考内容），不承载敏感参数原文；旧 SDK 忽略未知事件，不影响既有消息流。

## 原生流式工具循环

- 无工具和有工具场景统一以模型 `astream()` 作为生成入口，不允许因为 Agent 已配置工具就退化为先完整生成、再一次性发送正文。
- 每一轮模型流需要累计增量消息，分别提取正文、工具调用片段和 Token 用量；只有工具名称与参数形成完整调用后才允许执行工具。
- 模型输出正文时立即发送既有 `message_delta`；若该轮只产生工具调用，则不发送空正文或把工具参数混入正文。
- 工具调用开始和完成继续通过既有 `agent_step_started` / `agent_step_completed` 实时投影；工具结果追加到模型消息后，下一轮最终回答继续原生流式输出。
- `message_completed` 只能在全部模型流和工具循环完成后发送，其正文必须等于所有已发送正文 delta 的有序拼接，避免重复或丢字。
- AgentLoop 面向用户只显示安全状态与脱敏摘要。模型原始 chain-of-thought、完整 Prompt 和工具敏感参数不得通过流式事件展示或落库。
- 工具参数摘要限制在 300 字符以内，结果摘要限制在 500 字符以内，只展示截断后的 JSON/文本摘要，不展示完整敏感原文；MCP 结果继续沿用既有脱敏链路。
- 模型思考内容通过 `agent_step_delta` 实时展示，并在 `agent_loop_steps.thinking_text` 落库（用户 2026-08-13 明确要求）；历史会话重载后思考卡片可恢复思考全文。
- 思考内容与正文严格分离：思考落 `thinking_text`，正文落 `content`，两者拼接顺序以步骤 `sequence` 与时间线为准；展示端对超长思考内容折叠与截断。
- 用户取消或连接断开时，应取消当前模型流并阻止尚未开始的后续工具调用；不得在取消后继续发送 delta 或完成事件。
- 流式过程中出现异常时，保留客户端已经接收的正文，结束运行中的 Loop step，将 Loop 标记为失败，并使用既有结构化 `error` 事件报告错误；失败的半成品不作为完整助手消息持久化。
- SDK 继续增量累计 `message_delta` 并容错渲染未闭合 Markdown；每次增量更新后保持消息区域跟随到底部，但用户主动向上滚动时不得强制抢回滚动位置。

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
- 时间线顺序风险：流式过程与完成视图的正文/步骤顺序必须一致，避免出现“早期正文落在后续工具卡片之后”的错位。
- 思考内容兼容风险：不同模型返回思考内容的字段不同（`reasoning_content` / thinking 内容块），部分模型不返回；必须逐块容错提取，普通模型静默降级，不得把思考文本混入正文。
- 数据安全风险：过程落库可能误存敏感数据，必须实现脱敏和字段白名单。
- 存储膨胀风险：AgentLoop step 和内容块可能快速增长，需要限制大小和保留策略。

## 停点判断

- 是否涉及架构边界变化：是。AgentLoop 成为会话运行过程的独立概念。
- 是否涉及数据模型变化：是。需要新增字段和表。
- 是否涉及 API 契约变化：是。初始版本需要新增事件和响应字段；本次增量兼容性新增 `inputSummary`、`knowledgeBase` 等可选字段。
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
- Agent 配置 Skill、MCP 或宿主工具时，工具后的最终回答必须在模型完成前收到至少一个 `message_delta`，不得只在结束时一次性返回完整正文。
- 有工具场景中，AgentLoop 工具状态和回答 delta 必须符合真实执行顺序，所有 delta 拼接结果必须与 `message_completed` 正文一致。
- 流式过程中，正文与步骤卡片按事件到达顺序内联展示；有工具调用的回答应呈现“正文片段 → 工具卡片 → 继续正文”的真实顺序，而非把正文固定放在过程面板之后。
- 知识库引用卡片必须展示知识库名称与命中片段文字摘要（有 `knowledgeBase` 与 `text` 数据时）。
- 工具卡片必须展示参数摘要与结果摘要；长参数/结果可折叠展开，失败时展示错误状态而非结果内容。
- “生成回答/思考中”卡片在有思考内容时流式展示思考文本；思考文本只来自 `agent_step_delta`，不得混入 `message_delta` 正文。
- 普通模型无思考内容时，思考卡片保持“正在理解你的问题并组织回答...”占位与思考动效，不报错、不中断正文流。
- 取消和异常测试必须证明模型流停止、后续工具不再执行、Loop 状态正确结束，且不会持久化失败的半成品助手消息。

## 变更记录

### 2026-08-13 modify：回答过程按时间顺序内联展示并补充引用/工具明细

- 变更原因：当前 SDK 将正文固定渲染在过程折叠面板上方/下方，工具与引用详情缺失，无法让用户看到“思考中 -> 正文 -> 引用知识库 -> 使用了工具 -> 正文”的真实执行顺序，也不知道引用了哪个知识库的哪段文字、工具发送了什么参数得到什么结果。
- 变更内容：
  - SDK 维护“正文片段 + 步骤卡片”按序时间线，按事件到达顺序渲染；历史消息降级为“过程在上、正文在下”兼容布局。
  - 知识库引用对象携带 `knowledgeBase`（id/name/slug）与命中片段，前端展示知识库名 + 段落摘要。
  - 工具步骤 `agent_step_started` 兼容性新增 `inputSummary`（脱敏截断参数摘要），`outputSummary` 从固定文案扩展为脱敏截断的结果摘要。
  - 后端 `retrieve_citations` 按知识库归属为引用附加 `knowledgeBase`；工具运行事件补充真实参数/结果摘要。
- 影响章节：目标、范围、协议事件草案、隐私与安全边界、风险、停点判断、验收标准。
- 是否触发人工确认：是。步骤事件与引用对象为兼容性新增可选字段，仍属于 API 契约变化，进入实现前需人工确认。
- 关联计划更新：已同步更新 `plan.md`，见“2026-08-13 增量计划”。

### 2026-08-13 modify：思考步骤实时展示模型思考内容

- 变更原因：思考中卡片目前只有占位文案“正在理解你的问题并组织回答...”，用户看不到模型真实思考内容。
- 变更内容：
  - 后端 `stream_graph` 逐块提取模型思考文本（`reasoning_content` / thinking 内容块），通过预留的 `agent_step_delta` 事件实时下发（payload：`stepId` + `stepType` + `field: "thinking"` + `content`）。
  - SDK 在“生成回答/思考中”卡片流式追加思考文本，支持折叠；思考与正文严格分离，普通模型无思考内容时静默降级为占位文案。
  - 思考内容实时展示并落库：`agent_loop_steps` 新增 `thinking_text` 字段，`agent_step_delta` 流式下发、步骤完成时累计落库，历史重载后恢复思考全文。
- 影响章节：目标、范围、协议事件草案、隐私与安全边界、风险、验收标准。
- 是否触发人工确认：是。新增 `agent_step_delta` 协议事件类型、新增 `thinking_text` 数据字段（含迁移），并放宽“不落库原始思维链”边界；用户已确认落库，审批通过。
- 关联计划更新：已同步更新 `plan.md`，见“2026-08-13 增量计划”。

### 2026-08-06 fix：修复 pending Message 更新未传递到过程面板

- 变更原因：`ChatMessageList` 中 `pendingAsMessage.loop.steps` 已实时更新，但将 `message.loop` 拆成独立 prop 后，`AgentLoopPanel` 仍可能停留在首次创建的空步骤对象，表现为 `status=running` 且 `steps.length=0`。
- 变更内容：`ChatMessageList -> ChatMessage -> AgentLoopPanel` 全程传递完整 `Message`，由 `AgentLoopPanel` 直接从最新 `props.message.loop` 读取状态和步骤，不再拆分 Loop prop，也不创建局部 Loop computed 投影；历史消息与 pending 消息使用相同路径。
- 影响章节：前端聊天组件、验收标准。
- 是否触发人工确认：否，不改变协议、数据模型、权限或对外 SDK API。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-06 fix：补齐 AgentLoop 首屏反馈

- 变更原因：SDK demo 在首个消息更新与 AgentLoop 事件之间只显示普通输入指示器；当 AgentLoop 事件延迟或旧服务未发送时，生成期间看不到任何过程状态。
- 变更内容：`ChatWidget` 在首个消息更新时创建临时 running Loop，过程步骤到达后替换为真实 Loop；首个真实步骤到达时自动展开详情，用户收起后不因后续步骤更新反复展开。
- 影响章节：前端聊天组件、原生流式工具循环、验收标准。
- 是否触发人工确认：否，不改变协议、数据模型、权限、架构边界或事件字段含义。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-06 fix：优化生成中消息与过程面板展示

- 变更原因：AI 尚未输出正文时仍渲染空内容区域；工具或知识库步骤已经到达后，用户在生成期间无法清晰地按需查看过程，只能在答案完成后再查看。
- 变更内容：空白文本内容块不再渲染，生成中仅展示 AgentLoop 思考区；过程面板在生成期间保持可交互，有步骤时立即允许展开或收起，并在摘要中实时标识工具、技能和知识库过程。
- 补充约束：首个 `message_started` 或正文 delta 到达时，即使 AgentLoop 事件尚未到达，也先展示“思考中”面板；首个真实步骤到达时自动展开过程详情。
- 影响章节：前端聊天组件、验收标准。
- 是否触发人工确认：否，不改变 API、数据模型、权限、架构边界或过程数据的安全摘要规则。
- 关联计划更新：已同步更新 `plan.md`。

补充验收标准：

- pending assistant 正文为空或仅包含空白字符时，不渲染消息内容区域；已有 AgentLoop 时只显示思考区。
- AgentLoop 运行期间一旦收到工具、技能或知识库步骤，用户无需等待最终答案即可展开和收起过程详情。
- 用户在运行期间主动收起过程后，后续步骤更新不得强制重新展开；最终完成后仍可继续查看完整过程。

### 2026-08-06 fix：限制模型客户端重试和流式等待

- 变更原因：上游 502 时 OpenAI 客户端使用默认重试策略，且流式分块等待没有统一上限，底层异常迟迟不抛出，导致 C 端无法收到终止 `error`。
- 变更内容：`ChatOpenAI` 默认请求超时和流式分块超时均为 60 秒，默认 `max_retries=0`；通过 `MODEL_REQUEST_TIMEOUT_SECONDS` 和 `MODEL_MAX_RETRIES` 可调整，Agent 版本 `model_options` 可覆盖默认值。
- 影响章节：错误处理、风险、验收标准。
- 是否触发人工确认：否，不改变协议、数据模型、权限或工具语义。
- 关联计划更新：已同步补充模型客户端超时与重试配置验证。

### 2026-08-06 fix：Agent 上游错误发送到 C 端并结束本轮消息

- 变更原因：模型网关返回 HTTP 502 等 Agent 连接错误时，标准 SSE 只返回固定 `chat failed`，Embed WebSocket 直接透传异常字符串；SDK 收到 `error` 后仍保留 pending assistant，C 端无法得到明确提示且本轮不会结束。
- 变更内容：复用统一 `error` 事件作为当前 request 的终止信号。后端输出 `agent_upstream_unavailable`、用户可展示提示、`retryable` 和脱敏调试详情；SDK 收到后清理 pending assistant 并结束当前 request；失败运行中的 Loop/生成步骤标记为 `failed`，不发送 `message_completed`。
- 方案依据：详见 `research.md` 的“2026-08-06 增量调研：Agent 上游错误的终止事件”，选择不新增 `message_failed` 协议类型。
- 影响章节：协议事件草案、原生流式工具循环、风险、验收标准。
- 是否触发人工确认：否，不新增事件类型、数据模型或权限行为。
- 关联计划更新：已同步更新 `plan.md`。

#### 错误路径审计补充

- 服务端结构化 `error`、WebSocket 连接失败、token 获取失败和协议解析失败均进入 SDK 的统一失败收口；当前存在活跃 request 时必须生成失败助手消息并结束本轮。
- 可恢复的工具执行失败继续使用 `agent_step_completed(status=failed)` 和 `tool_result` 投影，不升级为终止 `error`；只有错误导致整轮无法继续时才发送终止 `error`。
- 握手、鉴权阶段尚未创建聊天 request 的失败只更新连接状态并触发 `onError`，不创建无归属的聊天消息。

补充验收标准：

- Agent 上游返回 502 或连接错误时，SSE/WebSocket 均只发送一个结构化 `error` 终止事件，C 端展示“Agent 连接失败（HTTP 502），本轮对话已结束”或对应状态码提示。
- `error` 事件后不再发送 `message_completed`；SDK 的 pending assistant 不再保持生成中，已有 `onError` 回调仍被触发。
- 失败的运行中 Loop 和模型生成步骤保存为 `failed`，失败半成品不创建完整助手消息。

### 2026-08-05 modify：工具场景使用模型原生流式输出

- 变更原因：现有无工具场景已通过 `astream()` 增量输出，但只要 Agent 配置了工具，运行时就改用 `ainvoke()` 完成整个工具循环，最终回答只能一次性出现，首字延迟和交互感受不符合预期。
- 变更内容：有工具和无工具场景统一采用模型原生流；AgentLoop 实时展示安全状态，最终回答通过既有 `message_delta` 增量输出；补充工具调用片段累计、取消、异常、Markdown 渲染和滚动行为约束。
- 方案确认：用户于 2026-08-05 选择“AgentLoop 状态实时更新，同时最终回答逐字或逐段出现”，并确认采用现有运行时内的原生流式工具循环方案。
- 影响章节：原生流式工具循环、隐私与安全边界、风险、验收标准。
- 是否触发人工确认：否，复用现有事件、数据模型和权限语义，不新增或改变外部 API 契约。
- 关联计划更新：待书面 spec 审阅通过后补充 `plan.md`。

### 2026-08-05 fix：按 chat-glass 设计稿重写 SDK 聊天 UI

- 变更原因：此前实现仍保留旧 `ChatBubble` 气泡外壳，内容块和 AgentLoop 只是嵌套在旧结构中，未达到设计稿要求的组件边界和尺寸一致性。
- 变更内容：废弃旧气泡组件，拆分为 `ChatMessage`、`MessageContent`、Markdown/图片/文件/表格/动作/custom 内容组件和 `TypingIndicator`；移除重复的 `CitationList`，统一由 `AgentLoopPanel` 展示知识库引用；布局、字体、间距、颜色、玻璃效果和阴影直接采用 `chat-glass.html` 的 token。
- 影响章节：前端聊天组件、内容块草案、验收标准。
- 是否触发人工确认：否，仍属于原 request 的前端实现范围，不改变 API、数据模型、权限或事件契约。
- 关联计划更新：已同步更新 `plan.md` 和 `verify.md`。

### 2026-08-05 fix：标准会话响应补齐 Loop 步骤投影

- 变更原因：非流式标准会话接口原先只返回 Loop 摘要，`steps` 被固定为空数组，历史恢复与流式结果的过程明细不一致。
- 变更内容：标准会话接口从已落库的 `agent_loop_runs` / `agent_loop_steps` 读取并返回完整安全摘要；补充技能版本字段。
- 影响章节：范围、协议事件草案、验收标准。
- 是否触发人工确认：否，不新增数据模型或 API 字段，仅补齐既有 `loop.steps` 的实现。
- 关联计划更新：已同步更新 `plan.md` 和 `verify.md`。

### 2026-08-05 fix：实时技能工具数据库并发

- 变更原因：实时 `tool_started` 落库与技能工具查询并发复用同一个 `AsyncSession`，触发 asyncpg `another operation is in progress`。
- 变更内容：运行时事件增加消费确认握手，AgentLoop step 落库完成后才放行技能工具访问仓储，保持实时展示并串行化同一 session 的数据库操作。
- 影响章节：协议事件实现约束、错误处理和验证。
- 是否触发人工确认：否，不改变数据模型和 API 契约。
- 关联计划更新：无需新增迁移。

### 2026-08-05 第 2 次设计确认

- 变更原因：联调发现工具步骤只在最终回答完成后回填，长时间生成期间前端缺少实时反馈。
- 变更内容：要求模型分析、工具开始、工具完成和最终生成状态在真实执行时机通过既有 AgentLoop 事件实时推送；仍不展示或保存原始 chain-of-thought。
- 影响章节：协议事件草案、验收标准。
- 是否触发人工确认：否，复用既有事件和数据模型，不改变 API 字段含义。
- 关联计划更新：运行时采用异步事件回调与队列桥接，不等待最终 `GraphResult` 后再统一回填。

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
