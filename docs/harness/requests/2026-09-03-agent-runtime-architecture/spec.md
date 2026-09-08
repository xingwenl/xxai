# 设计说明

## 目标

- 将 Agent 主循环、工具调用、请求上下文和运行事件抽成可复用的 Python 模块。
- 让 REST 对话和 Embed WebSocket 共享同一套 Agent 行为，协议层只负责输入输出适配。
- 降低 `conversation/runtime.py`、`conversation/services.py` 和 `gateway/router.py` 的职责密度。
- 依据 `research.md`，采用“统一 runtime + 协议 Adapter + 类型化事件/工具调用”的渐进方案。

## 范围

- 新增 `apps/backend/app/modules/agent_runtime/` 作为统一 Agent runtime 的独立模块目录，集中承载内部契约、运行循环、工具执行器和请求上下文。
- 新增或整理 Agent runtime 的请求、结果、事件和工具调用内部接口。
- 合并 `run_graph()` 与 `stream_graph()` 的核心循环，保留流式与非流式两种调用方式。
- 抽离会话/loop 持久化编排，使 REST 与 Embed 复用。
- 将工具来源封装为可注册的执行器，保留 MCP、builtin、skill、host tool 和 ask_user 行为。
- 拆分网关连接状态机与协议适配职责。
- 补充 Agent loop、工具分发和 REST/Embed 一致性测试。

## 非目标

- 本次不替换现有模型供应商、LangChain、MCP 或 Skill Runner。
- 本次不改变数据库表结构、字段、迁移或已有消息/loop 数据格式。
- 本次不改变公开 REST 路径、WebSocket 消息协议和鉴权规则；如实施中必须改变，需单独确认。
- 本次不新增多 Agent 协作、长期记忆或复杂工作流编排。

## 风险

- Agent 事件顺序、loop 状态和工具确认恢复属于高回归风险区域。
- REST 与 WebSocket 对同一内部事件的序列化可能存在兼容差异。
- WebSocket 断连、取消、超时和 Future 清理需要专项测试。
- 动态字典改为类型化对象可能暴露现有隐式兼容行为，需要分阶段保留兼容层。

## 停点判断

- 是否涉及架构边界变化：是，涉及 `conversation`、`gateway` 与 Agent runtime 的职责重新划分。
- 是否涉及数据模型变化：当前设计否。
- 是否涉及 API 契约变化：当前设计否，实施时必须保持兼容。
- 是否涉及鉴权或权限行为变化：当前设计否，工具权限仍由现有 Adapter/Dispatcher 执行。
- 结论：进入 `plan` 和实现前需人工确认本 spec 的边界与核心接口方向。

## 验收标准

- REST 非流式、REST SSE、Embed WebSocket 均通过统一 Agent runtime 执行主循环。
- `run_graph()` 与 `stream_graph()` 不再各自维护重复的工具循环逻辑。
- 工具调用、工具结果、Agent 事件具备明确的类型化内部契约，并有单元测试。
- MCP、builtin、skill、host tool、ask_user 的既有行为和权限约束保持不变。
- 现有 gateway/conversation 测试通过，并新增 REST/Embed 行为一致性测试。
- `ruff`、`compileall` 和后端测试通过；实际结果记录在 `verify.md`。

## 本次增量范围：多工具调用失败收敛

- 当同一模型轮次包含多个工具调用时，普通工具异常和 `status=failed` 结果均作为工具级失败记录，不因单个失败直接跳过同批次后续工具。
- 同批次工具结果全部完成后，统一回填模型；模型可根据成功和失败结果决定最终答复或后续动作。
- 取消、确认等待、用户问题等待和显式不可继续状态保持原有停止语义，不转换为普通工具失败。
- 工具事件顺序保持 `tool_started -> tool_completed`；异常工具必须先发布 `tool_completed(status=failed)`，再由 runtime 负责请求级终态处理。
- 本次不引入工具并行执行，不修改 API 契约、数据库模型、鉴权或权限边界。

