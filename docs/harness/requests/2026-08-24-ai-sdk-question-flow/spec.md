# 设计说明

## 目标

- 为 `apps/ai-sdk` 对话流程增加结构化询问能力：AI 在任务执行中调用 `ask_user` 提出问题（2-4 个选项，可含自由文本），前端渲染选项卡片，用户选择或输入后，AI 基于答案继续执行原任务。
- 影响对象：通过 embed SDK WebSocket 链路（`/ws/agents/{agent_id}`）发起的带工具对话。
- 完成后应产生可验证结果：模型调用 `ask_user` 后前端出现选项卡片；用户选择后模型继续执行；超时、断线、旧客户端场景不卡死；问答记录可在 loop steps 中追溯。
- 调研结论见 `research.md`：参考 Claude Code AskUserQuestion、LangGraph interrupts、Vercel askUser、Spring AI AskUserQuestionTool；采用"内置工具 + 新协议事件 + Future 挂起恢复"方案。

## 范围

### 工具定义（后端）

- `apps/backend/app/modules/builtin_tool/registry.py`：新增 `ASK_USER_TOOL`（`BuiltinToolDefinition`，name=`ask_user`，executor=`ask_user`），`input_schema` 字段：
  - `question`（string，必填）：要问用户的问题；
  - `description`（string，可选）：补充说明或背景；
  - `options`（array，2-4 项，必填）：每项 `{id, label}`；
  - `allowFreeText`（boolean，默认 true）：是否允许用户输入自定义答案；
  - `requireSelection`（boolean，默认 true）：用户是否必须选择一个选项。
- `ask_user` 是普通内置工具，与 `http_get`/`http_post` 一致：仅在后台为 Agent 启用绑定（`agent_builtin_tools`）后进入 `runtime_tools`，后台未启用则不出现（用户明确要求"后台启用才可用，不要搞特殊"）。
- REST 路径（`apps/backend/app/modules/conversation/services.py` 的 `execute_chat`/`stream_chat`）通过 `_rest_runtime_tools` 过滤掉 `ask_user`：REST 无实时问答通道，暴露该工具会导致模型调用后无执行器；此过滤仅解决"启用了但无法交互"的功能缺口，不属于启用门控。

### 系统提示词

- `apps/backend/app/modules/conversation/runtime.py` 的 `build_system_prompt` 追加 `ask_user` 使用说明：仅在需要用户决策时调用（任务范围模糊、方案选择、行动前缺关键信息）；一次一个问题；不要用提问替代一般信息回复。

### 挂起与恢复（后端分发器）

- `apps/backend/app/modules/gateway/dispatcher.py`：
  - `invoke()` 按工具名拦截 `ask_user`，走新增 `_invoke_question_tool()`；
  - `_invoke_question_tool()`：按 `input_schema` 校验参数 → 生成 `question_id`（沿用 call id 模式）→ 在连接级 `pending_questions` 注册 Future → 向 `event_queue` 发送 `question_required` 事件 → `await asyncio.wait_for(future, timeout=600)` → 收到答案后返回 `SimpleNamespace(status="completed", result={"question": ..., "answer": ...})`，经 `ToolMessage` 注入模型继续循环；
  - 超时返回 `SimpleNamespace(status="completed", result={"status": "expired", "message": "问题等待超时..."})`；
  - 单请求提问次数上限 3 次，超限返回"已超出单次任务提问上限，请基于现有信息继续"。

### 网关 WebSocket 协议

- `apps/backend/app/modules/gateway/router.py`：
  - 连接级新增 `pending_questions: dict[str, asyncio.Future]`；
  - `_event_to_protocol_payload` 增加 `question_required` 分支：`{questionId, question, description?, options, allowFreeText, expiresAt?}`；
  - 入站消息新增 `question_answer`（payload：`{questionId, selectedOptionId?, freeText?}`），新增 `_handle_question_answer()`：校验 `questionId` 存在于 `pending_questions` 且 Future 未完成，通过后 `set_result(answer)`；不做审计落库（问题 ID 由当前请求生成、仅当前连接可见）；
  - WebSocket 主循环 `message_type == "question_answer"` 分支；
  - 连接关闭 `finally` 中取消 `pending_questions` 内未完成 Future。

