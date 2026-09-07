# 实施计划

## 变更文件

## 进度表

| 阶段 | 状态 | 结果 |
|---|---|---|
| 调研与方案确认 | 已完成 | 已参考 LangChain、FastAPI、AutoGen、PydanticAI 和本地 Pi 项目 |
| agent_runtime 基础契约 | 已完成 | request、event、tool call/outcome、hooks、context 已建立 |
| 工具与消息适配 | 已完成 | ToolDispatcher、LangChain Adapter、旧事件双向适配已建立 |
| WebSocket 生命周期 | 已完成 | 取消事件、失败、断线清理和 replay 已统一并补充回归测试 |
| AgentLoop 接管 WebSocket | 已完成（灰度） | WS 灰度已接入 AgentRuntime 并完成 max_turns、confirmation、ask_user、cancel 的事件流 parity 自动化；legacy Graph 保留为 fallback |
| REST 入口迁移 | 已完成（灰度） | REST 非流式与 REST SSE 已接入 AgentRuntime 灰度并完成 parity 自动化；真实人工测试按用户要求延后 |
| 全量验证与验收 | 进行中 | 后端自动化 `307 passed, 1 skipped`；最终验收等待用户执行 REST 人工测试 |

## 后续执行队列

1. ~~取消事件与状态收敛~~（已完成：统一取消 error 事件并补测试）。
2. ~~WebSocket AgentLoop 兼容接入~~（已完成：WS 灰度接入 AgentRuntime，Embed 事件适配不变；runtime 终态去重与取消兼容已落地）。
3. ~~工具确认、ask_user、取消和断线专项回归~~（已完成：自动化 parity + 用户真实验证）。
4. ~~REST 非流式与 SSE 入口迁移~~（已完成灰度接入与 parity 自动化；真实人工测试延后）。
5. ~~SDK/后端全量验证~~（已完成后端自动化部分：`307 passed, 1 skipped`；SDK 自动化此前已通过）。
6. 完成 `verify.md`、`acceptance.md` 和 request 状态更新（进行中：文档随增量持续更新，最终状态等人工测试反馈）。

## 本轮执行记录

