# 业界调研记录：工具查询结果跨轮记忆（后端智能体复用订单等查询结论）

## 调研问题

- 本次要解决什么问题？
  - 用户问题：「使用 tools 查询出来的数据（如订单），每次追问一句是否都要重新查询？」（特指本仓库 `ai-base` 的后端系统智能体）。
  - 现状：单轮内工具结果以 `ToolMessage` 正确回填给模型，但**跨轮历史只保存最终 assistant 文本**，工具原始结果只落 `agent_loop_steps.output_summary`（截断 500 字符）且不回填模型 ⇒ 下一轮模型看不到上一轮查到的订单/店铺数据，只能重新调用工具或含糊回答。
  - 目标：设计「工具查询结果跨轮记忆」方案，让模型在数据未过期、查询条件未变化时直接复用上一轮结论，仅在需要最新数据或条件变化时重新查询。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - `conversation_messages` 是否要扩展存储语义（是否需要新增消息角色/字段、表结构迁移）；
  - 历史回放到模型上下文的方式（原生消息重放还是文本摘要注入）；
  - 影响范围：`apps/backend` 对话运行时（REST 与 embed WebSocket 两条链路共用）。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及对话消息存储语义与模型上下文构造，业界存在「原生重放 vs 摘要记忆」两种流派，选型会直接影响数据模型与 token 成本；同时 OpenAI 系列模型对 `tool` 消息有强配对约束，方案必须规避。
- 最低调研要求：官方/权威来源 + 成熟开源框架案例（OpenAI Agents SDK、LangGraph、Dify、Semantic Kernel）。

## 背景结论（先回答问题：业界主流如何处理工具结果的跨轮记忆）

- **回答原问题**：在「无记忆」配置下，每次新轮对话都是全新上下文，工具结果不会自动保留到下一轮，业界默认确实需要重新查询或显式重放历史；要「不用重查」，必须把上一轮工具查询的事实**以某种形式重新放进下一轮上下文**。
- 业界三类做法：
  1. **完整消息原生重放（标准做法）**：把整轮对话按序重放，包括「带 `tool_calls` 的 assistant 消息 + 每条 tool 结果（`ToolMessage`）」。OpenAI Agents SDK 的 Session、LangGraph 的 checkpointer、Dify 的会话历史都属此类。
  2. **摘要/压缩记忆**：对工具结果做长度裁剪或语义摘要后随历史注入，控制 token 与敏感面（对应 OpenAI SDK 的 `SessionSettings(limit)` 裁剪思想、LangGraph 的 summarization 思路）。
  3. **无记忆（本仓库现状）**：仅重放 user/assistant 最终文本，工具结果不跨轮可见。
- **关键硬约束（来自多个供应链的同一错误文本）**：OpenAI 系接口强制要求 `role="tool"` 的消息必须是对**前一条带 `tool_calls` 的 assistant 消息**的响应，且每个 `tool_call_id` 都要有对应结果。⇒ 若要「原生重放」，存储层必须能重建完整的「assistant(tool_calls) → ToolMessage」元组，缺一环即报错。
- **结论**：业界支持跨轮复用工具结果的前提，都是「先把工具调用链（含中间 assistant 与结果）持久化下来」。本仓库现状只存最终文本，无法重建该元组；直接上「原生重放」需要改消息存储模型与回放逻辑，工程与 token 成本高。更匹配现状的路径是「**摘要快照**」：把每轮成功工具查询压缩成带时间戳的脱敏事实快照，随历史文本注入下一轮。

## 参考依据

### 来源 1

- 类型：官方文档（OpenAI Agents SDK）
- 名称：Sessions — 会话记忆
- 链接：https://openai.github.io/openai-agents-python/sessions/
- 版本或发布日期：持续更新；调研日期 2026-09-03
- 核心做法：
  - 默认每次 `run` 都是独立上下文，只有本轮消息对模型可见；跨轮记忆必须显式使用 Session；
  - Session 会保存完整会话项（用户消息、assistant 回复、工具调用与结果等），新一轮开始时把这些项按序重放给模型；
  - 用 `SessionSettings(limit=N)` 等限制回放条数，超过限制移除最旧项，控制上下文体积。
- 对本项目的启发：业界标准答案是把「上一轮完整对话项（含工具调用与结果）」重放进新轮；重放条数有上限控制 ⇒ 我们若做记忆，也必须给长度/条数设上限，避免几十次工具调用全部回放造成 token 爆炸。

### 来源 2