### 能力声明

- SDK auth 消息保留 `capabilities: ["questions"]` 作为协议能力声明；网关不再据此门控注入（启用与否完全由后台绑定决定）。
- 风险提示：旧版 SDK 客户端不理解 `question_required` 事件，若 Agent 已启用 `ask_user` 且旧客户端提问，会等待至 600 秒超时；使用该功能的前端必须升级到带问答处理的新 SDK。

### SDK（apps/ai-sdk）

- `src/core/protocol.ts`：`ProtocolEventType` 与事件白名单增加 `question_required`，`ProtocolPayload` 增加对应 payload 类型；
- `src/core/types.ts`：新增 `AgentQuestion`（`questionId/question/description?/options[{id,label}]/allowFreeText/expiresAt?`）、`QuestionAnswer`（`selectedOptionId?/freeText?`）；`AgentCallbacks` 增加 `onQuestionRequired?`；
- `src/core/client.ts`：处理 `question_required` 事件 → `pendingQuestions` 登记 + `onQuestionRequired` 回调 + `eventEmitter.emit('question_required', ...)`；新增 `answerQuestion(questionId, answer)`（校验 pending → `transport.sendQuestionAnswer` → emit `question_resolved`）；断开/重置时清空 pending questions；
- `src/core/websocket.ts`：新增 `sendQuestionAnswer(questionId, answer)`（参照 `resolveToolCall` 实现）；
- `src/ui/components/QuestionCard.vue`：渲染问题、描述、单选选项（radio）、"其他"自由文本输入（`allowFreeText` 时）、提交按钮与超时态；按 `ToolConfirmation.vue` 的挂载方式接入 `ChatWidget.vue`。

### 落库与可观测（不改数据模型）

- 问答以工具事件经 `tool_started`/`tool_completed` 走既有 loop step 落库链路；`apps/backend/app/modules/conversation/runtime.py` 的 `tool_step_values` 增加 `waiting_question` 状态映射与对应输出文案；
- 不新增 `GraphResult.pending_question_id` / `ChatResponse` 字段：REST 路径不注入 `ask_user`，无消费方；问题 ID 由 `question_required` 事件内联传递（与已确认设计的差异见"变更记录"）。

## 非目标

- 不做 REST `/chat` 路径（含流式 SSE）的询问支持。
- 不改数据库表结构，不新增问答表。
- 不新增跨进程持久化的中断恢复（不引入 LangGraph checkpointer 等价物）。
- 不改动现有 `confirmation_required` 确认机制及其协议。

## 风险

- 回归风险：`dispatcher.invoke` 是网关工具循环唯一入口，新增 `ask_user` 分支不得影响 MCP/宿主/技能工具分发；用现有测试回归验证。
- 兼容性风险：新增协议事件对旧 SDK 不可见，若未做能力协商剔除会导致模型挂起至超时；能力协商必须在 auth 阶段完成。
- 滥用风险：模型过度提问；用系统提示词 + 3 次/请求硬上限兜底。
- 超时/断线风险：沿用确认机制的 600 秒超时、连接关闭清理；超时结果注入模型后由其决定重试或放弃。
- 当前未识别到数据模型与鉴权变化风险。

## 停点判断

- 是否涉及架构边界变化：否，改动在既有对话运行时与网关协议内部完成，不改变模块边界。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：是，新增出站事件 `question_required` 与入站消息 `question_answer`。
- 是否涉及鉴权或权限行为变化：否，`question_answer` 沿用连接层 token 鉴权，不新增权限语义。
- 结论：进入实现前需人工确认（API 契约变化）；设计已获用户在方案确认环节批准（方案 1、多选 + 自由文本）。

## 验收标准