## 本次增量范围（阶段 5）：工具执行边界收敛（待确认）

- legacy fallback 与 runtime 灰度对同一工具事件保持一致的边界语义：
  - 未知工具名不再静默跳过，转为 `failed(tool_not_found)` 工具结果并回填模型；
  - 工具回调抛普通异常转为 `failed` 工具结果并继续同批次后续工具，不再把工具错误升级为整请求错误；
  - `CancelledError` 原样传播，不伪装成工具失败；确认等待、ask_user、预算短路语义不变。
- WebSocket host tool 等待有服务端超时：
  - 等待时长沿用 `create_audit` 已写入的 `expires_at`（当前 10 分钟）；
  - `awaiting_confirmation` 超时按既有状态机转为 `expired`；
  - `running` 超时按既有状态机转为 `failed` 并携带 `host_tool_execution_timeout` 错误码；
  - 取消或超时都在 `finally` 中清理 pending Future，迟到页面结果继续由审计幂等逻辑忽略。
- 兼容要求：不修改 REST、SSE、WS 公开事件结构、数据库模型、鉴权与权限边界；`expired`/`failed` 均为既有合法审计终态；灰度开关与 legacy fallback 保留。

## 变更记录

### 2026-09-08 第 13 次变更：收敛为单一 AgentLoopAgentRuntime，删除 legacy（已确认方向）

- 变更原因：三协议入口已完成 AgentRuntime 灰度接入与 parity 自动化，用户
  2026-09-08 确认后续只使用 `AgentLoopAgentRuntime`，legacy Graph 主循环
  （`run_graph`/`_stream_graph`/`stream_graph`）可直接删除，避免双实现口径
  漂移与双份维护，达成总目标第 1 条“Agent 主循环只有一套核心实现”。
- 调研结论：research.md 阶段 8 预研与最终决策（8A–8E 分批）；legacy 仍有
  两处 AgentRuntime 尚未覆盖的真实模型缓解（context-length 降级重试、纯
  文本模型拒图降级）需先“补齐或确认等价”，8A 依赖用户选项甲/乙。
- 变更内容：按 8A–8E 分批实施（见 plan.md 阶段 8）；本记录先锁定方向与分叉，
  待 8A 行为分叉确认后逐批落地。
- 影响章节：范围、验收标准、变更记录。
- 兼容要求：不修改 REST/SSE/WS 公开协议、数据库模型、鉴权与权限边界；灰度
  与 legacy fallback 随批次删除后不再保留第二条主循环。
- 是否触发人工确认：是；方向已确认（删除 legacy、仅 AgentRuntime），行为
  分叉（8A 选项甲/乙）仍待用户拍板。

### 2026-09-07 第 12 次变更：工具状态与终态映射收拢（阶段 2，已确认）

- 变更原因：阶段 2 核心集中点（`RunStatus`、`resolve_result_run_status`、
  `normalize_tool_step_status`、`AgentRunLifecycle`、RequestRegistry 预算
  终态）已收敛，但 conversation 与 gateway 三个收尾站点仍各自重复“结果
  终态 → 生成步骤状态 / loop 状态 / loop 摘要”推导，同一函数内还重复调用
  多次 `resolve_result_run_status()`，状态口径存在漂移风险。
- 调研结论：参考 Pi 无对应领域概念；本项目已具备的集中单点可作为收拢目标。
  本地审计见 research.md“阶段 2 调研”。
- 变更内容：在 `agent_runtime/lifecycle.py` 新增三个纯函数助手
  （`generation_step_status_for` / `loop_status_for` / `loop_summary_for`），
  映射规则严格照搬现有行为（仅 `WAITING_CONFIRMATION` 特殊，其余保持
  succeeded/completed/“已完成回答”）；替换 conversation/services.py
  （流式与非流式收尾）与 gateway/runtime.py（`_finish_embed_chat`）中的
  重复三元表达式，每个函数只调用一次 `resolve_result_run_status()`；新增
  RunStatus 全量矩阵测试，并用全量核心回归证明无行为变化。
