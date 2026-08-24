# 业界调研记录

## 调研问题

- 本次要解决什么问题：优化 `apps/ai-sdk` 对话流程，增加"询问"能力——AI 在任务执行中提出问题，让用户从结构化选项中做出选择（可选自由文本），用户选择完成后 AI 继续执行任务。
- 调研结果将影响哪些范围、架构、接口或实现决策：后端工具循环与网关 WebSocket 协议（`apps/backend/app/modules/gateway/dispatcher.py`、`apps/backend/app/modules/gateway/router.py`）、内置工具注册（`apps/backend/app/modules/builtin_tool/registry.py`）、SDK 协议与 UI（`apps/ai-sdk/src/core/*`、`apps/ai-sdk/src/ui/*`），以及验收标准与实施计划。

## 功能复杂度

- 级别：复杂 / 架构级（策略 B）
- 选择理由：跨后端运行时、网关 WebSocket 协议、SDK 三端联动；新增协议事件（`question_required`）与入站消息类型（`question_answer`）属于 API 契约变化，触发人工确认；但复用现有确认机制的 Future 挂起-恢复骨架，不改数据模型。
- 最低调研要求：参考至少两个成熟 Agent 框架的结构化提问实现（问题数量、选项数量、自由文本支持、挂起-恢复机制），比较"新增协议"与"复用确认机制"两条路线。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Claude Code Agent SDK — 处理批准和用户输入（AskUserQuestion）
- 链接：https://code.claude.com/docs/zh-CN/agent-sdk/user-input
- 版本或发布日期：持续维护，页面更新于 2026-07，调研日期 2026-08-24
- 核心做法：`AskUserQuestion` 由模型自主调用；每次调用支持 1-4 个问题，每个问题 2-4 个选项；选项之外允许用户输入自由文本（"Other"）；问题用于澄清歧义、让用户在方案间做选择；子代理中不可用。
- 对本项目的启发：结构化提问的行业标准形态——选项数量 2-4、支持自由文本、由模型自主决定提问时机；本项目按其形态设计 `ask_user` 工具参数（`question` + `options[2-4]` + `allowFreeText`）。

### 来源 2

- 类型：官方文档
- 名称：LangChain LangGraph — Interrupts（Human-in-the-loop）
- 链接：https://docs.langchain.com/oss/python/langgraph/interrupts
- 版本或发布日期：持续维护，页面更新于 2026-08，调研日期 2026-08-24
- 核心做法：`interrupt()` 在图执行中途暂停并返回 payload；外部拿到中断信息后，以 `Command(resume=...)` 注入用户输入并继续执行；结合 checkpointer 可跨进程恢复。
- 对本项目的启发：HITL 的标准模式是"执行到需要决策的点 → 挂起 → 外部输入 → 恢复同一点继续"。本项目已存在等价简化实现（`pending_mcp_confirmations` Future 挂起-恢复），无需引入 checkpointer：WebSocket 连接级 Future 在同一连接生命周期内即可完成挂起与恢复。

### 来源 3

- 类型：官方教程（Vercel Academy）
- 名称：Build Your Own AI Coding Agent Harness — Structured Questions（askUser）
- 链接：https://vercel.com/academy/build-ai-agent-harness/structured-questions
- 版本或发布日期：持续维护，调研日期 2026-08-24
- 核心做法：`askUser` 工具向用户提一个多选问题（2-4 个选项）；配套"Search → Ask → Act"歧义协议：任务范围模糊、需要在方案间选择、行动前缺关键信息时先提问，已有足够上下文则不要问。
- 对本项目的启发：除工具形态外还给出了"何时提问"的提示词策略——应写入系统提示词，防止模型滥用提问；单次任务限定提问次数（本项目取 3 次）作为兜底。

### 来源 4

- 类型：官方博客
- 名称：Spring AI Agentic Patterns (Part 2): AskUserQuestionTool
- 链接：https://spring.io/blog/2026/01/16/spring-ai-ask-user-question-tool
- 版本或发布日期：2026-01-16，调研日期 2026-08-24
- 核心做法：`AskUserQuestionTool` 是 Claude Code `AskUserQuestion` 的可移植实现，允许 AI 在回答前提问澄清、交互式收集需求，支持单选/多选与自由文本；配套 `CommandLineQuestionHandler` 演示终端场景。
- 对本项目的启发：验证了"提问工具 + 前端/宿主处理器回传答案"的通用拆分——本项目对应"后端 `ask_user` 拦截 + SDK `QuestionCard` 组件"。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 新增 `ask_user` 工具 + `question_required`/`question_answer` 协议事件 | 语义清晰，与现有确认机制正交；结构化、可演进（多问题、动态选项、自由文本）；符合业界标准形态 | 新增协议契约（API 变化，需人工确认）；后端/网关/SDK 三端联动 | 高 |
| 扩展现有 `confirmation_required` 支持选项 | 复用确认链路，改动最小 | 批准/拒绝与选择语义混淆；side_effect 审计逻辑耦合；自由文本、多问题表达别扭；后续难以演进 | 低 |
| 纯文本问答（模型文本提问，用户下一条消息回答） | 零协议改动，天然兼容 | 无法渲染结构化选项；模型不保证遵守格式；跨轮状态不可靠 | 低（仅作旧客户端降级兜底） |

## 最终决策

- 选择方案：方案 1——新增内置工具 `ask_user`（`question` + `options[2-4]` + `description` + `allowFreeText`），新增出站事件 `question_required` 与入站消息 `question_answer`；复用现有 `pending_mcp_confirmations` 的 Future 挂起-恢复骨架；SDK 渲染 `QuestionCard` 选项卡片。
- 选择原因：用户已确认采用多选 + 自由文本（选项 B）；四个业界来源（Claude Code、LangGraph、Vercel、Spring AI）均验证"工具 + 挂起/恢复 + 前端选择"形态；与现有确认机制分开，避免语义污染。
- 不选择其他方案的原因：复用确认机制会破坏"批准/拒绝"语义并耦合审计逻辑；纯文本无法满足"让用户做出选择"的结构化诉求。
- 对后续 spec、plan 或人工确认的影响：新增协议事件与入站消息类型属 API 契约变化，`plan -> implement` 前需人工确认；不涉及数据模型与鉴权逻辑变化。启用模型按用户要求调整为普通内置工具语义：仅在后台 `agent_builtin_tools` 绑定启用后进入工具列表，不做无条件/能力门控注入（2026-08-24 用户明确指示，见 `spec.md` 变更记录）。

## 剩余风险

- 模型可能过度提问（每轮都问）：通过系统提示词约束 + 单请求最多 3 次提问的硬上限兜底。
- 旧版 SDK 客户端不理解 `question_required`：SDK 保留 `capabilities: ["questions"]` 协议声明但服务端不再据此门控注入；使用该功能的前端必须升级到带问答处理的新 SDK，否则提问会等待至 600 秒超时。
- 超时或断线导致 Future 未恢复：沿用确认机制的 600 秒超时与连接关闭时的 Future 清理；超时后向模型注入"问题等待超时"结果，由模型决定重试或放弃。
- 资料时效性：Claude Code 文档更新于 2026-07、Spring AI 博客发布于 2026-01，均与调研日期（2026-08-24）接近；实施时如引用具体参数以官方文档为准。