| 步骤 | 结果 | 验证或结论 |
|---|---|---|
| 取消事件标准化 | 已完成 | `AgentLoop` 在 `cancel_event` 触发时先发布标准 `error/agent_request_cancelled`，再抛出 `CancelledError` |
| WS task cancellation 兼容 | 已完成 | `produce_embed_request` 补发同一稳定取消错误并保留 Future 清理流程 |
| runtime 终态去重 | 已完成 | 已避免 loop 取消事件与异常捕获重复持久化 |
| WS AgentLoop 接入点梳理 | 已完成 | 当前真实 seam 是 `gateway.runtime.stream_embed_chat` 中的 `stream_graph`；其内部同时承担模型流、工具轮次、确认态和 GraphResult 收尾，需按阶段拆 Adapter |
| WS 兼容 Adapter 设计 | 已完成 | `LegacyGraphEventAdapter` 已接入 Gateway 真实事件路径，保持旧事件和 GraphResult 行为不变 |
| Gateway 事件转换迁移 | 已完成 | Gateway 不再直接拼接事件双向转换，统一通过 Adapter 转换单事件 |
| 模型原生流 Adapter | 已完成 | 新增 `ModelStreamAdapter` 统一顺序消费模型 chunk；暂不改变工具确认、数据库 loop step 和 GraphResult 收尾 |
| conversation 模型流接入 | 已完成 | `_astream_collect` 已通过 `ModelStreamAdapter.stream` 消费模型流，保持图片降级、thinking、正文和 usage 行为不变 |
| 工具调用兼容 Adapter | 已完成 | 工具轮次先统一为 `ToolCall` 的 id/arguments，再保留旧回调的完整字段，确认、ask_user、MCP 和 host tool 语义不变 |
| 工具结果兼容契约 | 已完成 | `ToolOutcome` 已承载 confirmation/audit/metadata，旧结果转换不再丢失确认恢复信息 |
| Gateway ToolExecutor 兼容包装 | 已完成 | `RuntimeToolDispatcher` 已实现 `supports/execute` 接口，可作为统一 ToolExecutor 注册，原有权限、确认和审计行为未改变 |
| Gateway ToolDispatcher 实际接入 | 已完成 | 普通工具已走 `ToolDispatcher.execute`，MCP 特殊调用保留原分支，全链路回归通过 |
| 工具结果事件统一 | 已完成 | `ToolDispatcher` 返回前统一旧对象/字典为 `ToolOutcome`，保留协议层字段、确认 ID 和审计 ID |
| 工具事件构造统一 | 已完成 | Graph 工具轮次复用统一的基础/完成事件构造函数，旧事件字段和等待状态兼容 |
| AgentLoop 等待态收敛 | 已完成 | confirmation_required/waiting_user 工具结果暂停当前 loop，并通过 pending_tool_outcome 交由 continuation 恢复 |
| AgentLoop continuation | 已完成 | 新增 `continue_run()`，只注入已完成工具结果并恢复模型调用，不重复执行工具，暂不改变 WS 协议 |
| AgentRuntime continuation 门面 | 已完成 | 对外暴露 `continue_run()`，复用统一事件、持久化和取消链路，协议层不直接依赖 AgentLoop |
| Gateway 恢复结果标准化 | 已完成 | 现有 WS confirmation/ask_user 采用连接级 Future 在同一 Graph task 内恢复；Dispatcher 已将恢复后的工具结果统一转换为 `ToolOutcome`，无需额外重启 task |
| WS 断线/取消状态回归 | 已完成 | 现有断线、取消、Future 清理、请求终态幂等和工具恢复测试均通过 |
| WebSocket Graph runtime 桥接 | 已完成 | `LegacyGraphRuntimeBridge` 已接入 Gateway，承接旧 Graph 调用与事件转换，Gateway 仅消费 AgentEvent |
| GraphResult 统一结果适配 | 已完成 | 新增 `agent_result_from_legacy`，统一内容、引用、工具事件、usage 和 pending confirmation |
| 完成事件结果接入 | 已完成 | Bridge 在 completed 事件中附加统一 `AgentResult`，保留旧 result 字段供现有收尾逻辑兼容 |
| Gateway 统一结果收尾 | 已完成 | Gateway 已优先读取 `AgentResult`，旧 GraphResult 作为 fallback，收尾字段完整兼容 |
| REST/SSE 结果适配梳理 | 已完成 | 已确认非流式 GraphResult 仍保持公开响应；SSE 流已通过 Graph runtime bridge 统一事件转换 |
| REST 非流式统一结果 | 已完成 | Router 已将 `execute_chat` 结果转换为 `AgentResult`，公开 ChatResponse 字段和 loop 查询行为不变 |
| SSE 统一结果收尾 | 已完成 | SSE 完成事件优先读取 `AgentResult`，保留 legacy fallback，公开事件契约不变 |
| Python 编译与核心验证 | 已完成 | compileall 通过；核心测试 211 passed、1 skipped；Ruff 通过；结果已记录 verify.md |
| SDK 全量验证 | 已完成 | SDK 测试 99 passed；type-check 和 build 均通过 |
| Harness 审计 | 已完成 | 本 request 无新增审计问题；仓库既有历史 ERROR/WARN 已记录于 verify.md，未修改无关 request |
| 验收文档准备 | 已完成 | 已新增中文 acceptance.md，明确已完成项与 REST/完整 loop 剩余项 |
| WS 真实回归准备 | 已完成 | 用户确认普通对话、工具、confirmation、ask_user、取消和断线恢复均正常 |
| REST/SSE 自动回归 | 部分完成 | 核心 conversation 测试已通过；全量 pytest 因仓库既有同名测试模块 collection 冲突中断，未修改无关测试 |
| REST 非流式人工验证 | 已完成 | 用户提供真实接口响应，conversation/message/loop/steps/content 均正常 |
| REST SSE 人工验证 | 已完成 | 用户提供完整 SSE 样本，事件从 agent_loop_started 到 message_completed 顺序正常 |
| Graph 双路径循环收敛检查 | 已完成 | `run_graph` 与 `stream_graph` 已共同复用 `_execute_tool_round` 和 `_finish_tool_loop`，不存在两套工具轮次实现；下一步聚焦将这两个共享函数迁入 agent_runtime |
| 工具轮次状态契约迁移 | 已完成 | `_ToolRoundResult` 已改为复用 `agent_runtime.ToolRoundState`，执行逻辑和协议收尾保持不变 |
| 工具轮次迁移边界分析 | 已完成 | `_execute_tool_round` 仍耦合 GraphResult、LangChain ToolMessage 和旧回调；直接搬迁会扩大 runtime 接口，下一步采用窄回调接口拆分 |
| 窄接口工具轮次执行器 | 已完成 | 新增 `ToolRoundExecutor`，只依赖 ToolCall/ToolOutcome；消息追加与 confirmation 收尾通过回调注入，并已测试等待态短路 |
| conversation 工具轮次接入 | 暂缓 | 试接入暴露了旧生成器的惰性执行约束；已回退主链路，`ToolRoundExecutor` 保留为独立能力，待设计惰性 async-generator seam 后再迁移 |
| 惰性工具轮次接口 | 已完成 | `ToolRoundExecutor.stream()` 已支持惰性执行、backpressure 和关闭即取消，tool_started 后才执行工具 |
| conversation 工具轮次实际迁移 | 已完成 | 已使用惰性 `ToolRoundExecutor.stream()` 替换旧工具循环，兼容 ToolOutcome 序列化、legacy call 字段、预算终止和 Graph 收尾 |
| 完整模型轮次迁移 | 进行中 | 用户确认增量 spec；先实现模型响应/流式 Adapter，再扩展 AgentLoop，最后替换 Graph 主入口 |
| 模型响应 Adapter | 已完成 | LangChain AIMessage 的 content/tool_calls/usage 与 ToolOutcome 回填已统一，保留 legacy fallback；Agent runtime 测试 48 passed |
| AgentLoop 流式模型调用 | 已完成 | LangChainModelInvoker 支持显式 streaming 模式并逐 chunk 发布 message_delta，默认 ainvoke 路径保持不变；runtime 测试 49 passed |
| LangChain runtime 组合入口 | 已完成 | 新增 `AgentRuntime.from_langchain()` 工厂，供 REST/WS 组合根渐进接入；runtime 测试 50 passed |
| REST 非流式 AgentRuntime 分支 | 进行中 | 增加显式 feature flag 分支，默认 legacy Graph，先验证统一 loop 的结果兼容 |
| LangChain 消息上下文 Builder | 已完成 | 新增 `build_langchain_messages`，统一 system/history/user 顺序和附件注入；runtime 测试 51 passed |
| conversation 消息组装接入 | 已完成 | `_build_initial_messages` 已复用 runtime Builder，核心测试 216 passed、1 skipped |
| REST 非流式 AgentRuntime 分支 | 已完成 | `execute_chat(use_agent_runtime=False)` 已提供默认关闭的可回滚分支，统一 runtime 结果转换回 GraphResult，核心回归通过 |
| AgentRuntime 分支专项测试 | 已完成 | AgentRuntime/LangChain 普通回答、流式 chunk、工具调用、结果转换均有独立测试；默认开关仍关闭 |
| REST AgentRuntime 灰度开关 | 已完成 | 新增 `AGENT_RUNTIME_ENABLED` 内部配置，默认关闭；REST 非流式可本地灰度启用，不改变公开 API |
| REST AgentRuntime 灰度真实回归 | 已完成 | 用户确认开启 `AGENT_RUNTIME_ENABLED` 后 REST 普通对话正常，loop/技能步骤/完成状态正确 |
| REST AgentRuntime 工具回归 | 已完成 | 用户确认 get_runtime_info 工具 step、结果回填、后续模型生成和 loop completed 均正常 |
| REST SSE AgentRuntime 灰度 | 进行中 | 新增 runtime -> conversation 事件适配层，保持默认 legacy Graph，待自动化通过后进行真实 SSE 验证 |
| AgentRuntime 流式最终结果 | 已完成 | 完成事件已补齐 usage/tool_events 元数据，runtime 测试 51 passed |

### 本轮新增执行记录

