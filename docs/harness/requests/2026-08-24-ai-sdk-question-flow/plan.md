# 实施计划

## 变更文件

### 后端

- `apps/backend/app/modules/builtin_tool/registry.py`：新增 `ASK_USER_TOOL`（`BuiltinToolDefinition`，name=`ask_user`，executor=`ask_user`），`input_schema` 含 `question`、`description`、`options`（2-4 项）、`allowFreeText`、`requireSelection`。
- `apps/backend/app/modules/gateway/dispatcher.py`：
  - 构造函数新增 `pending_questions: dict[str, asyncio.Future]` 参数；
  - `invoke()` 在 builtin 分支前按 `tool.name == "ask_user"` 拦截；
  - 新增 `_invoke_question_tool()`：参数校验 → `question_id` 生成 → Future 注册 → `question_required` 事件入队 → `wait_for` 600 秒 → 返回 `SimpleNamespace(status="completed", result={"question", "answer"})`；超时与超限（3 次/请求）返回不可用结果。
- `apps/backend/app/modules/gateway/router.py`：
  - 不注入 `ASK_USER_TOOL`：可用性完全由后台 `agent_builtin_tools` 绑定决定（普通内置工具语义）；
  - 连接级新增 `pending_questions`，注入 dispatcher；
  - `_event_to_protocol_payload` 增加 `question_required` 分支；
  - 新增 `_handle_question_answer()` 与 `question_answer` 入站分支；
  - `finally` 清理 `pending_questions` 未完成 Future。
- `apps/backend/app/modules/conversation/runtime.py`：
  - `tool_step_values` 增加 `waiting_question` 状态映射与输出文案（"等待用户选择"）；
  - `build_system_prompt` 追加 `ask_user` 使用说明。

### SDK（apps/ai-sdk）

- `src/core/protocol.ts`：`ProtocolEventType`、事件白名单、`ProtocolPayload` 增加 `question_required`。
- `src/core/types.ts`：新增 `AgentQuestion`、`QuestionAnswer`；`AgentCallbacks` 增加 `onQuestionRequired`。
- `src/core/client.ts`：`question_required` 事件处理、`pendingQuestions` 登记、`answerQuestion()`、断开清理、`question_resolved` 事件。
- `src/core/websocket.ts`：新增 `sendQuestionAnswer()`。
- `src/ui/components/QuestionCard.vue`：选项卡片组件（radio + 自由文本 + 提交 + 超时态）。
- `src/ui/components/ChatWidget.vue`：挂载 `QuestionCard`（参照 `ToolConfirmation`）。

### 测试与文档

- `apps/backend/tests/gateway/`：dispatcher 提问流程、超时、超限、网关 `question_answer` 处理用例。
- `apps/backend/tests/conversation/`：`tool_step_values` 状态映射用例。
- `apps/ai-sdk/src/core/__tests__/`：协议解析、`answerQuestion` 与事件回调用例。
- `docs/harness/requests/2026-08-24-ai-sdk-question-flow/`：本 request 文档（`research.md`、`spec.md`、`plan.md`、`meta.json`）。

## 实施步骤

