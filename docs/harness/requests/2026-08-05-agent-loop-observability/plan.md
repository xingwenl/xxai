# AgentLoop 可观测消息与多内容块实施计划

## 变更文件

- `docs/design/agent-sdk-flow.md`：补充 AgentLoop 流程、事件顺序、兼容策略和隐私边界。
- `apps/backend/app/modules/conversation/models.py`：扩展消息模型并新增 AgentLoop run/step 模型；所有新增字段必须包含中文 `comment`。
- `apps/backend/app/modules/conversation/schemas.py`：新增内容块、AgentLoop、事件 payload 的 Pydantic schema。
- `apps/backend/app/modules/conversation/repositories.py`：新增消息内容块保存、AgentLoop run/step 创建和更新方法。
- `apps/backend/app/modules/conversation/runtime.py`：在知识库检索、技能/工具调用、模型生成阶段产出 loop step 摘要。
- `apps/backend/app/modules/conversation/router.py`：SSE 聊天接口输出 AgentLoop 事件和最终 `contentBlocks`。
- `apps/backend/app/modules/gateway/runtime.py` 与 `apps/backend/app/modules/gateway/router.py`：WebSocket 网关输出同样的 AgentLoop 事件。
- `apps/ai-sdk/src/core/types.ts`：新增 `MessageContentBlock`、`AgentLoopRun`、`AgentLoopStep` 类型。
- `apps/ai-sdk/src/core/protocol.ts`：新增协议事件类型和 payload 校验。
- `apps/ai-sdk/src/core/client.ts`：聚合 loop 事件、内容块和最终消息状态。
- `apps/ai-sdk/src/core/message-store.ts`：支持更新消息内容块和 loop 投影。
- `apps/ai-sdk/src/ui/components/*`：新增内容块渲染器和 AgentLoop 折叠过程面板。
- `apps/ai-sdk/src/ui/components/ChatMessage.vue`：替换旧 `ChatBubble`，承载用户消息、助手消息、内容块和 AgentLoop。
- `apps/ai-sdk/src/ui/components/MarkdownContent.vue`、`ImageContent.vue`、`FileContent.vue`、`TableContent.vue`、`ActionsContent.vue`、`CustomContent.vue`、`TypingIndicator.vue`：拆分独立内容渲染和输入中状态组件。
- `apps/ai-sdk/design/chat-glass.html`：根据真实组件状态更新设计稿或保留为样例。
- 数据库迁移文件：新增表和字段，保证旧消息可读。
- 测试文件：补充后端 schema/repository/runtime 测试、SDK protocol/client 测试和 UI 渲染测试。

## 实施步骤

1. 更新设计文档
   - 在 `docs/design/agent-sdk-flow.md` 增加 AgentLoop 章节。
   - 明确新事件与既有事件的顺序关系。
   - 明确不落库原始思维链和敏感参数。

2. 后端数据模型和迁移
   - 给 `conversation_messages` 增加 `status`、`content_blocks`、`metadata` 等字段。
   - 新增 `agent_loop_runs` 和 `agent_loop_steps`。
   - 为新增字段补充中文 `comment`。
   - 迁移旧数据：旧 `content` 转成一个 `markdown` 或 `text` 内容块。
   - 图片、文件内容块保存 `asset_id` 等稳定引用，不将临时签名 URL 作为唯一持久化数据。
   - 为 AgentLoop 步骤预留 `attempt`、`parent_step_id`、技能版本和工具调用 ID，支持后续详细审计扩展。

3. 后端 schema 与 repository
   - 定义内容块 schema、AgentLoop run/step schema。
   - 新增创建 loop、追加 step、完成 step、完成 loop 的仓储方法。
   - 增加大小限制和脱敏入口，避免任意大 JSON 或敏感内容落库。

4. 后端运行时事件
   - 用户消息进入后创建 `agent_loop_started`。
   - 知识库检索前后输出 `knowledge_retrieval` step。
   - skill instruction 注入或 skill tool 执行输出对应 step。
   - host tool / mcp tool 调用输出开始、等待确认、成功、失败状态。
   - 模型最终生成输出 `model_generation` step。
   - 完成后写入 assistant message 的 `content_blocks` 和 loop summary。
   - 第一版只在步骤开始、完成、失败或等待确认时发送状态事件，不发送逐摘要增量事件。
   - `run_graph` 通过异步回调报告工具开始和完成，`stream_graph` 使用事件队列在模型任务运行期间即时向上游产出，禁止等待最终回答后统一回填。
   - 标准后台 SSE 的 MCP/技能工具分支必须复用同一套实时事件桥接，不能在路由层等待 `execute_chat` 完成后再一次性补发步骤。

5. SDK 协议和状态
   - 扩展 `ProtocolEventType`。
   - 新增 AgentLoop 类型。
   - 在 `AgentClient` 中按 `requestId` 聚合 loop 事件。
   - `message_completed` 时把 `contentBlocks` 和 loop 挂到 assistant message。
   - 保持旧回调 `onMessage`、`onToolCall`、`onToolResult` 可用。
   - 协议解析遇到未知事件时忽略该事件并继续处理同一请求，避免旧 SDK 因新增 AgentLoop 事件中断消息流。