| 步骤 | 状态 | 结果 |
|---|---|---|
| 更新增量迁移状态 | 已完成 | 将 request 从历史验收状态恢复为 implement/active，避免计划状态与实际代码不一致 |
| REST SSE runtime 事件适配设计 | 已完成 | runtime 只输出供应商无关事件，conversation 负责数据库 loop step 和公开 SSE 收尾 |
| REST SSE runtime 灰度实现 | 已完成 | 接入 `AGENT_RUNTIME_ENABLED`，默认仍保留 legacy Graph fallback；新增事件适配器和回归测试 |
| REST SSE runtime 自动验证 | 已完成 | Ruff 通过；agent_runtime + conversation 测试 138 passed；compileall 通过 |
| REST SSE runtime 真实验证 | 已完成 | 用户确认 `message_completed` 正常返回，conversation/message/loop completed 均正确；runtime 灰度链路闭环 |
| WebSocket AgentRuntime 灰度接入 | 进行中 | 复用连接级工具权限、确认、取消和 replay，默认保留 legacy Graph fallback |
| WebSocket AgentRuntime 自动验证 | 已完成 | Gateway + agent_runtime 测试 131 passed、1 skipped；Ruff 通过 |
| WebSocket 断线重连前端渲染问题 | 延后 | 已定位为 SDK/server sequence 与 replay 状态恢复专项；暂不阻塞 runtime 架构迁移，后续单独修复并真实回归 |
| 确认拒绝与迟到回调状态一致性 | 已完成 | 补充确认拒绝只转换一次、pending Future 只完成一次，以及终态审计忽略迟到 confirmation/host result 的回归测试 |
| 流式运行时观测钩子统一 | 已完成 | 修复 `AgentRuntime.stream()` 未执行原始 `on_event` 的分叉，流式与非流式现在共享观测/审计钩子 |
| 请求级持久化隔离 | 已完成 | 新增可选 `persistence_factory`，长生命周期 runtime 并发请求可获得独立事件缓冲/存储 Adapter，保留旧单实例注入兼容 |
| 流式异常与终态收敛 | 已完成 | 修复模型首事件前异常导致的永久等待，并处理 task/queue 同时完成时的尾事件丢失；异常兜底事件也统一经过观测钩子 |
| 调用期间取消收敛 | 已完成 | 模型/工具等待统一支持 cancel_event 竞争等待，长时间运行的工具可被及时中断并只发布一个标准取消事件 |
| continuation 快照去重 | 已完成 | 恢复快照已包含同一工具结果时不重复追加；按对象身份判断，保留同一 call_id 的重试结果 |
| continuation 结果状态映射 | 已完成 | `AgentResult` 正确暴露等待确认工具的 `pending_confirmation_id`，避免中间终态被误报为普通完成 |
| continuation 元数据累积 | 已完成 | 新增可选 `prior_result`，按显式语义累加 usage、拼接 tool_events，并由当前结果覆盖旧 pending 状态 |
| 工具错误结果统一 | 已完成 | legacy callback、dict 和 ToolOutcome 统一通过同一 Adapter，保留 failed error、resume_token、call_id 等关键字段 |
| 工具异常事件统一 | 已完成 | 工具抛异常时先发布标准 `tool_completed(status=failed)`，并继续同批次工具；取消不伪装成工具失败 |

### 2026-09-04 第 3 次增量计划：多工具调用失败收敛

| 步骤 | 状态 | 结果 |
|---|---|---|
| Pi 多工具失败策略调研 | 已完成 | 确认普通工具异常应转换为错误工具结果；同批次后续工具继续执行；取消和等待类状态单独处理 |
| 方案写入 research/spec 并完成确认 | 已完成 | 用户确认继续按“批次尽力完成”方案实现 |
| 调整 AgentLoop 工具异常控制流 | 已完成 | 普通异常发布失败工具事件后继续同批次工具；取消、确认等待和用户等待保持短路 |
| 补充多工具失败/取消/等待回归测试 | 已完成 | 覆盖异常后续调用、显式 failed 回填、事件顺序和取消不伪装失败 |
| 运行核心测试和静态检查 | 已完成 | 核心回归 241 passed、1 skipped；Ruff 和 compileall 通过 |
| 更新验收结论 | 已完成 | 已同步 `verify.md` 和 `acceptance.md`，断线重连前端渲染继续延期 |

### 下一步

1. 用户开启 `AGENT_RUNTIME_ENABLED=true`，真实调用 REST SSE 普通对话。
2. 再验证 REST SSE 工具调用，核对 `tool_call`、`tool_result`、`message_delta`、`message_completed` 顺序及 sequence 连续性。
3. WebSocket AgentRuntime 灰度接入与自动化验证。
4. 用户真实回归 WS 普通对话、工具、确认、取消、断线恢复和 replay。

### 2026-09-04 第 4 次增量计划：最大轮数收尾行为

1. [已完成] 在 AgentLoop 测试中锁定预算触发、收尾提示、禁用工具、收尾再次返回工具调用和事件顺序。
2. [已完成] 为模型调用契约增加内部 `allow_tools` 收尾模式；LangChain Adapter 收尾轮使用未绑定工具模型。
3. [已完成] 达到 `max_turns` 且最近轮有工具调用时注入一次收尾提示；收尾工具调用转为稳定失败终态，不再循环。
4. [已完成] 运行 AgentRuntime、conversation、gateway 核心测试及 Ruff、compileall、`git diff --check`，并更新验证与验收记录。
5. [已完成] 未新增公开事件、数据库字段、权限判断或供应商公开契约；旧模型调用器保留兼容回退。

补充修正：收尾模型的 `allow_tools` 兼容判断改为签名反射，避免捕获模型内部 `TypeError` 后重复发起供应商请求。

补充修正：非正 `max_turns` 归一化为不设上限，与 legacy Graph 的 `AGENT_MAX_ITERATIONS` 语义保持一致。

### 阶段 2 实施进度

1. [已完成] `ToolOutcomeStatus` 补充 `cancelled`、`budget_exceeded`；`RunStatus` 补充等待确认/等待用户/等待问题和预算终态。
2. [已完成] `AgentRunLifecycle` 将等待态视为可恢复中间态，终态仍保持单次幂等收敛。
3. [已完成] `normalize_tool_step_status` 集中覆盖成功、等待、失败、过期、拒绝、取消和预算状态；未知状态默认失败。
4. [进行中] 检查并替换 conversation/gateway 的重复终态映射与迟到回调处理。

阶段 2 当前进展：已将 conversation 工具步骤的取消/预算状态展示和错误字段接入统一映射；终态幂等与迟到回调仍待继续收敛。

阶段 2 新进展：新增 `resolve_result_run_status()` 作为 REST/SSE/WS 收尾共享解析函数，conversation 与 gateway 不再分别判断完成/确认状态；迟到回调和 lifecycle 写入保护仍待专项检查。

阶段 2 新进展：`RequestRegistry` 新增预算终态入口，预算耗尽后迟到的 `complete()` 不会覆盖内部 `budget_exceeded` 状态；下一步继续检查事件流与确认/host 回调的终态闸门。

边界审计结论：未将 `budget_exceeded` 新增字段写入 WebSocket `message_completed` payload，避免改变公开协议；预算原因继续保留在 AgentResult/loop 内部状态，协议 Adapter 使用既有兼容事件。

阶段 2 新进展：confirmation、ask_user、host tool 入站回调新增请求归属校验：消息显式携带的 requestId 与当前活跃请求不一致时不唤醒等待 Future，也不更新审计；缺失 requestId 的旧客户端保持兼容。

阶段 2 新进展：新增协议层回归，锁定“工具失败只影响工具 step，不把整个 Agent 请求错误升级为 failed”；最终 loop 仍 completed、生成 step 仍 succeeded。

### 阶段 3 实施进度：模型调用错误收敛

1. [已完成] `error_from_exception` 与 legacy 错误分类对齐：上下文超限、HTTP 5xx/502、连接/超时、客户端 4xx。
2. [已完成] runtime 错误 details 保持安全，只暴露状态码与异常类型。
3. [已完成] runtime usage 归一化补齐 `response_metadata.usage` 兜底。
4. [已完成] 新增空内容模型结果与 invalid tool call 不进入执行契约的锁定测试。
5. [已完成] 运行核心回归、Ruff、compileall 与 `git diff --check` 并记录结果。

