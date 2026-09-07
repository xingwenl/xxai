# 业界调研记录

## 调研问题

本次调研关注如何把当前 REST 对话、Embed WebSocket、工具调用、确认等待和流式事件组织成可复用的 Python Agent runtime，同时降低 `conversation/runtime.py` 与 `gateway/router.py` 的职责耦合。

## 功能复杂度

- 级别：核心功能 / 架构级重构
- 选择理由：影响 Agent 主循环、工具执行、流式协议适配、会话持久化及网关连接状态。
- 最低调研要求：官方框架/协议资料、成熟开源实现，并比较统一运行时与协议分层方案。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：LangChain Agents / Middleware
- 链接：https://docs.langchain.com/oss/python/langchain/agents
- 版本或发布日期：LangChain OSS Python 文档，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：Agent 由模型、工具和运行时循环组成；中间件用于在模型调用和工具调用前后插入策略、状态与观测逻辑。
- 对本项目的启发：把模型循环、工具执行和外围协议拆成独立 seam；REST/WebSocket 不应各自实现 Agent 循环。

### 来源 2

- 类型：官方文档
- 名称：FastAPI WebSockets
- 链接：https://fastapi.tiangolo.com/advanced/websockets/
- 版本或发布日期：FastAPI 官方文档，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：WebSocket endpoint 负责连接接收、发送和断开异常；业务逻辑可以通过依赖注入和独立函数组织。
- 对本项目的启发：网关应成为协议 Adapter，连接状态、入站消息分发和 Agent 执行协调应从 endpoint 中抽离。

### 来源 3

- 类型：成熟开源项目
- 名称：Microsoft AutoGen AgentChat
- 链接：https://github.com/microsoft/autogen/tree/main/python/packages/autogen-agentchat
- 版本或发布日期：AutoGen main 分支，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：通过 Agent/消息/事件模型表达运行过程，把执行结果和流式事件作为结构化对象传播，而不是让调用方依赖内部字典细节。
- 对本项目的启发：定义稳定的 `AgentRequest`、`ToolCall`、`ToolOutcome`、`AgentEvent`，协议层再做 JSON/SSE 转换。

### 来源 4

- 类型：成熟开源项目
- 名称：PydanticAI Agent Graph / RunContext
- 链接：https://ai.pydantic.dev/agents/
- 版本或发布日期：PydanticAI 官方文档，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：运行上下文显式携带依赖和请求级状态，工具通过类型化参数获得上下文，模型运行结果与工具执行边界清晰。
- 对本项目的启发：用请求级运行上下文替代跨层传递的大量裸参数和动态 `kwargs`。

### 来源 5

- 类型：本地成熟开源项目源码
- 名称：Pi Agent Loop
- 链接：本地 `/Users/lixingwen/xw/git/pi/packages/agent/src/agent-loop.ts`、`types.ts`
- 版本或发布日期：本地工作树，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：用一个共享的 `runLoop` 同时支撑新请求和 continuation；通过 `AgentEventSink` 推送结构化事件；用 `AbortSignal` 贯穿模型流和工具执行；把 `transformContext`、`prepareNextTurn`、`shouldStopAfterTurn`、steering/follow-up 消息作为显式扩展点。
- 对本项目的启发：`agent_runtime` 应把“运行上下文变换”“每轮结束策略”“中断信号”“继续执行”设计为显式能力，而不是散落在 gateway Future 和 router 分支中。Pi 对截断的工具参数会拒绝执行，这个安全约束也适合纳入本项目。

### 来源 6