- 影响章节：范围、验收标准、变更记录。
- 兼容要求：不修改 REST/SSE/WS 公开事件结构、数据库模型、鉴权与权限边界；
  落库字符串与既有行为逐字一致。
- 是否触发人工确认：是；用户 2026-09-07 查看方案后指示“继续 一步一步来”，
  确认实施。
- 实施结论：lifecycle 三个助手已落地并导出；conversation/services.py 流式
  与非流式收尾、gateway/runtime.py `_finish_embed_chat` 三处站点已改用
  助手并只解析一次 `resolve_result_run_status()`；RunStatus 矩阵测试新增；
  全量核心回归 `307 passed, 1 skipped`，Ruff/compileall/`git diff --check`
  通过，无公开协议或数据库行为变化。
- 关联计划更新：已同步 `plan.md` 阶段 2 实施记录与 `verify.md`。

### 2026-09-07 第 11 次变更：max_turns 边界语义按 Pi/legacy 对齐（已确认）

- 变更原因：REST max_turns 对照测试发现 AgentLoop 与 legacy Graph 的上限
  边界差一轮工具执行：legacy 在达到上限的那次模型响应请求工具时不再执行该
  轮工具（上限 2 只执行 1 轮），AgentLoop 原实现会先执行完该轮再收尾（执行
  2 轮）。差异影响“达到上限那一轮的有副作用工具是否执行”，用户 2026-09-07
  指示参考 Pi 项目对齐。
- 调研结论：Pi `packages/agent/src/agent-loop.ts` 没有硬性最大轮数计数，最
  接近的参考语义是输出达 token 上限截断时（`failToolCallsFromTruncatedMessage`）
  该条响应的全部工具调用不执行，转为失败工具结果回填模型。即预算/上限类
  边界上“新工具不执行”是 Pi 的安全语义，与 legacy Graph 一致。
- 变更内容：AgentLoop 达到 `max_turns` 的那次模型响应若请求工具，该轮工具
  不再执行，逐条转为 `failed(max_turns_reached)` 结果回填上下文并发布失败
  工具事件；随后执行一次收尾模型调用（注入内部提示、`allow_tools=False`）；
  收尾仍返回工具则转稳定失败结果并结束，保持防无限循环。legacy 不记录上限
  轮的调用，灰度会多一条 failed 工具事件，属记录差异（不执行副作用工具这一
  安全语义两路一致）。
- 影响章节：范围、风险、验收标准、变更记录。
- 兼容要求：不修改 REST/SSE/WS 公开事件结构（灰度上限轮新增的是既有合法
  `tool_completed(failed)` 事件）、数据库模型、鉴权与权限边界；`max_turns`
  成功执行上限从 N 轮调整为 N-1 轮（与 legacy 配置语义一致）。
- 是否触发人工确认：是；差异与两个候选方案已向用户说明，用户指示按 Pi
  项目对齐后实施。
- 关联计划更新：已同步更新 `plan.md` 阶段 7 实施记录七。

### 2026-09-06 第 10 次变更：REST 非流式模型错误失败收尾补全（已确认）

- 变更原因：探针确认 `execute_chat`（REST 非流式）在模型错误时灰度与 legacy
  都把异常直接抛给调用方，loop 停留在 running 且没有 failed 的
  model_generation 步骤；流式入口（REST SSE/WS）已有 error 收尾，非流式
  缺口会让会话历史与审计长期停留在“处理中”假象。
- 变更内容：在 `execute_chat` 模型调用段外层捕获普通异常（`CancelledError`
  等 BaseException 不捕获），复用 legacy 错误 payload 构造规则，补写一条
  failed 的 model_generation 步骤并把 loop 更新为 failed 后继续上抛原异常，
  保持 REST 公开错误响应不变；灰度与 legacy 两路共用同一收尾逻辑。