### 阶段 4 实施进度：上下文与消息构建

1. [已完成] 盘点两条入口的消息组装与 legacy 护栏对 runtime 混合上下文的处理。
2. [已完成] 证据测试：legacy 逐条裁剪会把工具结果与其 assistant 调用拆散。
3. [已完成] 新增 `apply_runtime_context_guardrail`，按整轮删除并保护 System、快照与最近一轮。
4. [已完成] REST/WS AgentRuntime 灰度入口切换新护栏，legacy Graph 不变。
5. [已完成] `_messages_chars` 支持 `ToolOutcome` 估算，并运行完整回归。

### 阶段 5 实施进度：工具执行边界（已确认并完成）

1. [已完成] 盘点工具来源与两条工具轮路径：runtime 灰度 `AgentLoop` 内联执行；legacy fallback `ToolRoundExecutor`（conversation `_execute_tool_round` 共用）；host tool/确认/ask_user 等待均在 `gateway/dispatcher.py`。
2. [已完成] 审计结论：
   - 权限边界未绕过：`agent_runtime` 只通过注入的 `tool_invoker`/`ToolDispatcher` 调用，权限、确认、审计仍由 gateway Dispatcher/Adapter 负责；
   - runtime 主路径已达标的项：未知工具返回失败结果、普通异常结果化并继续同批次、取消不伪装失败、等待态短路、confirmation/回调请求归属校验、continuation 不重复执行已完成工具；
   - legacy fallback 缺口：未知工具静默跳过、工具异常升级为整请求错误，与 runtime/Pi 语义分叉；
   - host tool 缺口：页面结果/确认等待无服务端超时；取消路径缺少 `finally` 清理。
3. [已完成] `ToolRoundExecutor` 统一归一化语义：未知工具与普通异常转为 `failed` 工具结果并回填模型；等待态/预算短路与取消传播不变。
4. [已完成] host tool 等待按审计 `expires_at` 收敛：`awaiting_confirmation -> expired`、`running -> failed(host_tool_execution_timeout)`；取消/超时 `finally` 清理 pending Future。
5. [已完成] 补充测试：未知工具不再静默跳过；工具异常结果为失败且后续工具仍执行；取消不产生失败工具事件；host tool 等待超时/取消清理；迟到页面结果幂等忽略；既有 confirmation/ask_user/cancel 回归。
6. [已完成] 更新 `verify.md` 与 `acceptance.md`，运行 agent_runtime/conversation/gateway 全量回归、Ruff、compileall 与 `git diff --check`。

阶段 5 实现记录：用户按推荐方案确认（2026-09-04），host tool `running` 等待也启用服务端超时。
- 变更文件：`agent_runtime/tool_loop.py`、`agent_runtime/tool_events.py`、`gateway/dispatcher.py`。
- 新增测试：`tests/agent_runtime/test_tool_loop.py`（未知工具/异常归一化/取消传播/流式失败事件）、`tests/agent_runtime/test_tool_events_result.py`（失败结果文本回填）、`tests/gateway/test_host_tool_timeout.py`（running/确认超时、取消清理、竞争恢复）、`tests/conversation/test_runtime.py`（legacy 未知工具失败结果化）。

### 阶段 6 实施进度：持久化与并发（审计完成，无代码变更）

1. [已完成] 审计 runtime 请求隔离：`_new_loop` 请求级 hooks、流式队列按请求独立、`persistence_factory(request_id)` 提供请求级持久化器；并发流测试已锁定事件不串流。
2. [已完成] 审计 AsyncSession 生命周期：REST/WS 每个请求独立 Session，AgentLoop 不触碰数据库；host tool 审计连接级 Session 由入站回调串行访问。
3. [已完成] 审计 WS 请求语义：连接层单活跃请求 + `request_in_progress` 既有协议行为；`RequestRegistry` 幂等注册与完成/失败/取消/预算终态。
4. [已完成] 审计终态单写与事件顺序：`AgentRunLifecycle` 终态只收敛一次；Buffered persistence 请求级去重；replay 在发送前 append，sequence 断线续接有测试。
5. [已完成] 结论：持久化接线采用“runtime 事件流 + 协议 Adapter 落库”，`AgentRunPersistence` 作为保留 seam；阶段 6 无需行为变更，进入阶段 7 跨入口灰度兼容验证。

### 阶段 7 实施记录（2026-09-05）：REST 非流式与 REST SSE 灰度 parity 自动化

背景：WS 灰度 parity 已补自动化，但 REST 服务层两个入口（`execute_chat` /
`stream_chat`）仍只有人工样本记录。本次用替身仓库直接驱动服务层，对照
legacy Graph 与 AgentRuntime 灰度分支，发现并修复以下灰度内部缺陷：

1. `execute_chat` 灰度结果 `knowledge_grounded` 恒为 False；legacy 在存在
   检索引用时为 True。修复：按“runtime 引用或本轮检索引用”回填，保持
   ChatResponse 与 assistant 消息落库语义一致。
2. 灰度工具事件缺少工具分类与参数：loop step 全部落为 `host_tool` 且
   `input_summary` 为空，工具快照参数丢失。修复：`AgentLoop` 工具事件透出
   `tool_type`/`arguments`；LangChain Adapter 在模型返回工具调用时按工具
   注册表补齐分类；conversation 持久化层在缺少 `input_summary` 时按参数
   生成同口径摘要。
3. 非流式灰度结果未做图片 URL 改写与 image/custom content_blocks 组装，
   与 legacy `run_graph` 收尾不一致。修复：灰度 `execute_chat` 复用
   `rewrite_image_markdown`/`image_content_blocks`/`custom_content_blocks`。
4. 流式灰度 fallback GraphResult 未改写图片 URL。修复：conversation 与
   gateway 的 runtime completed fallback 均复用 legacy 收尾改写。

变更文件：
- `agent_runtime/langchain_adapter.py`：`model_turn_from_message` 按注册表
  补齐 `ToolCall.tool_type`。
- `agent_runtime/loop.py`：`_tool_event_entry`/`_tool_call_payload` 统一携带
  `tool_type`/`arguments`；TOOL_COMPLETED payload 同步补齐。
- `agent_runtime/conversation_adapter.py`：tool_started 优先使用 runtime
  工具分类，缺失时按 host_tool 回退。
- `conversation/runtime.py`：`tool_step_values`/`build_tool_snapshots` 对
  runtime 参数做摘要回退。
- `conversation/services.py`：非流式灰度收尾（knowledge_grounded、图片改写、
  content_blocks）与流式 fallback 改写。
- `gateway/runtime.py`：completed fallback 图片改写与 legacy 对齐。

新增测试：
- `tests/conversation/test_rest_parity.py`：非流式普通回答/工具轮 parity、
  流式事件序列与结果 parity、runtime 参数摘要落步骤与快照。
- `tests/agent_runtime/test_langchain_adapter.py`：工具类型随注册表归一化。
- `tests/agent_runtime/test_conversation_adapter.py`：tool_started 工具分类
  透传与 host_tool 回退。