1. 后端工具定义：注册 `ASK_USER_TOOL`，确认 `bind_tools` 转换路径。
2. 网关协议：`question_required` 出站事件转换 + `pending_questions` 容器 + `_handle_question_answer` + 连接清理。
3. 分发器：`invoke()` 拦截 + `_invoke_question_tool()` 挂起/恢复/超时/次数上限。
4. 启用模型：确认 `ask_user` 仅在后台绑定启用后进入 `runtime_tools`（与 http_get/http_post 一致），移除无条件/能力门控注入。
5. 系统提示词与 loop step：`build_system_prompt` 追加说明；`tool_step_values` 增加 `waiting_question` 状态。
6. SDK 协议与客户端：`protocol.ts`、`types.ts`、`client.ts`、`websocket.ts`。
7. SDK UI：`QuestionCard.vue` 与 `ChatWidget.vue` 挂载。
8. 单测补充（后端 + SDK）。
9. 运行测试与格式化，记录真实验证结果到 `verify.md`。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/gateway tests/conversation -q`：新增用例通过、既有用例不回归。
- `cd apps/ai-sdk && pnpm test`（或仓库既有 SDK 测试命令）：协议与客户端用例通过。
- 手工验证（可选）：本地起后端 + SDK 示例，触发模型调用 `ask_user`，观察事件顺序与卡片交互；验证超时与旧客户端降级路径。

## 回滚说明

- 后端：回滚 `registry.py`、`dispatcher.py`、`router.py`、`runtime.py` 相关改动即可；移除 `ask_user` 注入即恢复原工具集合。
- 网关：删除 `question_answer` 入站分支与 `pending_questions` 容器即恢复原协议。
- SDK：回滚 `protocol.ts`/`types.ts`/`client.ts`/`websocket.ts` 与 `QuestionCard.vue` 挂载点。
- 关注点：`question_required` 事件不可被旧客户端消费，使用该功能的前端必须升级到带问答处理的新 SDK，否则模型会挂起至 600 秒超时。

## 人工确认点

- 必须：API 契约变化（新增出站事件 `question_required`、入站消息 `question_answer`）——已由用户于 2026-08-24 批准（meta.json `approvalRecords`），实现已完成。启用模型调整为后台绑定（用户明确指示，2026-08-24）。
- 无需：架构边界、数据模型、鉴权权限（见 `spec.md` 停点判断）。

## 详细任务清单

### 任务 1：内置工具定义

**文件：**

- 修改：`apps/backend/app/modules/builtin_tool/registry.py`

**内容：**

- 新增 `ASK_USER_TOOL = BuiltinToolDefinition(name="ask_user", executor="ask_user", kind="builtin", side_effect="none", ...)`；
- `input_schema`：`question`（必填 string）、`description`（可选 string）、`options`（必填 array，2-4 项 `{id, label}`）、`allowFreeText`（默认 true）、`requireSelection`（默认 true）；
- 说明文本写入 `description`：仅在需要用户决策时调用，一次一个问题。

### 任务 2：网关出站事件与入站消息

**文件：**

- 修改：`apps/backend/app/modules/gateway/router.py`

**内容：**

- `_event_to_protocol_payload` 增加 `question_required` 分支（`questionId/question/description/options/allowFreeText/expiresAt`）；
- 连接级 `pending_questions: dict[str, asyncio.Future]`，构造 dispatcher 时传入；
- `_handle_question_answer(message, payload, pending_questions)`：校验 `questionId` 为 str、Future 存在且未完成，`set_result({"selectedOptionId": ..., "freeText": ...})`；
- 主循环新增 `question_answer` 分支；
- `finally` 中取消 `pending_questions` 未完成 Future；
- `produce_embed_request` 不注入 `ASK_USER_TOOL`：可用性由后台 `agent_builtin_tools` 绑定决定；`runtime_tools` 直接由 `context.builtin_tools` 等组装。

### 任务 3：分发器挂起/恢复

**文件：**

- 修改：`apps/backend/app/modules/gateway/dispatcher.py`

**内容：**

- `__init__` 新增 `pending_questions` 参数；
- `invoke()`：`if tool.name == "ask_user": return await self._invoke_question_tool(tool, call)`（置于 builtin 分支之前）；
- `_invoke_question_tool()`：jsonschema 校验 → `question_id = f"{request_id}_question_{n}"` → Future 注册 → 事件入队（含 `expires_at = now + 600s`）→ `wait_for` → 返回结果；
- 超时返回 `{"status": "expired", ...}`；提问次数 > 3 返回 `{"status": "unavailable", ...}`；`finally` 中弹出 Future。

### 任务 4：启用模型（后台绑定）

**文件：**

- 修改：`apps/backend/app/modules/gateway/router.py`、`apps/ai-sdk/src/core/websocket.ts`

**内容：**

- SDK auth payload 增加 `capabilities: ["questions"]`；
- 网关不做能力门控注入；`ask_user` 可用性由后台绑定决定（用户明确要求，不要搞特殊）。

### 任务 5：系统提示词与 loop step 状态

**文件：**

- 修改：`apps/backend/app/modules/conversation/runtime.py`

**内容：**

- `build_system_prompt` 追加 `ask_user` 用法与"何时提问"约束（参照 Vercel Search→Ask→Act 策略）；
- `tool_step_values` 状态映射增加 `"waiting_question": "waiting_question"`，输出文案"等待用户选择"。

### 任务 6：SDK 协议与客户端

**文件：**

- 修改：`apps/ai-sdk/src/core/protocol.ts`、`apps/ai-sdk/src/core/types.ts`、`apps/ai-sdk/src/core/client.ts`、`apps/ai-sdk/src/core/websocket.ts`

**内容：**

- `protocol.ts`：事件类型 + 白名单 + payload；
- `types.ts`：`AgentQuestion`、`QuestionAnswer`、`AgentCallbacks.onQuestionRequired`；
- `client.ts`：`question_required` 处理（pending 登记、回调、事件）；`answerQuestion(questionId, answer)`；断开/重置清理；
- `websocket.ts`：`sendQuestionAnswer(questionId, answer)`。

### 任务 7：SDK UI 组件

**文件：**

- 新增：`apps/ai-sdk/src/ui/components/QuestionCard.vue`
- 修改：`apps/ai-sdk/src/ui/components/ChatWidget.vue`

**内容：**

- 选项卡片：标题/描述、radio 选项、`allowFreeText` 时"其他"输入框、提交按钮、`expiresAt` 超时态；
- 提交后调用 `agent.answerQuestion(questionId, {selectedOptionId?, freeText?})`；
- 挂载方式与 `ToolConfirmation` 一致。

### 任务 8：单测

**文件：**

- 新增/修改：`apps/backend/tests/gateway/`、`apps/backend/tests/conversation/`、`apps/ai-sdk/src/core/__tests__/`

**内容：**

- 后端：提问事件发送与 Future 恢复、答案注入结果、超时、超限、无效 `questionId` 忽略、`tool_step_values` 状态映射；
- SDK：`question_required` 解析与回调、`answerQuestion` 发送与 `question_resolved` 事件、pending 清理。
