---
id: 2026-09-21-ai-sdk-thinking-and-loop-visibility
tier: B
risk: high
approval:
  required: true
  granted: true
  why: ["API 契约变化：message_send payload 新增 thinking 字段", "默认行为变化：思考与 Agent 过程卡片默认关闭，既有接入方升级后行为改变"]
---

## 目标与范围

给 AI SDK 增加两个接入方可配置的开关，都由 `createAgentClient(options)` 一处传入，**两个开关默认关闭，显式传 `true` 才生效**：

1. `thinking?: boolean`（顶层，默认 `false`）——**端到端**控制模型是否思考：SDK 随 `message_send` 下发，后端翻译为上游厂商参数。传 `true` 才进入思考模式。
2. `ui.showAgentSteps?: boolean`（默认 `false`）——**纯 UI** 控制：传 `true` 才渲染思考 / 工具 / 技能 / 知识库过程卡片；不传或 `false` 时只留对话正文。

不做：

- 不做聊天窗内用户可点的开关（本次只做接入方配置项）。
- 不做思考强度分级（`low`/`high`/`max`），只区分「思考 / 不思考」。
- 不接请求级开关到 `conversation` 模块的 admin / 调试路径（`conversation/router.py`、`conversation/services.py`），它们保持既有行为。
- 不新增数据库表、列或迁移。

## 来源与方案比较

调研日期 2026-09-21。

1. **DeepSeek 官方文档**（[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)，2026-09 现行版）：请求体有 `thinking: {"type": "enabled"|"disabled"}`，默认 `enabled`；`reasoning_effort` 取 `none|low|high|max`，其中 `none` 关闭思考。本仓库默认模型正是 DeepSeek（`app/core/config.py` 的 `MODEL_DEFAULT_NAME` 默认 `deepseek-v4-flash`）。**注意上游默认是开启**，因此「默认关闭」必须由我们显式下发 `disabled`，不能靠不传字段。
2. **本机 Pi 源码**（`/Users/lixingwen/xw/git/pi`）：`packages/coding-agent/src/core/defaults.ts` 定义统一语义层 `THINKING_LEVEL_OPTIONS = ["off","minimal","low","medium","high","xhigh","max"]`，再由 `model-config.ts` 的 `ThinkingLevelMapSchema` 按厂商映射为具体参数。即「统一开关 + 每厂商映射表」，而不是在调用点写死厂商参数。
3. **langchain-openai 1.6.0**（本机 `site-packages/langchain_openai/chat_models/base.py`）：`reasoning_effort` 是一等字段，`extra_body` 可透传任意厂商参数；`openai` 客户端在 `_base_client.py:538` 把 `extra_body` **合并进顶层请求体**，因此 DeepSeek 的顶层 `thinking` 对象能经它下发。两者都能由现有 `model_options` 展开注入，不需要改模型构造方式。

方案比较：

- **A**：SDK 直接下发厂商参数对象（`extra_body` / `reasoning_effort` 原样透传）。否决理由见下。
- **B（采用）**：SDK 只下发布尔 `thinking`，后端把它翻译成上游参数。翻译优先级为：先读 `AgentVersion.model_options["thinking"]` 里接入方显式给出的 `on` / `off` 参数对象；未配置时按模型名兜底——命中 `deepseek` 用顶层 `thinking.type` 开关，其余厂商用 `reasoning_effort`。开关语义与厂商解耦。
- **C**：只做 UI 隐藏、不碰模型。用户已明确选择端到端，否决。

## 被否决的选项

- **两个开关默认开启（opt-out）**：用户明确要求默认关闭；且默认开启会让「思考 token 白付费 + 首字延迟」成为所有接入方的默认体验。
- **靠「不传字段」实现默认关闭**：上游 DeepSeek 的 `thinking` 默认是 `enabled`，不传等于开启，无法达成默认关闭，必须显式下发 `disabled`。
- **SDK 直接透传厂商参数（`extra_body` / `reasoning_effort`）**：接入方被迫了解每家厂商的思考参数形态，换模型要改前端代码；且等于把内部模型参数固化成公共契约。
- **只隐藏 UI、不真正关闭模型思考**：用户明确选择端到端；只隐藏仍会继续产生思考 token，白付钱且首字延迟不变。
- **把开关做成聊天窗内可点按钮**：用户明确选择接入方配置项；且需额外做偏好持久化与 header 布局改动。
- **给 `AgentVersion` 新增布尔列（如 `thinking_enabled`）**：属数据模型变化且要迁移，而请求级开关本就该按次生效，落库反而无法表达「同一 Agent 不同请求不同开关」。
- **复用 `MessageSendPayload` 做入参校验**：该 schema 当前是死代码（全仓库仅定义、无引用），贸然启用会把既有未校验字段一并变成强校验，扩大回归面；本次只在 handler 内做最小类型校验。
- **后台管理页（`apps/front`）同步新增开关**：默认关闭已由 SDK 侧表达，Agent 配置页不在本次范围，避免跨第三个 app 扩大改动面。