6. 前端聊天 UI
   - 建立 `MessageContent` 分发器及独立内容块组件。
   - 废弃旧 `ChatBubble` 普通气泡结构，使用 `ChatMessage` 作为消息边界。
   - 建立 `AgentLoopPanel`。
   - Markdown、图片、文件、自定义组件 fallback 作为第一版必达。
   - 图表、表格、动作按钮按 schema 支持最小展示。
   - 前端只展示脱敏后的安全摘要；后台详细审计页面和管理接口本期不实施。

7. 测试和验证
   - 后端测试覆盖模型迁移、schema 校验、loop step 写入和事件输出。
   - SDK 测试覆盖未知事件兼容、新事件解析、loop 聚合、message content blocks。
   - UI 测试覆盖内容块渲染和 loop 面板状态。
   - 标准会话非流式接口复用已落库的 Loop run/step，避免最终响应丢失步骤明细。
   - 增加标准后台 SSE 工具实时性回归测试和 Vue UI 内容块/Loop 面板测试。
   - 更新 `verify.md` 记录真实命令和结果。

8. 验收和归档
   - 对照 `spec.md` 验收标准逐项核对。
   - 在 `acceptance.md` 记录剩余风险和可合并结论。

## 测试步骤

- 后端：

```bash
cd apps/backend
poetry run pytest tests/conversation tests/gateway -q
```

- SDK：

```bash
cd apps/ai-sdk
npm run test -- --run
npm run type-check
npm run build
```

- 仓库检查：

```bash
git diff --check
```

## 回滚说明

- 若实现后需要回滚，优先回滚后端迁移、模型、schema、runtime、gateway、SDK 和 UI 相关提交。
- 数据库回滚前必须确认是否已有新 `content_blocks` 或 `agent_loop_*` 数据写入生产环境。
- 前端可通过能力协商或配置临时关闭 AgentLoop 面板，只展示传统文本消息。
- SDK 可保留对旧 `content` 字段的读取作为降级路径。

## 人工确认点

- 进入实现前必须确认：是否接受新增 `content_blocks` 字段和 `agent_loop_runs` / `agent_loop_steps` 两张表。
- 进入实现前必须确认：是否接受新增 WebSocket/SSE 事件 `agent_loop_started`、`agent_step_started`、`agent_step_completed`、`agent_loop_completed`，且第一版不发送 `agent_step_delta`。
- 进入实现前必须确认：是否接受第一版不落库原始 chain-of-thought，只保存可展示过程摘要。
- 进入实现前必须确认：是否接受第一版以 `markdown`、`image`、`file`、`custom fallback` 为必达内容块，图表/表格/动作按钮做基础 schema 和最小渲染。

## 2026-08-05 增量计划：工具场景原生流式输出

### 变更范围

- `apps/backend/app/modules/conversation/runtime.py`：把有工具场景从 `ainvoke()` 批处理改为 `astream()` 原生流式工具循环，累计正文、工具调用片段和 Token 用量。
- `apps/backend/tests/conversation/test_runtime.py`：覆盖工具调用前后事件顺序、最终回答多 delta、delta 拼接、用量和用户确认中断。
- `apps/ai-sdk/src/ui/components/ChatMessageList.vue`：仅在用户停留于消息底部附近时跟随流式内容，避免用户上滚阅读时被强制拉回。
- SDK UI 测试：若现有测试工具支持组件挂载，则补充自动滚动判断；否则以类型检查、构建和纯函数单元测试作为最小证据，并在 `verify.md` 记录限制。

### 实施步骤

1. 先增加失败测试，证明当前有工具场景只产生一个最终 `message_delta`。
2. 提取增量内容标准化逻辑，兼容字符串和多模态文本块。
3. 对绑定工具后的模型逐轮调用 `astream()`，累计 `AIMessageChunk`，从完整累计消息读取工具调用。
4. 工具开始事件先从异步生成器让出给上游；上游完成 Loop step 落库并请求下一事件后才执行工具，以此保证共享 `AsyncSession` 串行访问。
5. 工具结果追加到消息历史后进入下一轮模型流；没有工具调用时结束循环并输出 `completed`。
6. 确认取消传播到当前异步生成器，且取消后不会启动后续工具。
7. 调整 SDK 自动滚动条件，不改变消息协议和公共 API。
8. 执行后端定向测试、SDK 测试、类型检查、构建和 `git diff --check`，更新 `verify.md` 与 `acceptance.md`。

### 回滚说明

- 后端可单独回滚到原有“无工具原生流、有工具批处理”的 `stream_graph()` 分支，不涉及数据库回滚。
- SDK 自动滚动调整可独立回滚，不影响消息状态或协议兼容。

### 审批判断