### 阶段 7 实施记录（2026-09-05 二）：灰度 thinking/reasoning 文本 parity

背景：legacy Graph 流式逐 chunk 发布 `thinking_delta` 并在 GraphResult 中
合并全部轮次思考文本；AgentRuntime 灰度路径从不发布思考事件，非流式与流式
的 `thinking_text` 均为空，思考模型在灰度开关下出现展示与持久化差异。

1. 新增 `agent_runtime/message_text.py`，收口正文与思考文本提取规则：
   - `extract_text_content`：兼容字符串与 text 类型内容块；
   - `extract_thinking_text`：兼容 additional_kwargs 的 reasoning_content/
     reasoning/reasoning_details 与 content 中的 thinking/reasoning 块。
2. conversation legacy `_thinking_text` 改为委托同一实现，避免两条路径规则
   漂移。
3. LangChainModelInvoker：
   - 流式：逐 chunk 提取正文与思考，分别发布 `message_delta`/
     `thinking_delta`，并把思考累积进 ModelTurn metadata；
   - 非流式：从 ainvoke 响应提取思考写入 metadata；
   - `model_turn_from_message` 对 content 列表提取 text 块，不再输出
     Python repr。
4. AgentLoop：思考文本按轮累积（工具轮 + 最终轮）；COMPLETED payload 与
   AgentResult 均带完整 `thinking_text`。
5. 入口收尾：REST 非流式 GraphResult、REST SSE 与 WS 的 completed fallback
   均从 runtime 结果/事件补齐 `thinking_text`。

变更文件：`agent_runtime/message_text.py`（新增）、`langchain_adapter.py`、
`loop.py`、`runtime.py`、`conversation/runtime.py`、`conversation/services.py`、
`gateway/runtime.py`。

新增测试：LangChain Adapter 流式/非流式思考提取、AgentLoop 跨工具轮思考
累积、AgentRuntime 结果与 completed 事件、REST 非流式与流式思考 parity。

### 阶段 7 实施记录（2026-09-05 三）：REST SSE astream 工具轮 parity

背景：REST SSE 灰度此前只验证了无工具正文流，工具轮在 astream 场景的事件
顺序、步骤字段与快照尚未自动化对照。实现前用 LangChain `tool_call_chunks`
累加探针确认 chunk 可正确还原 `tool_calls`，再补服务层对照测试。

发现的差异与修复：

- conversation Adapter 序列化工具参数使用带空格的默认 JSON 且不截断；
  legacy 事件使用紧凑 JSON 且上限 300 字符，两个入口会写出不同的
  `input_summary`。修复：Adapter 复用 `agent_runtime.tool_events` 的
  `summarize_tool_value(arguments, limit=300)`，与 legacy 同口径。

新增测试：

- `tests/conversation/test_rest_parity.py::test_stream_chat_gray_tool_round_events_and_steps_match_legacy`
  ：astream 首轮工具调用、次轮正文的灰度/legacy 对照，校验事件类型序列、
  tool_call/tool_result payload、持久化 loop step（含 input_summary）、
  最终内容与工具快照（忽略写入时间戳）。

### 阶段 7 实施记录（2026-09-05 四）：REST 确认/等待态灰度收尾 parity

背景：确认等待（confirmation_required）在灰度下没有 legacy 的终态收尾：

- 非流式 `execute_chat` 的 GraphResult 未透出 `pending_confirmation_id`，
  工具步骤与 model_generation 步骤丢失，loop 停留在 running；
- AgentLoop 等待态提前返回时未把 tool_events/thinking 挂到结果 metadata，
  AgentResult 工具事件为空；
- REST SSE 灰度事件流在 confirmation_required 后直接结束，没有
  agent_step_completed/agent_loop_completed/completed 收尾事件。

修复：

1. AgentLoop 等待态返回前把已执行工具事件与思考文本挂到 `last_turn.metadata`，
   保持 runtime 结果完整；不改动等待态事件流（仍不发布 completed，WS 既有
   恢复语义不受影响）。
2. `execute_chat` 灰度 GraphResult 透出 `runtime_result.pending_confirmation_id`。
3. conversation Adapter 的 tool_completed 透出 `tool_type`/`arguments`，供
   提前收尾时重建工具事件与快照。
4. `stream_chat` 在灰度 confirmation_required 后调用 `_finish_stream_chat`
   合成等待态 GraphResult，产出与 legacy 相同的步骤/loop/完成事件序列。
5. completed fallback GraphResult 支持 `pending_confirmation_id` 字段。

新增测试：`test_execute_chat_gray_confirmation_waiting_matches_legacy`、
`test_stream_chat_gray_confirmation_waiting_terminates_like_legacy`，并扩展
AgentLoop/AgentRuntime 等待态结果断言。

### 阶段 7 实施记录（2026-09-05 五）：REST SSE/WS 流式模型错误收尾 parity

背景：探针对照发现灰度流在模型级错误（如首事件前失败）时与 legacy 分叉：

- legacy `stream_graph` 把模型异常转成终止 `error` 事件，服务层据此把
  loop 与 model_generation 步骤落为 failed，并向 SSE/WS 发送稳定终态；
- 灰度 `AgentRuntime.stream` 只把模型错误写入 persistence/观测 hook 后直接
  向协议层抛异常，事件流中断，loop 与生成步骤停留在 running，SSE 前端
  收到的是连接中断而不是 error 事件。

修复：

1. `AgentRuntime.stream` 在任务异常且该错误尚未表达为事件时，先发布标准
   `error` 事件再正常结束事件流，与 legacy `stream_graph` 的“错误以事件
   终结”契约一致；取消（`CancelledError`）与已发布过错误事件的场景保持
   原有异常传播/正常结束语义，不吞掉取消。
2. REST SSE（`conversation/services.py`）与 WS（`gateway/runtime.py`）既有的
   error 收尾分支随后统一生效：生成步骤与 loop 落为 failed、发送协议 error。

新增测试：

- `test_runtime_stream_invokes_hook_for_fallback_model_error`（契约更新）与
  `test_runtime_stream_cancellation_still_propagates`（取消不受影响）；
- `test_stream_chat_gray_model_error_terminates_like_legacy`：REST SSE 灰度
  事件序列、error payload（code/message/retryable）与落库状态对照 legacy；
- `test_embed_stream_runtime_gray_sends_terminal_error_and_marks_loop_failed`：
  WS 灰度开启时模型错误以 error 事件收尾并落库 failed；
- `test_execute_chat_gray_model_error_propagates_like_legacy`：REST 非流式两路
  均向调用方抛出同一异常（非流式失败落库缺口为两路共有的既有行为，留待
  后续增量，不属于灰度回归）。

### 阶段 7 实施记录（2026-09-06 六）：REST 非流式模型错误失败落库补全