- 类型：本地成熟开源项目源码/文档
- 名称：Pi Protocol、Client State 和 Telemetry
- 链接：本地 `/Users/lixingwen/xw/git/pi/packages/protocol/src/schemas.ts`、`packages/client/README.md`、`packages/telemetry/README.md`
- 版本或发布日期：本地工作树，2026-09-03 调研
- 调研日期：2026-09-03
- 核心做法：请求通过 ID 关联；服务端快照作为权威状态，进度事件不乐观覆盖快照；协议事件和持久化快照分离；Telemetry 使用显式 parent context，Adapter 负责后端差异。
- 对本项目的启发：保留当前 `requestId`/`sequence`，但将“权威持久化状态”和“实时进度事件”分离；为 Agent runtime 增加显式 request context 与可插拔观测接口。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 继续在 REST、Embed 中分别维护循环 | 改动小 | 逻辑重复，状态和错误语义容易漂移 | 低 |
| 抽出统一 Agent runtime，REST/WebSocket 作为 Adapter | 复用度高，测试面清晰，协议变化不影响核心循环 | 需要一次性定义事件和工具调用契约 | 高，最终采用 |
| 全量替换为第三方 Agent 框架 | 可快速获得部分能力 | 现有 MCP、宿主工具、确认、持久化和协议模型难以直接匹配，迁移风险高 | 中低 |
| 参考 Pi 的最小核心循环 + 显式事件/上下文扩展点 | 共享循环、可中断、可 continuation，兼容现有业务 | 需要重新定义 Python 内部契约和取消语义 | 高，纳入最终方案 |

## 最终决策

- 选择方案：保留现有模型和工具实现，抽出统一的类型化 Agent runtime；参考 Pi 的共享 loop、事件 sink、显式 context transform、continuation、Abort/取消和安全工具执行约束；将 REST SSE 与 WebSocket 网关降级为协议 Adapter；通过 ToolExecutor 注册表扩展工具来源。
- 选择原因：最能复用现有业务能力，且能逐步迁移，不要求立即替换 LangChain 或现有持久化模型。
- 不选择其他方案的原因：双链路重复方案无法解决架构根因；全量引入第三方框架会扩大迁移范围并改变既有行为。Pi 的 TypeScript 实现只借鉴边界和机制，不直接复制其类型或协议。
- 对后续 spec、plan 或人工确认的影响：会改变 `conversation` 与 `gateway` 的职责边界，进入实现前必须人工确认；本次计划不主动修改数据库表和公开 API 契约。

## 剩余风险

- 资料时效性：调研基于 2026-09-03 可访问的官方文档和开源仓库。
- 与本项目上下文的差异：参考项目的状态持久化和 WebSocket 协议不同，不能直接复制实现。
- 尚未验证的假设：现有 REST 与 Embed 的事件语义可以收敛为同一内部事件模型；需要在实现阶段通过兼容测试验证。

## 2026-09-04 增量调研：多工具调用失败策略

### 调研问题

当一次模型响应包含多个工具调用时，一个工具抛出异常或返回 `failed`，Agent 是否应立即终止整轮，还是将失败转换为工具结果并继续执行同批次的其他工具。

### Pi 实际实现依据

- 来源：本机 Pi Agent Loop，`/Users/lixingwen/xw/git/pi/packages/agent/src/agent-loop.ts`
- 关键位置：`executeToolCallsSequential`、`executeToolCallsParallel`、`executePreparedToolCall`、`shouldTerminateToolBatch`
- 调研日期：2026-09-04
- 实际结论：工具执行异常在 `executePreparedToolCall` 中转换为 `isError=true` 的工具结果；顺序模式继续处理后续工具；并行模式等待已启动工具完成，并按原调用顺序生成工具结果消息。批次是否终止由所有结果的 `terminate=true` 共同决定，而不是由单个错误结果隐式终止。
- 额外约束：模型输出因长度截断导致工具参数可能不完整时，Pi 不执行这些调用，而是为每个调用生成错误工具结果；取消则通过 `AbortSignal` 传播，不伪装成普通工具失败。

### 方案比较