- 模型调用 `ask_user` 后，SDK 前端出现选项卡片（2-4 个选项，`allowFreeText` 时含"其他"输入框），并收到 `question_required` 事件。
- 用户选择选项或输入自由文本后，模型基于答案继续执行任务，最终正常产出 `message_completed`。
- `question_answer` 的 `questionId` 无效或重复提交时被忽略，不破坏模型循环。
- 单请求提问超过 3 次时，后续 `ask_user` 返回不可用结果且模型继续收尾。
- 问题等待超时（600 秒）后，模型收到"等待超时"结果并继续（不永久挂起）。
- `ask_user` 仅在后台启用绑定后出现在模型工具列表；后台未启用时，embed 与 REST 对话均不出现该工具，行为与改动前一致。
- 问答以工具事件记录在 loop steps 中（状态 `waiting_question`，输出含问题与用户答案摘要）。
- 现有 `confirmation_required` 确认流程、MCP/宿主/技能工具调用行为不回归。

## 变更记录

### 初始版本

- 时间：2026-08-24
- 变更原因：首次创建 ai-sdk 对话流程结构化询问能力设计
- 变更内容：确定新增 `ask_user` 内置工具（2-4 选项 + 自由文本）、`question_required`/`question_answer` 协议事件、Future 挂起-恢复、能力协商降级、单请求 3 次提问上限、loop step 落库
- 影响章节：全部
- 是否触发人工确认：是（API 契约变化）

### 2026-08-24 设计细化

- 变更原因：对已确认设计做技术性细化，避免无用契约
- 变更内容：取消 `GraphResult.pending_question_id` 与 `ChatResponse` 新字段——REST 路径不注入 `ask_user`，无消费方；问题 ID 由 `question_required` 事件内联传递，问答记录依赖既有 loop step 机制
- 影响章节：范围（落库与可观测）、验收标准
- 是否触发人工确认：否，未扩大契约与范围；仍待人工确认整体 API 契约变化后进入实现

### 2026-08-24 实现

- 变更原因：用户确认设计并批准 API 契约变化后按 plan.md 完成实现
- 变更内容：注册 `ASK_USER_TOOL`；dispatcher 新增 `_invoke_question_tool`（挂起/恢复、600 秒超时、单请求 3 次上限）；网关新增 `question_required` 出站转换、`question_answer` 入站处理与 `pending_questions` 清理；auth 能力协商（`capabilities: ["questions"]`，不支持则不注入工具）；`tool_started` 携带 `waiting_status`，loop step 状态 `waiting_question`；`build_system_prompt` 仅在 ask_user 可见时追加提问策略；SDK 协议/类型/客户端/`sendQuestionAnswer`/`QuestionCard.vue`/`ChatWidget` 挂载；后端与 SDK 单测
- 影响章节：范围、验收标准
- 是否触发人工确认：是，用户已批准（API 契约变化），进入实现

### 2026-08-24 修复：后台绑定 ask_user 导致同名冲突被剔除

- 变更原因：用户在后台启用 ask_user 生成了 `agent_builtin_tools` 绑定，网关又按客户端能力注入一次，两个同名工具被 `filter_conflicting_runtime_tools` 全部剔除，模型看不到 ask_user
- 变更内容：注入前按工具名去重（`_runtime_tools_with_ask_user`），已绑定同名工具时不重复注入；REST 路径（`execute_chat`/`stream_chat`）通过 `_rest_runtime_tools` 过滤掉 ask_user，保持"REST 不注入"契约
- 影响章节：范围、风险、验收标准
- 是否触发人工确认：否（fix，不扩大契约）

### 2026-08-24 设计调整：启用模型改为后台绑定

- 变更原因：用户明确要求"后台启用才能用这个功能，不要搞特殊"——ask_user 不应作为无条件注入的核心能力，而应与 http_get/http_post 一致，由后台 `agent_builtin_tools` 绑定控制可用性
- 变更内容：移除网关 embed 路径的无条件注入与客户端能力门控（`_runtime_tools_with_ask_user` 与 `supports_questions` 参数删除）；ask_user 仅在后台启用后进入 `runtime_tools`；SDK 保留 `capabilities: ["questions"]` 协议声明但不作为注入门控；REST 路径 `_rest_runtime_tools` 过滤保留（REST 无实时问答通道，属功能缺口兜底，非启用门控）
- 影响章节：范围（工具定义、能力协商→能力声明）、验收标准
- 是否触发人工确认：是，用户本次明确指示（后台启用模型），视同已确认