背景：上一增量探针发现 `execute_chat`（REST 非流式）在模型错误时把异常
直接抛给调用方，loop 停留在 running 且没有 failed 的 model_generation
步骤；流式入口（REST SSE/WS）已有 error 收尾，非流式缺口是灰度与 legacy
两路共有的既有行为（非灰度回归），会让会话历史与审计长期停留在“处理中”。

修复（2026-09-06，方案 2026-09-05 已说明、用户确认继续）：

1. 把 execute_chat 的模型调用段抽为 `_run_execute_chat_model_round`：灰度
   runtime 与 legacy Graph 共用同一份上下文组装参数，分叉只留在循环执行器。
2. execute_chat 外层捕获普通异常（`CancelledError` 属 BaseException 不捕获），
   复用 legacy `build_agent_error_payload` 构造失败步骤与 loop 收尾：补写
   failed 的 model_generation 步骤、loop 更新为 failed 后继续上抛原异常，
   REST 公开错误响应不变。
3. 灰度与 legacy 共用同一收尾代码，错误 payload 落库内容完全一致。

新增/更新测试：`test_execute_chat_gray_model_error_propagates_like_legacy`
断言两路仍抛出同一异常，且 loop/生成步骤均落 failed、error payload 一致。

### 阶段 7 实施记录（2026-09-07 七）：多轮 usage 跨轮累积 parity

背景：新增 REST 非流式 max_turns（收尾）对照测试时发现灰度与 legacy 的
token 统计分叉：

- legacy `run_graph` 对所有模型调用逐轮 `merge_token_usage`，wrap-up 场景
  返回三轮合计值；
- `AgentLoop` 只把最后一轮模型调用的 usage 放入结果与事件 payload，多轮
  工具/收尾场景 token 统计偏小。

修复：

1. `agent_runtime/contracts.py` 新增 `merge_usage()`：字段名不假设、存在即
   相加，兼容不同供应商键名；`AgentRuntime._merge_usage` 委托同一实现，
   消除双份累积逻辑。
2. `AgentLoop.run` 按轮累积 usage：每轮模型调用后合并进
   `accumulated_usage`，TOOL_STARTED/COMPLETED 事件 payload 与最终结果、
   等待态返回均携带跨轮累计值，与 legacy Graph 口径一致。

新增测试：`test_loop_accumulates_usage_across_tool_rounds`（AgentLoop 两轮
工具 usage 合并、事件 payload 累计）、`test_execute_chat_gray_max_turns_
wrapup_matches_legacy`（REST 非流式收尾回答/usage/模型调用数与 legacy
一致）。

max_turns 边界语义（2026-09-07 按 Pi 对齐，用户确认）：差异先登记为待确认
项——legacy 在达到上限的那次模型请求工具时不再执行该轮工具（`max_turns=2`
只执行 1 轮），AgentLoop 原实现会先执行完该轮再收尾。用户指示参考 Pi：
Pi `agent-loop.ts` 对输出达 token 上限截断的响应会把全部工具调用转为失败
结果、不执行（`failToolCallsFromTruncatedMessage`），即预算/上限类边界上
“新工具不执行”。据此重构 AgentLoop：

1. 上限检查从 while 顶部移到“模型返回工具调用后、执行前”：达到
   `max_turns` 的那轮新工具不再执行，逐条转 `failed(max_turns_reached)`
   回填上下文并发布失败工具事件（保证 assistant tool call 与失败结果成对）；
2. 随后执行一次收尾模型调用（内部提示 + `allow_tools=False`），收尾仍返回
   工具则转稳定失败结果并结束，防无限循环；
3. while 顶部只保留兜底 break，防止 steering/follow-up 让轮次越过上限。

对齐结果：两路成功执行的上限轮数一致（N 上限执行 N-1 轮）；灰度多一条
`tool_completed(failed)` 记录事件（legacy 不记录上限轮调用），不执行副作用
工具的安全语义一致。相关测试（agent_runtime wrap-up 三个 + REST max_turns
对照）已按新语义更新。

### 阶段 7 实施记录（2026-09-07 八）：REST SSE max_turns 收尾 parity 补全

背景：非流式 max_turns 对照已有自动化，但 REST SSE（`stream_chat`）尚无
“达到上限后以收尾回答正常终止”的对照用例，缺口是流式入口是否会卡死、
丢尾事件或在两路间出现事件序列分叉。

新增测试：
`tests/conversation/test_rest_parity.py::test_stream_chat_gray_max_turns_wrapup_
terminates_like_legacy`：使用 `MaxTurnsStreamingModel`（第 1 轮请求工具并执行、
第 2 轮达上限再次请求工具、第 3 轮收尾输出正文），对照断言：

- 灰度与 legacy 都以 `completed`（内容“已到执行上限，基于已有信息回答。”）
  终结，均发布 `agent_loop_completed`（legacy 终态等价物），loop 均落
  `completed`，不卡死、不丢收尾正文；
- 两路模型调用次数一致为 3（执行轮 + 达上限轮 + 收尾轮）；
- 灰度把达上限轮（call-2）转为 `tool_result(status=failed)` 且
  `payload["error"]["code"] == "max_turns_reached"`（记录口径差异），
  legacy 不发布该轮失败工具事件。

实现说明：服务层 `tool_result` 事件 payload 是 `outcome.model_dump()` 后
的 dict，失败原因需用 `payload["error"]["code"]` 读取；测试首版误用属性访问
`payload.error`，修正后通过。此用例不修改任何生产代码，仅补灰度/legacy
REST SSE 行为一致性证据。

### 阶段 7 实施记录（2026-09-07 九）：WS max_turns 收尾 parity 补全

背景：max_turns 对齐语义在 AgentLoop 层实现，REST 非流式与 REST SSE 已有
对照用例，但 gateway WebSocket 入口（`stream_embed_chat`）此前没有完整的
工具轮 max_turns 自动化对照，也未覆盖 WS 灰度工具轮事件到步骤的映射。

新增测试：
`tests/gateway/test_chat_flow.py::test_embed_chat_gray_max_turns_wrapup_
terminates_like_legacy`：使用 `MaxTurnsEmbedStreamingModel`（第 1 轮执行
lookup、第 2 轮达上限再次请求 lookup、第 3 轮收尾输出正文）直接驱动
`stream_embed_chat`，对照断言：

- 灰度与 legacy 都以 `message_completed` 终结、loop 均落 `completed`，
  收尾正文一致，不卡死、不重复完成；
- 两路模型调用次数一致为 3（执行轮 + 达上限轮 + 收尾轮）；
- 工具步骤对比：两路第 1 轮 lookup 步骤均 `succeeded`；灰度第 2 轮达上限
  的 lookup 转为 `failed` 工具步骤（记录口径差异），legacy 不记录未执行的
  上限轮调用。