| 方案 | 行为 | 优点 | 限制 |
|---|---|---|---|
| 立即失败 | 第一个工具异常后发布失败事件并抛出 Agent 级错误，后续调用不执行 | 实现简单，失败反馈快 | 独立工具被连带跳过；模型拿不到完整批次结果；与并行执行语义不一致 |
| 批次尽力完成 | 每个工具异常统一为 `ToolOutcome(status=failed)`，继续执行同批次其他工具，全部结果回填模型 | 保留独立工具结果，适合查询/分析类任务；与 Pi 的错误隔离方式一致 | 需要区分工具失败、取消、确认等待和显式终止；单次请求可能继续消耗模型调用 |
| 全局失败但先完成工具 | 先等待同批次工具全部结束，再不回填模型而直接结束 Agent | 能避免遗留后台工具；错误边界清晰 | 丢失其他成功工具结果，模型无法基于部分结果继续决策 |

### 最终决策

本项目采用“批次尽力完成”策略，具体规则如下：

1. 工具抛出的普通异常转换为失败 `ToolOutcome`，发布 `tool_completed(status=failed)`，继续执行同一模型响应中的后续工具调用。
2. 工具主动返回 `status=failed` 时视为普通工具结果，不立即终止；结果与成功结果一起回填模型，由模型决定如何回答或重试。
3. `CancelledError`、请求取消、确认等待、用户问题等待���显式不可继续状态不转换为普通失败；按现有终态语义停止后续执行。
4. 只有所有工具结果都标记为显式终止，或出现取消/等待类状态时，才停止继续请求模型。
5. 保持 REST、SSE、WS 公开事件和数据库结构不变；本次只调整 runtime 内部轮次控制与测试覆盖。

### 剩余风险

- 某些工具可能具有副作用，模型一次返回多个调用时继续执行后续调用必须依赖现有工具权限、确认和幂等约束；不改变这些边界。
- 当前 Python runtime 的工具调用是顺序执行，暂不引入并行执行，以避免 AsyncSession 共享和工具副作用并发风险；仅采纳 Pi 的“失败结果化”和批次终止判定思想。

## 2026-09-04 增量调研：最大轮数后的收尾行为

### 调研问题

`AgentLoop.max_turns` 达到上限时，若上一轮模型仍返回工具调用，如何在不执行新工具、不改变公开协议的前提下生成明确终态。

### 参考实现

- 来源：本机 Pi Agent Loop，`/Users/lixingwen/xw/git/pi/packages/agent/src/agent-loop.ts`、`packages/agent/src/types.ts`
- 调研日期：2026-09-04
- 实际做法：Pi 将轮次停止作为 `shouldStopAfterTurn` 等显式策略；模型 `error`/`aborted` 直接结束，长度截断导致的工具调用转为错误工具结果，不执行潜在损坏参数。Pi 没有固定轮数 wrap-up prompt，因此本项目只借鉴“显式停止原因、不可执行工具结果和取消语义分离”。
- 约束启发：达到预算后必须在循环边界停止；不能把预算耗尽伪装成普通工具异常，也不能让收尾阶段重新进入工具循环。

- 来源：现有 legacy Graph，`apps/backend/app/modules/conversation/runtime.py` 的 `_MAX_ITERATIONS_WRAPUP_PROMPT`、`_finish_tool_loop`、`run_graph`、`stream_graph`
- 调研日期：2026-09-04
- 实际做法：检测到最后一轮仍有工具调用且达到 `AGENT_MAX_ITERATIONS` 时，不执行这些工具，注入一次系统收尾提示；收尾调用使用未绑定工具的模型，流式与非流式都把收尾文本作为最终内容；收尾失败使用稳定降级文案。
- 约束启发：收尾提示必须只调用一次；收尾模型不可继续调用工具；收尾失败要有可持久化的最终内容。

### 方案比较

| 方案 | 行为 | 优点 | 限制 |
|---|---|---|---|
| 直接返回上一轮 | 达到上限后立即返回最近模型结果 | 改动最小 | 最近结果可能只有工具调用，没有明确回答；调用方无法区分预算终态 |
| 预算收尾调用 | 注入一次收尾提示，用禁用工具的模型生成最终回答 | 延续旧 Graph 行为；用户能获得明确回答；不执行超预算工具 | 需要模型 Adapter 支持禁用工具和收尾状态；收尾仍可能失败 |
| 继续工具直到自然结束 | 忽略上限，继续执行工具轮次 | 结果可能更完整 | 违背预算约束，可能无限循环或产生额外副作用 |