## 停点判断

- 架构边界变化：否。
- 数据模型变化：否（`AgentVersion.model_options` 是既有 JSON 列，仅约定新 key）。
- API 契约变化：**是**——`message_send` payload 新增 `thinking` 字段。
- 鉴权或权限行为变化：否。
- 命中「API 契约变化」与「默认行为变化」，故 `approval.required: true`，实现前需人工确认。

**破坏性影响（必须让用户知晓）**：两个开关默认关闭后，既有接入方（`apps/ai-sdk/index.html`、`demo/*.html`）升级即静默失去思考与过程卡片显示。SDK 当前为 `0.1.7`，本次默认语义变更按 minor 提升版本并在 README 显著标注迁移方式。

## 变更点

后端：

- `apps/backend/app/modules/agent/services.py`：新增请求级开关到模型参数的翻译函数；`build_chat_model()` 增加可选 `thinking` 入参，为 `None` 时行为逐字节不变。
- `apps/backend/app/modules/gateway/router.py`：`_handle_message_send` 校验 `thinking` 必须为布尔；`produce_embed_request` 把它传给 `build_chat_model`。
- `apps/backend/app/modules/gateway/schemas.py`：`MessageSendPayload` 补 `thinking` 字段定义，与 handler 校验保持一致。

SDK：

- `apps/ai-sdk/src/core/types.ts`：`AgentClientOptions` 增 `thinking?: boolean`；`UIOptions` 增 `showAgentSteps?: boolean`。
- `apps/ai-sdk/src/core/client.ts`：`sendMessage` 始终下发解析后的布尔 `thinking`（未设置为 `false`）。
- `apps/ai-sdk/src/index.ts`、`src/ui/index.ts`：把 `thinking` / `showAgentSteps` 透传到 `ChatWidget`。
- `apps/ai-sdk/src/ui/components/ChatWidget.vue`、`ChatMessageList.vue`、`ChatMessage.vue`：按 `showAgentSteps`（默认 `false`）跳过 `AgentLoopPanel` / `AgentLoopStepCard` / `AgentLoopSkillGroup`，并保证隐藏后 pending 态仍有 `TypingIndicator`。
- `apps/ai-sdk/src/ui/__tests__/chat-message.ssr.test.ts`：现有断言改为显式传 `showAgentSteps: true`，并新增默认关闭的断言。
- `apps/ai-sdk/README.md`：补两个开关的用法、默认值与迁移说明；`apps/ai-sdk/index.html` 显式开启以保留开发态可见性。

验证方式：SDK 侧补 SSR 单测覆盖「默认只留正文、显式开启恢复卡片、pending 仍有指示器」；后端补单测覆盖布尔校验与参数翻译；跑 `vue-tsc`、`vitest`、`pytest`。

## 验收标准

1. 不传任何开关时，SDK 发出的 `message_send` payload 含 `"thinking": false`；`thinking: true` 时含 `"thinking": true`。
2. 不传 `showAgentSteps` 时，`ChatMessage` 渲染结果不含 `xxai-loop-card`、`xxai-loop-skill-group`、`xxai-agent-loop` 任一 class，且正文文本仍在。
3. 不传 `showAgentSteps`、正文为空且 `pending` 为真时，渲染出打字指示器。
4. `showAgentSteps: true` 时，现有 SSR 断言（技能分组、思考折叠、时间线）全部通过，渲染产物与改动前一致。
5. 后端收到非布尔的 `thinking` 时返回 `invalid_thinking` 协议错误且不启动请求；合法布尔值正常透传到模型构造。
6. `thinking` 为 `false` 时，DeepSeek 形态下构造出的请求参数含 `thinking.type = "disabled"`；为 `true` 时含 `"enabled"`。
7. `build_chat_model(version)` 不传 `thinking` 时，构造出的客户端参数与改动前一致。
