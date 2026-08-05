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