### 最终决策

采用“预算收尾调用”方案：达到 `max_turns` 且最近一轮包含工具调用时，停止执行新的工具，追加一次内部收尾提示并调用禁用工具的模型；若收尾响应仍携带工具调用，则统一转换为不可执行的失败工具结果并结束，不再次调用模型。取消、确认等待、用户问题等待仍优先于预算收尾并保持原有停止/暂停语义。预算终态通过现有 `completed`/结果适配路径表达，不新增公开事件类型。

### 剩余风险

- 收尾提示属于内部上下文，不应写入用户消息或改变公开消息格式；需要测试确认 REST、SSE、WS 适配器仍只看到既有事件形状。
- 收尾阶段禁用工具依赖模型调用 Adapter 的显式参数；若底层模型不支持该参数，必须在 runtime 层保证工具不会被执行，并以稳定失败结果结束。

## 2026-09-04 阶段 2 调研：工具状态与终态统一

### 调研问题

当前 `ToolOutcomeStatus`、`RunStatus`、conversation loop/step 状态和 gateway 生命周期状态分别维护状态集合，需确认哪些状态属于工具结果、运行中间态或请求终态，以及未知状态如何处理。

### 参考实现与现状

- Pi `agent-loop.ts`：工具结果通过 `isError` 与显式 `terminate` 区分；工具错误不自动等价于 Agent 级失败，取消使用 `aborted` 独立语义。
- 本项目 `agent_runtime/contracts.py`：工具结果已有 `completed/failed/confirmation_required/waiting_user/expired/rejected`，但缺少 `cancelled/budget_exceeded` 的统一枚举值。
- 本项目 `agent_runtime/lifecycle.py`：运行生命周期只有 `running/completed/failed/cancelled`，等待确认/用户问题和预算耗尽未进入同一状态机。
- 本项目 `conversation/runtime.py`、`gateway/runtime.py`：分别把工具状态转换为 `succeeded/failed/waiting_confirmation/waiting_question` 或 loop `completed/failed`，未知状态默认成功，存在错误升级和错误降级风险。

### 方案比较

| 方案 | 做法 | 优点 | 限制 |
|---|---|---|---|
| 继续各层映射 | 保留现有字符串和默认分支 | 改动最小 | 状态语义继续漂移，未知值可能被误报成功 |
| 统一内部状态分类与集中映射 | runtime 定义工具状态、等待态、请求终态和安全默认值；conversation/gateway 只调用 Adapter | 事实来源单一，便于幂等和测试；不改变公开协议 | 需要调整内部契约和现有映射测试 |
| 完全复刻第三方状态模型 | 直接采用 Pi 的 `isError/terminate/aborted` | 与参考实现一致 | 无法直接表达现有 confirmation、ask_user、数据库 waiting 状态，迁移成本高 |

### 最终决策

采用“统一内部状态分类与集中映射”：

1. 工具状态保留现有公开/持久化兼容字符串，并补充 `cancelled`、`budget_exceeded` 内部值。
2. 明确三类状态：工具完成结果、等待态（confirmation/user/question）、请求终态（completed/failed/cancelled/budget_exceeded）。工具 `failed` 不自动升级为 Agent 请求 `failed`。
3. 集中提供安全映射函数：未知工具状态默认 `failed` 而不是成功；`expired/rejected` 映射为失败类 step；预算耗尽映射为预算终态；取消独立映射为 cancelled，不能生成工具失败事件。
4. 生命周期状态机允许等待态进入可恢复中间态，但终态只允许一次；迟到的确认/host 回调不得覆盖 completed/failed/cancelled/budget_exceeded。
5. 不修改 REST、SSE、WS 公开事件名称、数据库模型、鉴权或权限边界；公开层继续使用现有兼容字符串，由 Adapter 负责转换。