实现说明：本文件 `FakeConversationRepository.create_loop_step` 原来只按
传入 kwargs 构造 SimpleNamespace，工具步骤开始事件缺少 `output_summary`
等 ORM 列默认字段时触发 AttributeError；补齐默认字段（与 REST 替身 FakeStep
对齐）后通过。此改动只影响测试替身，生产代码无改动。

### 阶段 7 实施记录（2026-09-07 十）：WS confirmation 确认恢复 parity 补全

背景：REST 非流式/SSE 的确认等待态已有 parity 自动化，但 WS 的真实确认
流程是连接层 dispatcher 在工具回调内等待页面决策后恢复模型循环（MCP
`pending_mcp_confirmations` Future 阻塞语义），此前缺少引擎级的“确认后
恢复”灰度对照自动化。

新增测试（`tests/gateway/test_chat_flow.py`）：

- `test_embed_chat_gray_confirmation_approval_resumes_like_legacy`：用
  `make_blocking_confirm_invoke(approved=True)` 模拟 dispatcher 在工具回调
  内进入确认等待（`entered` 事件 + `gate` Future），测试侧放行后断言两路
  都恰好调用 2 次模型（工具轮 + 确认后回答轮）、事件类型序列一致、以
  `message_completed` 终结、loop 均 completed、pay 工具步骤均 succeeded；
- `test_embed_chat_gray_confirmation_rejection_fails_step_like_legacy`：
  用户拒绝（`approved=False` 返回 rejected）时，两路都只把 pay 工具步骤
  记为 failed，模型仍可基于拒绝原因正常收尾、loop completed；拒绝不升级为
  整请求失败、不伪装成取消、不自动重试。

实现说明：真实 WS 的确认事件（`confirmation_required` 入队与页面决策回传）
属于 dispatcher 与连接层职责，已有独立单元测试覆盖；这里只锁定引擎在
“回调内阻塞等待后恢复”语义下灰度与 legacy 的行为一致。生产代码无改动。

### 阶段 7 实施记录（2026-09-07 十一）：WS ask_user 提问恢复 parity 补全

背景：WS 的 ask_user 由 dispatcher `_invoke_question_tool` 发送
`question_required` 事件并在工具回调内等待连接层回传用户答复，模型循环暂停
后恢复。此前缺少引擎级“提问等待后恢复”的灰度对照自动化。

新增测试
`tests/gateway/test_chat_flow.py::test_embed_chat_gray_ask_user_resumes_like_
legacy`：`AskUserWaitStreamingModel` 第 1 轮调用 ask_user，
`make_blocking_question_invoke` 模拟 dispatcher 在回调内等待答复
（`entered` + `gate`），放行后断言：

- 两路都恰好调用 2 次模型（提问轮 + 答复后回答轮）、事件类型序列一致、
  以 `message_completed` 终结、loop 均 completed；
- ask_user 工具步骤两路均 succeeded；收尾正文一致（模型基于用户选择的
  “合并”给出回答）。

实现说明：`question_required` 协议事件与答复回传属 dispatcher/连接层既有
职责（已有 test_question_flow 覆盖），此处只锁定引擎等待后恢复语义。
生产代码无改动。

### 阶段 7 实施记录（2026-09-07 十二）：WS 灰度取消路径 parity 补全

背景：gateway 取消用例（RequestRegistry、断线清理）与 legacy 单路径取消
（`test_cancelled_embed_chat_does_not_write_assistant_completion`）已有，
但缺少灰度开关开启时 `stream_embed_chat` 被连接层取消的对照。

新增测试
`tests/gateway/test_chat_flow.py::test_cancelled_embed_chat_gray_does_not_
write_assistant_completion`：消费灰度事件流，在模型流式正文首条
`message_delta` 到达时抛出 `CancelledError`（取消点穿过 AgentRuntime 引擎
路径），断言：

- 只有用户消息落库，不写助手完成消息；
- loop 保持 running（取消不伪装成失败/完成终态），与 legacy 取消语义一致；
- `CancelledError` 原样传播，不被转换吞掉。

实现说明：取消发生时模型 Task 由连接层取消，AgentRuntime 的事件收尾逻辑
不会执行；网关层不得补写助手消息或把 running loop 改终态。生产代码无改动。

### 阶段 2 实施记录（2026-09-07）：状态映射收拢落地

背景：核心状态契约与集中映射已收敛，剩余重复点是 conversation 流式收尾
（`_finish_stream_chat`）、conversation 非流式 execute_chat 收尾段与
gateway `_finish_embed_chat` 三处各自推导“结果终态 → 生成步骤状态 / loop
状态 / loop 摘要”，且同一函数多次调用 `resolve_result_run_status()`。

实施内容：

1. `agent_runtime/lifecycle.py` 新增并导出 `generation_step_status_for` /
   `loop_status_for` / `loop_summary_for` 三个纯函数助手，映射规则严格照搬
   既有三元表达式（仅 `WAITING_CONFIRMATION` 特殊，其余收敛为
   succeeded / completed / “已完成回答”），中文注释说明 DB 列取值约束与
   非确认等待态由 resolve 阶段提前分流的原因；
2. `conversation/services.py`（流式收尾 + execute_chat 非流式收尾段）与
   `gateway/runtime.py` `_finish_embed_chat` 三处站点统一改用助手，每个
   函数只调用一次 `resolve_result_run_status()`；模型失败/取消的错误分支
   保持原有 failed 落库逻辑不变；
3. 新增 RunStatus 全量矩阵测试
   `tests/agent_runtime/test_lifecycle.py::test_finish_field_helpers_preserve_
   persistence_semantics`，锁定每个状态到三类落库字段的预期值。

验证结果：定向 36 passed（lifecycle + REST parity + gateway chat flow +
cancel）；全量核心回归 `307 passed, 1 skipped, 1 warning`；Ruff、
compileall、`git diff --check` 通过。无公开协议、数据库模型或权限边界变化。

### 2026-09-04 阶段 2 计划：工具状态与终态统一（2026-09-07 盘点更新，已确认）

盘点结论（2026-09-07）：核心状态契约与集中映射已收敛
（`contracts.ToolOutcomeStatus`、`lifecycle.RunStatus`/
`resolve_result_run_status`/`AgentRunLifecycle`、`tool_events.
normalize_tool_step_status`、RequestRegistry 预算终态与迟到回调闸门）；
剩余重复点是三个收尾站点的终态 → 落库字段推导。待确认后实施：

1. [已完成] 盘点 `ToolOutcomeStatus`、`RunStatus`、conversation loop/step 和
   gateway lifecycle 的状态集合及默认映射。
2. [已完成] 固化状态矩阵（工具结果、等待态、请求终态、预算终态、未知值
   安全策略）：lifecycle 助手 + 中文注释固化现有映射规则（2026-09-07）。
3. [已完成] `agent_runtime/lifecycle.py` 新增 `generation_step_status_for` /
   `loop_status_for` / `loop_summary_for` 纯函数助手（行为照搬现有三元
   表达式，仅 `WAITING_CONFIRMATION` 特殊）。
