# AgentLoop 可观测消息与多内容块调研记录

## 调研问题

- 如何把一次 Agent 回复拆成可展示、可追溯、可落库的消息内容块和执行过程？
- 如何在不暴露原始思维链的前提下，让用户看到“思考中、调用工具、调用技能、知识库引用”等过程信息？
- 调研结果将影响 `apps/ai-sdk` 消息模型、WebSocket/SSE 事件契约、后端会话消息表、AgentLoop 执行过程表和前端聊天组件。

## 功能复杂度

- 级别：核心功能
- 选择理由：本需求涉及聊天消息数据模型、协议事件、SDK 类型、前端渲染、后端落库和可观测审计，属于跨端契约变化。
- 最低调研要求：至少参考官方文档、成熟 SDK 或协议规范，并比较消息内嵌、独立事件流、追踪 span 三类方案。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenAI Agents SDK Tracing
- 链接：https://openai.github.io/openai-agents-python/tracing/
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：以 trace/span 记录 agent run、LLM 生成、函数调用、handoff、guardrail 等过程，支持按执行单元追踪一次 agent 工作流。
- 对本项目的启发：AgentLoop 应作为一次回答的独立执行记录，过程步骤应有类型、状态、耗时、错误摘要和 trace 标识，而不是只塞进最终文本消息。

### 来源 2

- 类型：官方文档
- 名称：OpenAI Agents SDK Tracing - Sensitive data
- 链接：https://openai.github.io/openai-agents-python/tracing/#sensitive-data
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：Tracing 能记录过程，但需要控制输入、输出和敏感数据是否进入追踪系统。
- 对本项目的启发：“思考中”只能落库可展示摘要，不能落库原始 chain-of-thought、完整 prompt、密钥、token、工具敏感入参或用户隐私字段。

### 来源 3

- 类型：官方文档
- 名称：Vercel AI SDK UI - Messages
- 链接：https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-message-persistence
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：AI SDK UI 把消息表达为可持久化的 UI message，消息中包含 parts，可承载文本、工具调用、文件等多类型内容，并支持恢复历史对话。
- 对本项目的启发：本项目消息应采用 `content_blocks` 数组作为主渲染模型，弱化单一 `content` 字段，兼容 Markdown、图片、文件、图表、表格、动作和自定义组件。

### 来源 4

- 类型：官方规范
- 名称：Model Context Protocol Specification - Tool Results
- 链接：https://modelcontextprotocol.io/specification/2025-06-18/server/tools#tool-result
- 版本或发布日期：2025-06-18 规范版本，调研日期为 2026-08-05。
- 核心做法：工具结果允许返回 `content` 内容块、`structuredContent` 结构化结果、`isError` 错误标记，并把面向模型和面向界面的内容分层。
- 对本项目的启发：工具调用和技能调用结果应同时支持展示摘要、结构化数据和错误状态；前端 UI 不应依赖任意字符串解析工具结果。

### 来源 5

- 类型：官方文档
- 名称：LangGraph Streaming
- 链接：https://langchain-ai.github.io/langgraphjs/concepts/streaming/
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：LangGraph 将流式输出拆成 `values`、`updates`、`messages`、`custom`、`debug` 等不同模式，分别服务最终状态、步骤更新、token 流和调试信息。
- 对本项目的启发：同一次 AgentLoop 应允许不同投影：用户 UI 默认看摘要和最终内容，开发者或后台审计可看更细的 step 事件。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：只在 `conversation_messages.metadata` 中保存过程 JSON | 改动小，上线快；不需要新增关联表 | 查询、分页、筛选、审计和增量更新困难；内容块和过程步骤混杂；长期演进容易失控 | 低。只适合原型，不适合后续查看和审计 |
| 方案 B：消息表增加 `content_blocks JSON`，AgentLoop 使用独立 run/step 表 | 兼容现有文本字段；多模态内容可整体恢复；过程步骤可查询、审计和重放；迁移风险可控 | 需要新增表和协议事件；需要定义数据脱敏边界 | 高。适合当前阶段作为第一版正式方案 |
| 方案 C：完全事件溯源，只保存原始事件流，由读取端重放成消息 | 可追溯性最强；适合复杂 agent 工作流 | 实现复杂，读取链路和兼容迁移成本高；对当前聊天 UI 过重 | 中。可作为后续审计增强，不适合作为第一阶段 |
| 方案 D：直接接入第三方 trace 系统作为唯一存储 | 可借助成熟观测能力；开发者视角强 | 与业务会话、权限、历史查看和数据保留策略耦合困难；终端用户 UI 仍需自建投影 | 中低。可作为补充 trace，不应替代业务落库 |