### 剩余风险

- 现有数据库 `loop.status`/`step.status` 可表达的字符串集合比 runtime 更窄，预算终态需要通过现有 `completed` 或 `failed` 兼容落库，同时保留内部原因字段，不能直接扩表。
- gateway 的 request lifecycle 与 conversation 的 loop status 不应互相覆盖，需要增加跨 Adapter 的终态幂等测试。

## 2026-09-04 阶段 3 调研：模型调用错误收敛

### 调研问题

runtime 灰度路径与 legacy Graph 对同一模型异常是否产生一致的错误事件、可重试判断和 usage 归一化。

### 参考实现与现状

- legacy `conversation/runtime.py::build_agent_error_payload`：识别上下文超限、HTTP 5xx/502、连接/超时错误；4xx 不重试；details 携带状态码和截断后的异常文本。
- runtime `agent_runtime/errors.py::error_from_exception`：原实现只区分取消与连接/超时，其余一律 `agent_request_failed/retryable=False`，与 legacy 对 502/5xx/上下文超限的分类不一致。
- runtime `langchain_adapter.py::_normalize_usage`：原实现缺少 `response_metadata.usage` 兜底，legacy `extract_token_usage` 有；同一供应商响应在两条路径可能得到不同 usage。

### 最终决策

1. runtime 错误分类与 legacy 对齐，但不复制 legacy 把原始异常文本放进 details 的做法；runtime details 只暴露状态码与异常类型，避免泄露供应商内部信息。
2. 上下文超限、HTTP 5xx、连接/超时、客户端 4xx 按 legacy 语义设置 code/retryable。
3. usage 归一化补齐 `response_metadata.usage` 兜底，保持归一化后要么完整三字段、要么为 None 的安全语义。
4. LangChain `invalid_tool_calls` 不进入执行契约；空内容模型结果保持与 legacy 相同的 completed 终态。

### 剩余风险

- legacy details 仍暴露截断异常文本；runtime 已收敛为安全字段，两路径 details 结构不同但均向前端兼容。

## 2026-09-04 阶段 4 调研：上下文与消息构建

### 调研问题

AgentRuntime 灰度路径把 legacy `apply_context_guardrail` 作为 `context_transform` 使用，但 AgentLoop 上下文是 LangChain 消息与内部 `ModelTurn`/`ToolOutcome` 的混合列表，需确认单条消息裁剪是否破坏 assistant/tool 配对。

### 参考实现与现状

- legacy `apply_context_guardrail`：按「旧历史 → 快照」顺序逐条删除消息，保留系统提示与最后一条；只理解带 `content` 的对象。
- runtime 上下文：工具结果以 `ToolOutcome` 追加（无 `content`），且可能位于列表末尾；护栏逐条删除会把 assistant 工具调用删掉而保留孤立 `ToolOutcome`，随后回填模型产生非法消息序列。
- Pi 消息适配要求 role 配对校验与上下文变换安全回退；本项目此前缺少 runtime 混合上下文的护栏回归。

### 最终决策

1. 新增 `apply_runtime_context_guardrail`：以「整轮」为删除单元，assistant 工具调用与其紧随的工具结果必须同删同留。
2. 系统提示、快照消息和最近一轮（含工具配对）保留；超预算时整轮丢弃最旧历史。
3. `_messages_chars` 增加 `ToolOutcome` 估算，避免护栏因低估而不触发。
4. REST/WS 的 AgentRuntime 灰度入口改用新护栏；legacy Graph 继续使用原护栏，行为不变。

### 剩余风险

- 若预算仍小于系统提示与最近一轮，runtime 只能保留当前轮并记录 warning；后续模型调用可能仍被供应商拒绝，这与 legacy 降级语义一致，待真实环境验证。

