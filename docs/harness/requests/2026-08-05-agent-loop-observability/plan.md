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

5. SDK 协议和状态
   - 扩展 `ProtocolEventType`。
   - 新增 AgentLoop 类型。
   - 在 `AgentClient` 中按 `requestId` 聚合 loop 事件。
   - `message_completed` 时把 `contentBlocks` 和 loop 挂到 assistant message。
   - 保持旧回调 `onMessage`、`onToolCall`、`onToolResult` 可用。
   - 协议解析遇到未知事件时忽略该事件并继续处理同一请求，避免旧 SDK 因新增 AgentLoop 事件中断消息流。

6. 前端聊天 UI
   - 建立 `ContentBlockRenderer`。
   - 建立 `AgentLoopPanel`。
   - Markdown、图片、文件、自定义组件 fallback 作为第一版必达。
   - 图表、表格、动作按钮按 schema 支持最小展示。
   - 前端只展示脱敏后的安全摘要；后台详细审计页面和管理接口本期不实施。

7. 测试和验证
   - 后端测试覆盖模型迁移、schema 校验、loop step 写入和事件输出。
   - SDK 测试覆盖未知事件兼容、新事件解析、loop 聚合、message content blocks。
   - UI 测试覆盖内容块渲染和 loop 面板状态。
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