- 影响章节：范围、风险、验收标准、变更记录。
- 兼容要求：不修改 REST/SSE/WS 公开错误响应与事件、数据库模型、鉴权与
  权限边界；只补内部失败状态落库（`loop.status="failed"` 与 failed step
  均为既有合法持久化值）。
- 是否触发人工确认：是；2026-09-05 已向用户说明方案（失败落库补全、两路
  统一收尾、公开错误响应不变），用户 2026-09-06 确认继续实施。
- 关联计划更新：已同步更新 `plan.md` 阶段 7 实施记录六。

### 2026-09-04 第 9 次变更：工具执行边界收敛（阶段 5，待确认）

- 变更原因：legacy `ToolRoundExecutor` 对未知工具静默跳过、对工具异常直接向上传播，与 runtime 灰度路径及 Pi 的“工具失败结果化”语义分叉；host tool 等待页面结果没有服务端超时，页面或确认永不响应时请求可能无界挂起。
- 变更内容：统一 legacy 工具轮归一化语义；host tool 等待按审计 `expires_at` 收敛，取消/超时清理 pending Future。
- 影响章节：范围、风险、验收标准、本次增量范围。
- 是否触发人工确认：是，调整工具轮执行边界与 host tool 等待行为，实现前需用户确认。
- 关联计划更新：待确认后补充 `plan.md` 的测试和实现步骤。

### 2026-09-04 第 6 次变更：工具状态与终态统一（阶段 2，待确认）

- 变更原因：工具、运行生命周期、conversation loop/step 和 gateway 各自维护状态集合，未知状态默认成功，等待态与预算终态缺少统一内部表达。
- 变更内容：在 agent_runtime 集中定义工具状态、等待态和请求终态分类；补充 `cancelled`/`budget_exceeded` 内部值；未知工具状态安全映射为失败；生命周期允许可恢复等待态但只允许一次请求终态；conversation/gateway 通过 Adapter 使用集中映射。
- 兼容要求：不修改 REST、SSE、WebSocket 公开事件名称、数据库模型、鉴权和权限边界；预算终态按现有持久化字符串兼容落库，内部原因保留在事件/结果 metadata。
- 影响章节：范围、风险、验收标准、停点判断。
- 是否触发人工确认：是，调整 AgentRuntime 内部状态契约和跨层终态映射；实现前需用户确认。
- 关联计划更新：待确认后补充状态矩阵、幂等和 continuation 测试计划。

### 2026-09-04 第 7 次变更：模型调用错误收敛（阶段 3，已确认）

- 变更原因：runtime 灰度路径与 legacy Graph 对同一模型异常产生不同错误码/可重试判断，usage 兜底也不一致。
- 变更内容：`error_from_exception` 供应商无关识别上下文超限、HTTP 5xx/502、连接/超时与客户端 4xx；错误详情只暴露状态码与异常类型；usage 归一化补齐 `response_metadata.usage`。
- 兼容要求：不修改 REST、SSE、WebSocket 事件结构、数据库模型、鉴权与权限边界；runtime 路径的错误 code/retryable 与 legacy 语义对齐。
- 是否触发人工确认：是，已确认；错误事件 code 会从笼统失败改为精确分类。

### 2026-09-04 第 8 次变更：runtime 混合上下文护栏（阶段 4，已确认）

- 变更原因：AgentLoop 上下文的 `ToolOutcome` 没有 `content`，legacy 逐条裁剪可能删除 assistant 调用而保留孤立工具结果，回填模型形成非法消息序列。
- 变更内容：新增 `apply_runtime_context_guardrail`，按整轮删除并保护 System、快照与最近一轮；REST/WS runtime 灰度入口切换，legacy Graph 不变。
- 兼容要求：不修改 REST、SSE、WebSocket 事件结构、数据库模型、鉴权与权限边界；护栏裁剪粒度仅影响 runtime 灰度内部上下文。
- 是否触发人工确认：是，已确认。

### 2026-09-04 第 5 次变更：非正最大轮数兼容