## 2026-09-04 阶段 5 调研：工具执行边界

### 调研问题

1. Agent runtime 是否绕过现有 Dispatcher/Adapter 的权限、确认和审计边界。
2. runtime 主循环（`AgentLoop`）与 legacy fallback（`ToolRoundExecutor`）对“未知工具、工具异常、取消、等待态”是否保持同一套工具级语义。
3. WebSocket 宿主工具（host tool）等待页面结果期间是否可能无界挂起，取消时是否有 Future 清理缺口。

### 参考实现与现状

- Pi `packages/agent/src/agent-loop.ts`（阶段 5 调研日期：2026-09-04）：
  - 未知工具名不会静默跳过：`prepareToolCall` 找不到工具时返回 immediate error tool result，结果回填模型，模型可据此换工具或直接回答。
  - 工具异常统一收敛为带 `isError` 的工具结果；批次是否终止由显式终止语义决定，不因单个错误跳过同批次其他工具。
  - `AbortSignal` 在工具之间检查；取消不被伪装成普通工具失败。
- 本项目现状：
  - runtime 灰度路径：`AgentLoop` 内联执行工具，未知工具由 `make_legacy_tool_invoker` 返回 `failed(tool_not_found)`；普通异常经 `error_from_exception` 转为 `failed` 工具结果并继续同批次；等待态短路返回；`CancelledError` 原样传播，不生成失败工具事件。
  - legacy fallback：`conversation/runtime.py::_execute_tool_round` 使用 `agent_runtime/tool_loop.py::ToolRoundExecutor`。未知工具名在 `ToolCatalog` 中找不到时直接 `continue`，不发布事件、不回填模型，整轮可能被误判为“未执行工具”而提前收尾；工具回调抛普通异常时原样向上传播，最终被当成整请求错误，与 runtime 的“工具失败结果化”分叉。
  - host tool 等待：`gateway/dispatcher.py::_invoke_host_tool` 创建审计后直接 `await future`，没有类似 MCP 确认（`wait_for(expires_at)`）和 ask_user（`wait_for(600s)`）的服务端超时；取消发生在 `await future` 时不会执行末尾的 `pending_host_results.pop`，依赖连接层 `_cancel_pending_request_futures` 兜底清理。
  - `AGENT_RUNTIME_ENABLED` 默认关闭，legacy Graph 目前仍是默认运行路径。

### 方案比较

1. 只收敛 runtime 主路径：权限、异常、取消、等待语义已在灰度路径闭环，但默认路径（legacy fallback）继续保留静默跳过与“异常即请求错误”的分叉行为，阶段 5 目标不能算全局达成。
2. 统一 legacy 工具轮语义：把未知工具/普通异常归一化为 `failed` 工具结果并继续同批次，等待态/预算短路与取消传播保持原样；需要修改 fallback 行为（不涉及公开协议、数据库模型与权限），且需回归既有 legacy 测试。
3. 为 host tool 等待补服务端超时：沿用 `create_audit` 已写入的 `expires_at`（当前 10 分钟），`awaiting_confirmation` 超时走既有的 `expired` 转换，`running` 超时走既有的 `failed` 转换并携带 `host_tool_execution_timeout` 错误码；同时在 `finally` 中清理 pending Future，迟到页面结果继续由审计幂等逻辑忽略。
4. 维持现状：仅记录剩余风险，把两处缺口推迟到删除 legacy Graph 的阶段 7；期间默认路径仍存在“空收尾/请求级错误”和“页面永不响应则请求无界挂起”的隐患。

### 最终决策（待用户确认）

推荐采用“方案 2 + 方案 3”：

1. `ToolRoundExecutor`（legacy 工具轮）补齐与 runtime/Pi 一致的归一化语义：未知工具与普通异常都转为失败工具结果并发布 `tool_completed(failed)`、回填模型；取消与等待态语义不变。
2. host tool 等待按审计 `expires_at` 收敛：`awaiting_confirmation` 超时转为 `expired`，`running` 超时转为 `failed`（错误码 `host_tool_execution_timeout`），并补齐取消/超时的 Future 清理。
3. 不修改 REST、SSE、WS 公开事件、数据库模型、鉴权或权限边界；审计终态值（`expired`/`failed`）均为既有合法值。