## 最终决策

- 选择方案：方案 B，采用 `content_blocks JSON + agent_loop_runs/agent_loop_steps 独立表`。
- 选择原因：
  - 保留现有 `content` 纯文本字段作为兼容摘要和搜索入口。
  - 使用 `content_blocks` 表达 Markdown、图片、文件、图表、表格、动作和自定义组件。
  - 使用 AgentLoop 独立表记录一次回答的过程摘要，支持历史查看、审计、失败诊断和前端折叠面板。
  - 对原始思维链、敏感工具参数、完整 prompt 采取不落库或脱敏落库策略。
- 不选择其他方案的原因：
  - 方案 A 后续查询与审计能力不足。
  - 方案 C 对当前阶段复杂度过高。
  - 方案 D 不能替代业务数据库中的会话历史。
- 对后续 spec、plan 或人工确认的影响：
  - 需要新增数据库表和迁移。
  - 需要扩展后端事件、SDK 类型和前端渲染协议。
  - 触发数据模型变化和 API 契约变化，进入实现前必须人工确认。

## 剩余风险

- 资料时效性：Agent 追踪和 UI message 规范仍在演进，后续需保留事件兼容策略。
- 与本项目上下文的差异：当前后端已有 `citations` 和工具事件，但尚未统一成 AgentLoop 状态机，需要迁移旧逻辑。
- 尚未验证的假设：
  - 现有历史消息读取接口是否需要一次性返回完整 `content_blocks` 和 `loop`。
  - 自定义组件 `props` 的安全白名单、大小限制和版本兼容策略。
  - 文件、图片等资源 URL 的授权、过期和归档策略。

## 2026-08-05 增量调研：工具场景的原生流式输出

### 调研问题

- 为什么 Agent 配置了 Skill、MCP 或宿主工具后，最终回答会在生成完成后一次性出现？
- 如何让工具状态和最终回答都按真实执行时机更新，同时继续隐藏原始思维链？

### 补充来源

#### 来源 6

- 类型：官方文档
- 名称：LangChain Models - Streaming
- 链接：https://docs.langchain.com/oss/python/langchain/models#stream
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：聊天模型通过 `stream` / `astream` 返回增量消息块；消息块可以累计为完整消息，流中也可包含工具调用片段和用量元数据。
- 对本项目的启发：有工具和无工具场景应统一消费模型增量消息；工具参数片段必须先完整累计，再执行工具。

#### 来源 7

- 类型：官方文档
- 名称：LangGraph Streaming
- 链接：https://docs.langchain.com/oss/python/langgraph/streaming
- 版本或发布日期：在线官方文档，调研日期为 2026-08-05。
- 核心做法：LangGraph 可分别流式传递消息 token、图状态更新和自定义事件，并允许组合多个流模式。
- 对本项目的启发：模型文本与 AgentLoop 状态是同一次运行的不同投影，应保持独立事件语义，不把安全摘要混入回答正文。

### 当前实现审计

- 无工具时，`stream_graph()` 已调用 `model.astream()` 并逐块发送 `message_delta`，属于模型原生流式输出。
- 只要存在可用工具，`stream_graph()` 就委托 `run_graph()` 使用 `ainvoke()` 完成全部模型调用和工具循环，最后把完整 `result.content` 作为单个 `message_delta` 发送。
- SDK 已能累计 `message_delta`、实时投影 AgentLoop，并以 streaming 状态渲染 Markdown；线协议无需增加事件类型。