- 变更原因：legacy Graph 将 `0`/负数配置解释为不设上限，AgentLoop 原实现会在首轮前直接退出并抛出无模型结果错误。
- 变更内容：AgentLoop 初始化时将非正 `max_turns` 归一化为 `None`，保持 legacy 配置语义。
- 影响章节：风险、验收标准。
- 是否触发人工确认：否，属于已确认最大轮数设计内的兼容性修正，不改变公开协议、数据库或权限边界。

### 2026-09-04 ��� 4 次变更：最大轮数收尾行为

- 变更原因：`AgentLoop` 达到 `max_turns` 后直接返回上一轮；当上一轮仍包含工具调用时，可能没有明确最终回答，且无法区分预算终态。
- 变更内容：达到最大工具轮数后停止执行新工具；注入一次内部收尾提示，使用禁用工具的模型调用生成最终回答；收尾响应若仍返回工具调用，转为不可执行的失败结果并稳定结束，不再循环。
- 影响章节：范围、风险、验收标准、停点判断。
- 兼容要求：不修改 REST、SSE、WebSocket 公开协议、数据库模型、鉴权和权限边界；确认等待、ask_user 和取消优先于预算收尾并保持原语义。
- 是否触发人工确认：是，改变 Agent Loop 内部终态控制；实现前需用户确认。
- 关联计划更新：待确认后补充 `plan.md` 的测试和实现步骤。

### 初始版本

- 时间：2026-09-03
- 变更原因：首次创建 Agent runtime 架构优化 request
- 变更内容：定义统一 runtime、类型化内部契约和协议 Adapter 方向
- 影响章节：全部
- 是否触发人工确认：是，架构边界变化

### 2026-09-03 第 1 次变更

- 变更原因：用户确认统一运行时应使用独立目录，避免继续扩大 `conversation` 与 `gateway` 的职责。
- 变更内容：将新建 `apps/backend/app/modules/agent_runtime/`，现有模块通过兼容适配层调用。
- 影响章节：范围、非目标、验收标准、风险
- 是否触发人工确认：已确认

### 2026-09-04 第 2 次变更：完整模型轮次迁移

- 变更原因：用户确认继续将 legacy Graph 的模型轮次完全迁入 `agent_runtime.AgentLoop`，减少 conversation runtime 对模型循环实现的承担。
- 迁移范围：将模型消息组装、流式/非流式模型调用、工具调用结果回填和轮次终止判断逐步迁入 `agent_runtime`；保留协议 Adapter、数据库持久化和工具权限实现。
- 兼容要求：不修改 REST、SSE、WebSocket 公开契约；不修改数据库模型；不改变 LangChain、MCP、builtin、skill、host tool 和 ask_user 的权限及确认语义。
- 实施策略：先抽取模型消息与模型响应 Adapter，再让 `AgentLoop` 支持流式 chunk、工具调用和 continuation；最后以 feature seam 替换 Graph 调用，保留 legacy fallback。
- 风险：模型消息格式、多轮工具上下文、流式事件时序和 loop 收尾属于高风险区域，必须分阶段实现并在每个阶段运行核心测试。
- 停点：若需要改变公开事件、数据库字段、鉴权/权限或模型供应商调用契约，立即暂停并重新确认。
- 是否触发人工确认：是，用户已确认继续该高风险架构迁移；spec 更新后仍需对齐本增量的具体实现方案。

### 2026-09-04 第 3 次变更：多工具调用失败策略

- 变更原因：发现当前 `AgentLoop` 在第一个工具异常后立即抛出，导致同一模型响应中的其他独立工具不会执行；需要参考 Pi 收敛工具级错误与批次终止语义。
- 变更内容：采用批次尽力完成策略；普通异常转换为失败工具结果并继续同批次工具；取消和等待类状态继续保持终止/暂停语义；不引入并行执行。
- 影响章节：范围、风险、验收标准、本次增量范围
- 是否触发人工确认：是，涉��� Agent Loop 行为和架构边界；实现前需确认
- 关联计划更新：用户确认后同步更新 `plan.md`，补充失败、取消、等待和多工具顺序测试。