若不希望 `running` 中的页面工具被服务端打断，可只对 `awaiting_confirmation` 做超时（保守方案），`running` 仍由页面结果/取消/断线结束。

### 剩余风险

- 页面宿主工具可能真实执行超过 10 分钟；若启用 `running` 超时，服务端会在页面仍未完成时返回失败结果，迟到结果被幂等忽略，需要真实环境回归确认体验可接受。
- legacy fallback 语义变化后，需要重跑 conversation/gateway 全量测试确认无既有用例依赖“工具异常即整请求错误”。

## 2026-09-04 阶段 6 调研：持久化与并发

### 调研问题

一个复用型 runtime/连接同时承载多个请求时，事件缓冲、数据库 Session、loop step 顺序、replay/sequence 和终态是否可能出现串流、重复写入或并发操作冲突。

### 参考实现与现状（审计日期：2026-09-04）

- `AgentRuntime` 每次调用创建请求级 `AgentLoop`/hooks（`_new_loop`），流式事件使用请求内独立队列，`persistence_factory(request_id)` 为每个请求提供独立持久化器；并发 `stream()` 测试确认两个请求的事件不会互相串流。
- 数据库 Session 生命周期：REST/SSE 每个请求在 `get_session_factory()` 上下文内独立创建；WS 每个模型请求任务独立创建 Session，host tool 审计使用连接级 Session 且只被对应任务与入站回调串行访问；`AgentLoop` 本身不接触数据库。
- WS 并发请求语义：连接层对第二个不同 requestId 在活跃请求完成前返回 `request_in_progress`（既有协议行为），`RequestRegistry` 按 requestId 幂等注册、完成、失败、取消和预算终态。
- 终态单写：`AgentRunLifecycle` 等待态可恢复、终态只收敛一次；gateway/conversation 收尾对 `loop.status` 与 generation step 只写一次，迟到回调不重复变更。
- 事件缓冲与重放：`BufferedAgentRunPersistence` 请求级顺序记录并去重；WS 事件在发送前写入 Redis replay Stream；sequence 在断线重连后按已重放事件继续递增。
- 生产接线观察：`AgentRunPersistence` 目前是保留 seam，正式数据库写入仍由 conversation/gateway 协议 Adapter 在消费事件流时完成；这满足总目标 8 的“Adapter 或 Persistence 接口注入”中的 Adapter 路径，删除 legacy Graph 时可再评估是否切换为统一 Persistence Adapter。

### 最终决策

阶段 6 以审计为主，不引入行为变更：

1. 维持现有“runtime 事件流 + 协议 Adapter 落库”的接线方式，不把 conversation/gateway 的数据库写入临时迁入 agent_runtime，避免双写。
2. 维持 WS 单活跃请求与 registry 幂等约束；请求级隔离、终态单写与 replay/sequence 语义以定向测试锁定。
3. 阶段 7 再补充 REST SSE 与 WS 灰度入口的自动化兼容验证，最后统一做 REST 人工测试。

### 剩余风险

- `AgentRunPersistence` 尚无真实数据库实现，协议 Adapter 与 runtime 之间的事件快照一致性依赖各 Adapter 自己的幂等实现；删除 legacy Graph 时需评估统一 Persistence Adapter 的收益与双写风险。
- REST SSE 灰度入口没有自动化端到端回归，只有单元层事件转换覆盖；已在阶段 7 计划中补充。

## 2026-09-07 阶段 2 调研：工具状态与终态映射收拢

### 调研问题