- 类型：官方指南（OpenAI API）
- 名称：Running agents — 多轮运行的官方建议
- 链接：https://developers.openai.com/api/docs/guides/agents/running-agents
- 版本或发布日期：持续更新；调研日期 2026-09-03
- 核心做法：
  - 多轮对话建议用 **server-managed state**（session / previous_response_id）承载历史，而不是客户端自行拼接消息再整段重发；
  - server-managed state 让服务端按序重放历史，避免客户端拼接导致消息错位（尤其含工具调用时）。
- 对本项目的启发：跨轮记忆的权威实现方式是「服务端保存、按序回放」，印证本仓库应把可回放的记忆数据落在 `conversation_messages` 侧，而不是让 SDK 端自行维护。

### 来源 3

- 类型：开源 issue（错误语义证据）
- 名称：openai/openai-agents-python issue #873
- 链接：https://github.com/openai/openai-agents-python/issues/873
- 版本或发布日期：issue 核对于 2026-09-03
- 核心做法（错误文本）：
  - `messages with role 'tool' must be a response to a preceding message with 'tool_calls'`——`tool` 消息必须紧跟带 `tool_calls` 的 assistant 消息；
  - 该错误在 OpenAI 系接口（及 portkey 等错误库）中为同一文本，说明是服务端强校验。
- 对本项目的启发：若跨轮历史里出现孤立的 `ToolMessage`（无配对 assistant），请求会直接失败；「原生重放」方案必须保证历史中工具元组完整，否则回放即报错。

### 来源 4

- 类型：开源讨论（错误语义证据，Microsoft Semantic Kernel）
- 名称：semantic-kernel discussion #8105
- 链接：https://github.com/microsoft/semantic-kernel/discussions/8105
- 版本或发布日期：讨论核对于 2026-09-03
- 核心做法：
  - 「assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'」；
  - 每个工具调用 ID 都必须有对应结果消息，不能少、不能乱序。
- 对本项目的启发：跨供应链（OpenAI/微软）对工具消息配对的要求一致 ⇒ 重建「历史工具元组」的容错成本高，摘要快照路线天然规避该约束，对任意模型供应商都兼容。

### 来源 5

- 类型：官方文档（LangChain/LangGraph OSS）
- 名称：LangGraph Persistence（持久化与检查点）
- 链接：https://docs.langchain.com/oss/javascript/langgraph/persistence
- 版本或发布日期：持续更新；调研日期 2026-09-03
- 核心做法：
  - checkpointer 把线程状态（ThreadState，核心即消息列表）落盘，同一线程后续轮次从检查点恢复；
  - 工具调用的中间结果与最终消息都保留在状态里，恢复后模型可直接引用此前查询结果，无需重查。
- 对本项目的启发：LangGraph 把「存整轮消息」作为跨轮复用工具结果的默认机制；同时官方体系内也有 summarization/压缩思路用于控制超长历史 ⇒ 我们自研时可在「存整轮」与「存摘要」之间按成本选型。

### 来源 6

- 类型：官方文档（Dify 自托管 Agent）
- 名称：Agent 功能与历史消息上限说明
- 链接：https://docs.dify.ai/en/self-host/use-dify/build/agent
- 版本或发布日期：持续更新；调研日期 2026-09-03
- 核心做法：
  - Agent 会话把对话历史（含工具执行过程）以消息列表形式回放给 LLM，使模型能延续上下文中的工具结论；
  - 单会话历史有上限（约 500 条消息或 2000 token 级，超限移除最旧消息），防止上下文失控。
- 对本项目的启发：主流产品都「回放消息列表给模型」且「给历史设上限」；本仓库已有 `conversation_history_window_seconds`（默认 3600s）时间窗上限，可在其内做快照注入，超窗自动失效。

## 仓库现状分析（代码级证据，2026-09-03 核对）