- 不新增或修改 API 字段、数据库结构、鉴权、权限和服务边界。
- 用户已于 2026-08-05 确认采用“AgentLoop 实时状态 + 最终回答原生流式输出”方案，可以进入实现。

## 2026-08-06 增量计划：统一 Agent 上游错误终止语义

### 变更文件

- `apps/backend/app/modules/conversation/runtime.py`：新增异常分类和结构化错误 payload 构造，提取状态码、可重试性和脱敏摘要。
- `apps/backend/app/modules/conversation/router.py`：标准 SSE 使用统一错误 payload，保证异常后只结束当前流。
- `apps/backend/app/modules/conversation/services.py`：流式模型异常时将已创建的 Loop/生成步骤标记为失败并保存。
- `apps/backend/app/modules/gateway/router.py`：Embed WebSocket Task 异常使用统一错误 payload，避免透传不可控原始字符串。
- `apps/backend/app/modules/gateway/runtime.py`：Embed 流式运行异常时持久化失败 Loop/步骤并重新抛出供网关发送 error。
- `apps/ai-sdk/src/core/client.ts`：收到 error 后清理 pending assistant、pending loop 和 active request，触发已有错误回调。
- 后端和 SDK 测试文件：覆盖 502 payload、错误终止、Loop 失败落库和 pending 清理。

### 实施步骤

1. 先增加失败测试，锁定 502 的结构化 payload、错误后无完成事件和 SDK pending 清理。
2. 在 conversation runtime 中实现统一异常分类，限制调试摘要长度并避免向 C 端暴露完整堆栈。
3. 在标准 SSE 与 Embed WebSocket 入口复用该 payload；异常路径只发送一次 `error`。
4. 在两条流式服务路径中保存运行中 Loop/模型步骤的 `failed` 状态，不创建失败助手消息。
5. SDK 收到 `error` 后结束当前 request，并保留 `onError`/事件回调兼容。
6. 执行定向后端测试、SDK 测试、类型检查、构建和 `git diff --check`，回填 verify/acceptance。

### 回滚说明

- 回滚 conversation/gateway 的错误映射和失败状态处理即可恢复原错误行为；不涉及数据库迁移。
- SDK 回滚只影响 error 到达后的 pending 状态清理，不影响成功消息协议。

### 人工确认点

- 无。用户已确认使用现有统一 `error` 事件，不新增 `message_failed` 或其他协议类型。

### 超时补充

- 在 `apps/backend/app/core/config.py` 增加模型请求超时和最大重试配置。
- 在 `apps/backend/app/modules/agent/services.py` 将请求超时、流式分块超时和重试上限注入 `ChatOpenAI`，默认 60 秒、0 次自动重试。
- 通过 Agent 版本 `model_options` 保留按模型覆盖能力，增加设置和模型构造回归测试。

## 2026-08-06 增量计划：生成中消息与过程面板展示

### 变更文件

- `apps/ai-sdk/src/ui/components/ChatMessage.vue`：仅在内容块存在可渲染内容时展示正文区域，避免空 Markdown 占位。
- `apps/ai-sdk/src/ui/components/AgentLoopPanel.vue`：解除展开状态与运行状态的强制绑定，有实时步骤时立即允许用户展开或收起。
- `apps/ai-sdk/src/ui/components/ChatWidget.vue`：在首个消息更新到达时创建临时运行中 Loop，避免等待 AgentLoop 事件期间没有过程反馈。
- `apps/ai-sdk/src/ui/components/ChatMessageList.vue`、`ChatMessage.vue` 与 `AgentLoopPanel.vue`：全程传递完整 `Message`，由过程面板直接从 `props.message.loop` 读取 Loop，避免拆分 prop 或局部 computed 投影后停留在空步骤状态。
- `apps/ai-sdk/src/ui/message-presentation.ts`：集中处理可渲染内容判定和 Loop 摘要文案。
- `apps/ai-sdk/src/ui/__tests__/message-presentation.test.ts`：覆盖空白正文、非文本内容块、运行中过程类型和空步骤摘要。

### 实施步骤

1. 提取消息展示纯函数，明确空白文本块不属于可渲染正文，其他内容块维持原渲染入口。
2. 调整助手消息条件渲染：无正文且有 Loop 时只展示过程面板，无正文且无 Loop 时继续展示输入指示器。
3. 将过程面板改为默认收起、步骤到达后即可点击展开；状态和步骤更新保留用户当前选择。
4. 调整运行中摘要文案，使工具、技能和知识库状态在最终答案完成前可识别。
5. 执行 SDK 单元测试、类型检查、生产构建、页面交互检查和 `git diff --check`。

### 回滚说明

- 可独立回滚上述 UI 组件、展示纯函数和测试，不影响消息协议、Loop 状态聚合或历史数据。

### 审批判断

- 本次仅调整现有 SDK UI 的条件渲染和折叠交互，不修改 API、数据库、权限或架构边界，无需新增人工确认。