阶段 2 的目标是把“工具结果状态、等待态、请求终态、预算终态”的表达与
落库映射收拢到 `agent_runtime` 单点，消除 conversation/gateway 各入口的
重复分支；本轮先盘点 2026-09-04 之后哪些已经收敛、哪些仍有重复实现。

### 现状盘点（本地源码审计，日期 2026-09-07）

已经收敛的集中点：

- `agent_runtime/contracts.py`：`ToolOutcomeStatus`、`ToolOutcome`（含
  resume/audit/confirmation 关联字段）作为工具结果统一契约；
- `agent_runtime/lifecycle.py`：`RunStatus` 全量枚举与
  `resolve_result_run_status()`（等待态优先、预算、失败、成功的固定判断顺序），
  `AgentRunLifecycle` 保证运行/等待态只进入一次明确终态；
- `agent_runtime/tool_events.py`：`normalize_tool_step_status()` 把工具结果
  状态安全映射为 loop step 落库状态（未知默认 failed），conversation 的
  `tool_step_values()` 已复用该单点；
- Gateway `RequestRegistry` 支持预算终态，迟到完成不覆盖预算状态；入站
  确认/问题/宿主工具回调有请求归属闸门。

仍存在的重复实现（本轮拟收敛对象）：

- conversation/services.py `_finish_stream_chat`、execute_chat 非流式收尾段、
  gateway/runtime.py `_finish_embed_chat` 三处重复“结果终态 → 生成步骤
  状态 / loop 状态 / loop 摘要”三元表达式：仅对
  `WAITING_CONFIRMATION` 特殊，其余一律映射为 succeeded/completed/
  “已完成回答”；
- 同一函数内多次重复调用 `resolve_result_run_status()`（同一结果解析
  3 次），存在未来条件分叉后口径漂移的风险。

### 方案比较

1. 维持现状：三处 Adapter 各自推导落库字段。
   优点：零改动；缺点：状态口径散落，新增等待态或预算策略时容易漏改一处，
   与“单点收敛”目标不符。
2. 新增纯函数助手集中推导（推荐）：在 `agent_runtime/lifecycle.py` 增加
   `generation_step_status_for(result_status)`、
   `loop_status_for(result_status)`、`loop_summary_for(result_status)`，
   三个收尾站点统一调用；映射规则完全照搬现有行为（只把
   `WAITING_CONFIRMATION` 映射为 waiting_confirmation，其余保持
   succeeded/completed），不改变 REST/SSE/WS 事件、数据库字段与权限语义。
   优点：口径单点、可测试、零行为变化；缺点：需要改动三个 Adapter 的局部
   代码并补矩阵测试，回归面通过全量核心测试覆盖。
3. 把整个收尾落库段抽成共享 Persistence Adapter：收益最大但会触及
   conversation/gateway 的持久化接线与事件出口，属于阶段 6 已审慎保留的
   高风险双写问题，不在本轮范围。

### 最终决策（待用户确认）

采用方案 2，具体范围：

- `agent_runtime/lifecycle.py` 新增三个导出助手并配中文注释（说明 DB 列取值
  约束、未知/其他等待态由 resolve 阶段提前分流、保持现有落库语义）；
- 替换 conversation/services.py（流式收尾 + 非流式收尾）与
  gateway/runtime.py（_finish_embed_chat）中的重复三元表达式，每个函数只
  调用一次 `resolve_result_run_status()`；
- 新增 `agent_runtime` lifecycle 矩阵测试（RunStatus 全量 → 三类落库字段
  的预期值），并用既有 REST/WS parity 全量回归证明无行为变化；
- 不修改 REST/SSE/WS 公开协议、数据库模型、鉴权与权限边界。

### 剩余风险

- 三个收尾站点若未来出现不同协议语义（例如某入口需要把 waiting_question
  也落为独立 DB 状态），需先在 helper 中扩展而不是在站点局部改；
- host tool 审计状态（`awaiting_confirmation`/`running`/`rejected`）属于
  host tool 领域状态，不属于 Agent 请求 RunStatus，本轮不收拢，避免越界。