- `conversation_messages` 表结构已具备扩展基础：`role` 字段类型含 `user/assistant/tool`，并已有 `tool_call_id` 与 `message_metadata`（JSON）列（`apps/backend/app/modules/conversation/models.py:42` 附近）。
- 历史读取已按 `role in ("user","assistant","tool")` 过滤（`apps/backend/app/modules/conversation/repositories.py:91` `list_recent_context_messages`）。
- 历史转换已支持把 `role="tool"` 转成 `ToolMessage`（`apps/backend/app/modules/conversation/runtime.py:74-108` `build_history_messages`）。
- **但全仓库没有任何写入 `role="tool"` 消息行的代码**；跨轮历史只含 user/assistant 最终文本。
- 单轮内回填正确：`runtime.py` 工具循环把每次结果以 `ToolMessage(content=_tool_result_content(...))` 追加回模型（`_execute_tool_round` 附近，约 `runtime.py:811`）。
- 工具结果展示摘要 `_tool_result_summary` 截断 500 字符仅用于 `agent_loop_steps.output_summary`，不回填模型（`runtime.py:298-330`）。
- 回填入口：`load_recent_history`（`conversation/services.py:156`），窗口配置 `conversation_history_window_seconds` 默认 3600s。
- 两条链路共用同一运行时：REST `execute_chat/stream_chat`（`conversation/services.py`，落库仅 assistant，`_finish_stream_chat`）与 embed WebSocket `stream_embed_chat`（`gateway/runtime.py:645` 附近，落库同样仅 assistant）。
- 工具示例：`order_query` 已在 `apps/backend/app/modules/tools/shop/data/order_query.py`，输出字段白名单化（剔除手机号等隐私字段）。

## 方案比较与决策

### 方案 A：完整原生重放（业界标准，OpenAI SDK / LangGraph / Dify 同款）

- 内容：把每轮「assistant(带 tool_calls) + tool(ToolMessage)」整链落库，下一轮按序原生重放。
- 优点：与 OpenAI Agents SDK 行为完全一致，模型拿到的就是完整工具过程，事实零丢失。
- 缺点（本仓库落地成本高）：
  1. 需要为**每次模型中间调用**落库带 `tool_calls` 的 assistant 记录（当前数据库只存最终文本，无法重建元组），属消息存储模型变化；
  2. OpenAI 系强校验「tool 必须紧跟带 tool_calls 的 assistant」且逐 `tool_call_id` 配对，历史一旦缺环/乱序整次请求失败；
  3. `agent_max_iterations` 默认 20，工具结果可能几十个且单条上限 2 万字符（内置工具 10 万），原样重放 token 成本高；
  4. 现有 `build_history_messages` 会跳过空 content 消息，改造需连带处理该逻辑与前后端展示隔离。

### 方案 B：脱敏摘要快照（推荐，借鉴 SessionSettings(limit)/summarization 思想）

- 内容：
  1. 工具循环结束后，把本轮**成功**工具查询的模型可见结果（即同轮回填的 ToolMessage 文本，工具层已脱敏白名单化）压缩成结构化中文「数据快照」条目：工具名 + 查询时间 + 参数摘要 + 截断后的结果事实文本；
  2. 快照随最终 assistant 消息一起落库（存 `message_metadata`，不改表结构、不新增消息行）；
  3. 下一轮 `build_history_messages` 时，把窗口内 assistant 上的快照组装成一段文本（前置一条轻量 SystemMessage 说明时效语义），注入到当前用户消息之前；
  4. 注入文本自带指令：同范围问题可直接用快照回答；用户要求最新数据、变更时间/查询条件或快照缺失时，应重新调用工具查询。
- 优点：跨模型供应商（OpenAI/DeepSeek/MCP/内置工具）纯文本兼容；不产生孤立 `ToolMessage`，规避配对硬约束；长度/条数可控；快照随历史窗口（3600s）自动失效；前端与 SDK 零改动（快照存 metadata 不进入可见 content）；工具失败/等待确认不产生快照。
- 缺点：快照是截断文本，事实密度低于原生重放；对超长内置工具结果只能取头部（有界丢失）。
- 本仓库现状是「只存最终文本」，方案 B 只需在「生成快照 → 落 metadata → 回放注入」三处做最小改动，两条链路共用同一运行时即可同时生效。

### 决策

- **采用方案 B（脱敏摘要快照）作为本次实现方案**；方案 A（原生重放）作为远期演进方向记录在非目标，后续若消息存储模型升级到「中间 assistant + tool_calls 完整落库」再评估。
- 落地要点：
  1. 快照仅取同轮已回填模型的脱敏结果文本并截断（默认单条 2000 字符、每轮 10 条，可配置），不落敏感原文（与 `message_metadata` 列注释「不保存敏感原文」一致）；
  2. 存储：最终 assistant 消息的 `message_metadata["tool_snapshots"]`，表结构零迁移；
  3. 注入：`build_history_messages` 收尾追加快照文本段，REST 与 embed WebSocket 自动同享；
  4. 时效：快照文本带查询时间，随 `conversation_history_window_seconds` 窗口自动失效，不单独加 TTL。