### 方案比较

| 方案 | 优点 | 限制 | 决策 |
|---|---|---|---|
| A：在现有运行时中实现原生流式工具循环 | 复用现有协议、仓储和 AgentLoop；首字延迟低；改动边界集中 | 需要正确累计工具调用片段、用量和多轮消息 | 选择 |
| B：改用 LangGraph `astream_events` 重写编排 | 图级事件能力完整，后续扩展空间大 | 会扩大运行时架构边界和回归面，不适合本次体验修正 | 暂不选择 |
| C：前端收到完整回答后模拟打字 | 前端改动小，视觉上有逐字效果 | 不降低首字延迟，不是真流式，取消也无法及时中止模型 | 不选择 |

### 增量决策

- 选择方案 A：模型分析、工具调用后的继续生成均使用 `astream()`；通过累计增量消息得到完整 AI 消息和完整工具调用参数。
- AgentLoop 继续只展示“正在分析、调用工具、整理结果、生成回答”等安全状态，不展示或保存原始 chain-of-thought。
- 继续复用 `message_delta` 与现有 AgentLoop 生命周期事件，不新增 API 字段、数据库字段或权限行为。
- 流式异常必须保留已发送内容用于当前界面展示，同时把 Loop 标记为失败并发送现有结构化错误事件；最终持久化仍以完整成功消息为事实来源。
- 本次属于原 request 内的实现修正，不触发新的人工审批，但实施前需要补充计划与针对性验证。

## 2026-08-06 增量调研：Agent 上游错误的终止事件

### 调研问题

- 模型网关返回 502 等上游错误时，如何让 C 端收到可展示提示并可靠结束当前消息？

### 补充来源

#### 来源 8

- 类型：官方文档
- 名称：OpenAI Python Library - Error handling
- 链接：https://github.com/openai/openai-python#error-handling
- 版本或发布日期：在线官方文档，调研日期为 2026-08-06。
- 核心做法：将 HTTP 状态错误映射为带 `status_code` 的 API 异常，并区分可重试的连接/服务端错误；调用方应捕获异常并决定重试或向用户报告失败。
- 对本项目的启发：后端应从异常中提取状态码和可重试性，使用统一结构化错误事件向 C 端报告，而不是把异常变成固定或不可分类的字符串。

#### 来源 9

- 类型：成熟开源项目
- 名称：Vercel AI SDK UI message stream protocol
- 链接：https://github.com/vercel/ai/tree/main/packages/ui-utils
- 版本或发布日期：在线源码，调研日期为 2026-08-06。
- 核心做法：流式消息协议将错误作为当前消息流的终止状态，客户端收到错误后停止 pending 消息并交给 UI 展示，同时保留可重试入口。
- 对本项目的启发：无需新增事件类型；沿用现有 `error` 事件作为 request 的终止信号，SDK 必须清理 pending assistant，避免界面永久处于生成中。

### 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：统一 `error` 事件作为终止信号 | 不新增协议类型；SSE、WebSocket、SDK 复用现有链路；客户端行为清晰 | 需要明确 error 是当前 request 的终止语义 | 高，选择 |
| 方案 B：新增 `message_failed` 事件 | 语义显式 | 扩大协议契约，旧 SDK 兼容和重放逻辑需同步修改 | 中低 |
| 方案 C：只改错误文案 | 改动最小 | 无状态码、重试语义和 pending 清理约束 | 低 |

### 增量决策

- 选择方案 A：后端统一输出 `error` 事件，payload 包含 `code`、用户可展示 `message`、`retryable` 和脱敏 `details`；该事件表示当前 request 结束，不再发送 `message_completed`。
- 对 502、连接错误和服务端 API 错误统一映射为 `agent_upstream_unavailable`，用户提示为“Agent 连接失败（HTTP 502），本轮对话已结束”或对应状态码文案。
- SDK 收到 `error` 后清理 pending assistant、结束当前 request，并触发已有 `onError` 与 error 事件回调。