4. [已完成] conversation/services.py（流式收尾 `_finish_stream_chat`、非流式
   execute_chat 收尾段）与 gateway/runtime.py `_finish_embed_chat` 统一改用
   助手推导；每个函数只调用一次 `resolve_result_run_status()`，保持公开
   协议和数据库兼容。
5. [已完成] RunStatus 全量矩阵测试（→ 生成步骤/loop 状态/loop 摘要），
   全量核心回归 307 passed 证明无行为变化。
6. [已完成] 失败、过期、拒绝、取消、预算和迟到回调的跨入口回归已由阶段 5
   /阶段 7 parity 测试覆盖（按需补充矩阵测试时继续沿用）。

## 完整模型轮次迁移增量计划

1. 定义供应商无关的模型响应和流式 chunk Adapter。
2. 扩展 `AgentLoop`，支持模型流式事件与标准化工具调用。
3. 将 conversation 的消息组装封装为 runtime context builder。
4. 在 REST/SSE 上以 feature seam 灰度接入新 loop，保留 legacy Graph fallback。
5. 在 WebSocket 上接入新 loop，专项回归确认、ask_user、取消和断线。
6. 验证通过后再删除重复 Graph 编排；若发现协议、权限或数据模型变化，立即暂停确认。
| 工具链真实回归 | 已完成 | 用户确认 WS 与 REST SSE 的普通工具、confirmation/ask_user、取消和完成事件均正常 |

### 新增目录：`apps/backend/app/modules/agent_runtime/`

- `__init__.py`：模块导出和版本兼容入口。
- `contracts.py`：定义 `AgentRequest`、`ToolCall`、`ToolOutcome`、`AgentEvent`、运行状态等内部契约。
- `context.py`：定义请求级运行上下文，集中携带 Agent、版本、历史、引用、附件和可用工具。
- `loop.py`：统一非流式与流式 Agent 主循环，负责模型调用、工具轮次、最大迭代和收尾。
- `loop.py`：参考 Pi 的共享 `runLoop` 设计，同时支持新请求与 continuation，并通过事件 sink 输出过程事件。
- `tools.py`：定义工具执行器接口、工具注册表和工具结果归一化逻辑。
- `runtime.py`：对外提供 `AgentRuntime.run()` 与 `AgentRuntime.stream()`，负责准备上下文并调用 loop。
- `persistence.py`：封装会话、消息、loop、loop step 的生命周期持久化编排。
- `adapters.py`：提供现有 conversation/gateway 结果到内部契约的兼容转换。
- `hooks.py`：预留 context transform、每轮结束策略、继续执行和请求级取消等显式扩展点。

### 修改现有模块

- `apps/backend/app/modules/conversation/runtime.py`：逐步把 Agent loop、事件和契约迁移到 `agent_runtime`，保留兼容导出。
- `apps/backend/app/modules/conversation/services.py`：改为调用 `AgentRuntime`，保留 REST 会话和响应适配。
- `apps/backend/app/modules/conversation/router.py`：只保留 HTTP 参数、鉴权依赖和 SSE 序列化。
- `apps/backend/app/modules/gateway/dispatcher.py`：实现或适配 `ToolExecutor` 注册表，不改变现有权限、确认和审计行为。
- `apps/backend/app/modules/gateway/runtime.py`：保留 Embed 附件和网关事件适配，移除重复 Agent loop 编排。
- `apps/backend/app/modules/gateway/router.py`：逐步提取连接状态和入站消息分发，endpoint 保持协议兼容。

### 测试文件

- `apps/backend/tests/agent_runtime/test_contracts.py`
- `apps/backend/tests/agent_runtime/test_loop.py`
- `apps/backend/tests/agent_runtime/test_tool_dispatch.py`
- `apps/backend/tests/agent_runtime/test_runtime_adapters.py`
- 在现有 `tests/conversation/`、`tests/gateway/` 增补兼容性和行为一致性用例。

## 实施步骤

1. 先冻结现状：记录现有 REST、SSE、WebSocket、工具确认、ask_user、取消和超时的事件顺序与状态变化。
2. 创建 `agent_runtime` 目录，定义类型化内部契约；参考 Pi 的 request ID、事件 sink、continuation 和显式运行上下文；暂不删除旧函数，先让新契约可被测试构造。
3. 抽取统一工具执行接口和注册表，将现有 `RuntimeToolDispatcher` 的 MCP、builtin、skill、host tool、ask_user 行为接入 Adapter。
4. 抽取统一 Agent loop：先复用当前模型调用和上下文保护逻辑，再让非流式与流式共享同一个轮次实现；增加 `Abort` 检查、上下文变换、每轮结束钩子和 continuation 能力。
5. 抽取持久化生命周期：统一用户消息、assistant 消息、loop、loop step 的创建、成功、失败、取消和等待状态处理。
6. 将 `conversation/services.py` 的 REST 执行路径迁移到 `AgentRuntime`，保留原 HTTP 响应结构。
7. 将 `gateway/runtime.py` 的 Embed 执行路径迁移到 `AgentRuntime`，保留 WebSocket 事件结构、顺序和 requestId。
8. 拆分网关连接状态机；仅在内部移动代码，确保鉴权、工具注册、确认恢复、取消和重放行为不变。连接级 Future 只负责等待外部输入，Agent runtime 通过显式取消信号结束请求。
9. 删除重复实现或改为兼容转发，并补齐模块文档、中文关键注释和类型标注。
10. 执行测试、静态检查和编译检查，记录真实结果到 `verify.md`。

## 测试步骤

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
  - 预期：新旧核心测试通过，工具和协议兼容性无回归。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 预期：无新增 lint 错误。
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`
  - 预期：所有 Python 文件编译成功。
- 如环境允许，补充一次 WebSocket 测试和 REST SSE 测试，核对事件顺序、sequence、requestId 与终态。
- 增加截断工具参数、取消、continuation 和上下文变换测试，确保不执行不完整工具参数且最终事件可收敛到权威状态。

## 回滚说明

- 每一步保持旧入口可调用，迁移失败时将 REST 或 Embed 适配层切回原实现。
- 回滚范围主要是 `agent_runtime/` 新目录和对应适配调用，不修改数据库结构和公开协议。
- 若发现事件顺序或 loop 状态变化，优先恢复调用入口，不删除新模块，待定位后继续渐进迁移。

## 人工确认点

- 已确认：新增 `agent_runtime` 独立目录，并采用统一 runtime、协议 Adapter、类型化内部契约方向。
- 实施中若发现必须修改数据库模型、公开 API/WebSocket 契约或鉴权/权限行为，必须暂停并重新确认。
- 在删除旧实现前，需要人工或回归测试确认 REST 与 Embed 行为一致。
- 已确认（2026-09-04）：多工具调用采用批次尽力完成；普通工具失败不阻断同批次后续工具，取消/确认等待/用户等待保持原有停止语义；本次不引入并行执行。
