# 验证记录

## 2026-09-04 第 3 次增量：多工具调用失败收敛

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/tests/agent_runtime`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/tests/agent_runtime`
- `git diff --check`

### 预期结果

- 工具异常转换为失败工具结果后，同一模型批次中的后续工具仍执行。
- 失败和成功结果均回填下一次模型调用；取消、确认等待和用户等待不被误报为普通失败。
- 核心测试、Ruff、Python 编译和补丁格式检查通过。

### 实际结果

- Loop 测试：`13 passed`。
- Agent runtime 测试：`72 passed`。
- Agent runtime、conversation、gateway 回归：`241 passed, 1 skipped, 1 warning`。
- Ruff：`All checks passed!`。
- compileall：通过，无输出错误。
- `git diff --check`：通过。

### 失败项与例外

- 首次运行完整回归时，旧测试让模型无限重复失败工具调用，因新策略不再抛出工具异常而长时间运行；已中止该测试进程并将测试修正为真实的“失败结果回填后模型结束”场景。
- 保留一个既有 FastAPI/httpx 弃用警告，未涉及本次改动。
- 未进行 REST 人工测试，遵循用户要求最后统一测试；WS 断线重连后的前端消息列表渲染问题继续延期。

## 自动化验证

### 2026-09-04

- 命令：`apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway/dispatcher.py`
- 预期：无新增静态检查错误
- 实际：通过

- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 预期：Agent runtime、conversation、gateway 测试全部通过
- 实际：211 passed，1 skipped
- 例外：FastAPI/Starlette 输出 `httpx` deprecation warning，不影响本次结果。

- 命令：`apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests apps/backend/main.py`
- 预期：Python 文件全部编译成功
- 实际：通过，无编译错误。

- 命令：`apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/gateway`
- 预期：无新增静态检查错误
- 实际：通过。

- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests -q`
- 实际：未进入执行阶段，pytest collection 因仓库既有同名测试模块冲突中断（`test_models.py`、`test_services.py`、`test_routes.py` 分别来自多个目录）。
- 例外：该问题不属于本 request 改动范围，未修改无关测试文件；本 request 核心测试仍单独通过。

## 人工验证

- 场景：使用 WebSocket 对话链路进行真实对话测试
- 日期：2026-09-04
- 实际结果：用户确认测试可以，WebSocket 对话正常。
- 已覆盖：WebSocket 基础连接与对话流程
- 尚未覆盖：新 Agent runtime 接管后的工具确认、ask_user、取消和断线恢复

- 场景：WebSocket 流式对话、工具调用、确认和异常流程
- 日期：2026-09-04
- 实际结果：用户确认测试均正常。
- 结论：事件 Adapter 接入未改变现有 WebSocket 行为。

## SDK 自动化验证

- 命令：`pnpm test -- --run`（工作目录：`apps/ai-sdk`）
- 实际：16 个测试文件通过，99 passed。
- 命令：`pnpm run type-check`（工作目录：`apps/ai-sdk`）
- 实际：通过。
- 命令：`pnpm run build`（工作目录：`apps/ai-sdk`）
- 实际：构建通过，生成 ES/UMD/CSS 和声明文件。

- 场景：模型请求失败
- 日期：2026-09-04
- 实际结果：用户确认客户端收到错误信息，请求可以结束。

- 场景：统一桥接接入后的 WebSocket 综合回归
- 日期：2026-09-04
- 实际结果：用户确认普通对话、工具调用、confirmation、ask_user、取消和断线恢复均正常。
- 结论：统一事件/结果桥接未改变现有 WebSocket 行为。

- 场景：REST 非流式真实对话
- 日期：2026-09-04
- 实际结果：用户提供真实响应，`success=true`、`code=0`；conversation_id、message_id、assistant content、content_blocks、loop、知识检索步骤、技能步骤和 model_generation 均正确返回，loop 状态为 `completed`。
- 结论：REST 非流式结果适配和消息/loop 收尾正常。

- 场景：REST SSE 真实流式对话
- 日期：2026-09-04
- 实际结果：用户提供完整事件流，包含 `agent_loop_started`、步骤事件、thinking 增量、tool_call/tool_result、message_delta、`agent_loop_completed` 和 `message_completed`；sequence 从 1 连续到 125，最终状态为 completed。
- 结论：REST SSE 事件顺序、流式增量和最终收尾正常。

- 场景：工具轮次迁移后的 WS/REST SSE 真实回归
- 日期：2026-09-04
- 实际结果：用户确认普通工具调用、confirmation/ask_user、取消、断线/关闭连接和最终完成事件均正常。
- 结论：惰性 `ToolRoundExecutor` 接入未改变工具链行为。

- 场景：`AGENT_RUNTIME_ENABLED=true` 下 REST 非流式灰度
- 日期：2026-09-04
- 实际结果：用户提供真实响应，`success=true`、`code=0`；assistant content、content_blocks、conversation/message、knowledge/skill steps、model_generation 和 loop completed 均正常。
- 结论：AgentRuntime 普通对话灰度路径正常。

- 场景：`AGENT_RUNTIME_ENABLED=true` 下 REST 非流式工具调用
- 日期：2026-09-04
- 实际结果：用户提供真实响应；`get_runtime_info` 工具 step 为 succeeded，工具结果已回填，随后 model_generation succeeded，loop completed。
- 结论：AgentRuntime 灰度工具调用链路正常。

## 测试安排

- REST 普通对话和 REST SSE 当前没有可用页面入口，暂不进行人工测试。
- REST 测试延后到 `execute_chat()` 和 REST SSE 入口完成 Agent runtime 切换后统一执行。
- 在此之前，使用自动化测试覆盖 REST 代码路径，人工验证继续以 WebSocket 为主。

## 当前结论

统一事件、结果、工具和恢复适配已通过自动化验证；WS 仍保留旧 Graph 执行器作为兼容实现。REST 人工验证尚未进行，需在最终入口迁移后执行。

## Harness 审计

- 命令：`apps/backend/.venv/bin/python tools/harness/audit.py`
- 实际：本 request 未产生审计错误；仓库存在 1 个其他历史 request 的既有 ERROR 和 16 个 WARN，未修改无关 request。

- 验收前复核：再次执行同一审计命令，结果仍为本 request 无新增错误；仓库既有历史 ERROR/WARN 保持不变。

- 场景：REST SSE AgentRuntime 适配器自动验证
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/tests/agent_runtime`、`pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation -q`、`python -m compileall -q ...`
- 实际结果：Ruff 通过，138 passed，compileall 通过。
- 结论：runtime 事件展开、工具结果回填和 SSE 收尾适配具备自动化回归覆盖；尚待用户真实 REST SSE 验证。

- 场景：`AGENT_RUNTIME_ENABLED=true` 下 REST SSE 真实验证
- 日期：2026-09-04
- 实际结果：用户确认最终收到 `message_completed`；响应包含 content、contentBlocks、conversation/message、completed loop，未再出现工具参数类型错误或 GraphResult 收尾错误。
- 结论：REST SSE AgentRuntime 灰度链路通过真实验证。

- 场景：WS 断线重连后的前端消息渲染
- 日期：2026-09-04
- 当前结论：服务端与 SDK 的 sequence/replay 状态恢复存在独立问题，曾出现重连后 `message_started` 被 sequence 去重丢弃，以及连接认证阶段 4401。该问题暂不纳入本轮 runtime 架构验收，已记录为后续 SDK replay 专项。
- 后续要求：单独建立 SDK transport/reducer 回归用例，覆盖服务器重启、replay、首条新消息和宿主工具结果回传。

- 场景：确认拒绝、重复确认与迟到宿主工具回调
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_host_tool_result_idempotency.py apps/backend/tests/gateway/test_request_cancellation_cleanup.py apps/backend/tests/gateway/test_disconnect_cleanup.py -q`
- 实际结果：5 passed；确认拒绝只产生一次 `rejected` 状态转换并只唤醒一次等待 Future；已进入终态的审计忽略迟到 confirmation 和 host tool result。
- 结论：网关外部回调在重复、迟到场景下保持幂等，不会重新驱动 Agent loop。

- 场景：AgentRuntime 流式观测钩子一致性
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py -q`、`apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/tests/agent_runtime/test_runtime.py`
- 实际结果：目标测试 10 passed，Ruff 通过；随后 AgentRuntime、conversation、Gateway 核心集合 231 passed、1 skipped。
- 结论：流式 `message_delta`、`completed` 等事件会与非流式路径一样经过 `on_event`，观测、审计和指标钩子不会因传输模式丢失。

- 场景：AgentRuntime 并发请求的持久化隔离
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py apps/backend/tests/agent_runtime/test_runtime_concurrency.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 12 passed；核心回归 232 passed、1 skipped；Ruff 通过。
- 结论：显式使用 `persistence_factory` 时，每个 request 获得独立 persistence，不共享事件列表和本地 sequence；未使用 factory 的历史调用保持兼容。

- 场景：流式模型异常、队列尾事件和错误观测钩子
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 11 passed；核心回归 233 passed、1 skipped；Ruff 通过。
- 结论：模型在首个事件前失败时请求及时结束并产生标准 error；模型任务与事件队列同时完成时不丢尾事件；兜底 error 会触发 `on_event`。

- 场景：模型/工具调用期间取消
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 10 passed；核心回归 234 passed、1 skipped；Ruff 通过。
- 结论：模型或工具尚未返回时设置 `cancel_event` 会取消底层 await，并通过统一取消事件收敛，不再依赖外部调用自然结束。

- 场景：AgentLoop/AgentRuntime continuation 快照恢复
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/agent_runtime/test_runtime.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 23 passed；核心回归 236 passed、1 skipped；Ruff 通过。
- 结论：恢复快照已经包含工具结果时不会重复追加；同一工具不同对象的重试结果仍会保留，避免误用 call_id 去重。

- 场景：等待确认结果的统一状态映射
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 13 passed；核心回归 237 passed、1 skipped；Ruff 通过。
- 结论：runtime 结果会保留 `confirmation_required` 工具的 `confirmation_id`，上层可据此识别等待确认状态并继续恢复。

- 场景：continuation usage 与工具轨迹累积
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 14 passed；核心回归 238 passed、1 skipped；Ruff 通过。
- 结论：传入 `prior_result` 时可得到累计 token usage 和完整 tool_events；当前恢复已完成时会清除旧 pending confirmation 状态；不传时保持兼容行为。

- 场景：legacy callback 工具错误结果转换
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_tools.py apps/backend/tests/agent_runtime/test_adapters.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 8 passed；核心回归 239 passed、1 skipped；Ruff 通过。
- 结论：callback 返回 dict、旧对象或 `ToolOutcome` 时，错误码、恢复 token、调用 ID 等统一字段均能正确传递到 runtime。

- 场景：工具抛异常与 failed ToolOutcome 的事件一致性
- 日期：2026-09-04
- 命令：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/agent_runtime/test_runtime.py -q`；核心回归：`apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- 实际结果：目标测试 26 passed；核心回归 240 passed、1 skipped；Ruff 通过。
- 结论：工具异常会先生成统一的失败工具事件，再由 runtime 传播 Agent 级 error；取消路径仍只产生取消终态。
# 2026-09-04 第 4 次增量验证：最大轮数收尾行为

## 自动化验证

| 命令 | 结果 |
|---|---|
| `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/agent_runtime/test_langchain_adapter.py -q` | 19 passed（最终补充预算终态断言后，`test_loop.py` 15 passed） |
| `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q` | 243 passed, 1 skipped, 1 warning |
| `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py` | 通过 |
| `git diff --check` | 通过 |
| `apps/backend/.venv/bin/ruff check apps/backend` | 未通过；仅命中既有 `apps/backend/app/modules/embed/repositories.py:10` 未使用导入 `BaseRepository`，与本次改动无关 |
| `python3 tools/harness/audit.py` | 1 个既有 ERROR、16 个既有 WARN；未新增本 request 错误 |

## 本轮行为证据

- `max_turns=1` 且首轮返回工具调用时，工具正常执行一次；达到上限后注入中文收尾提示并调用第二轮模型。
- 收尾调用通过 `allow_tools=False` 选择未绑定工具模型；普通 LangChain Adapter 仍沿用绑定工具模型。
- 收尾模型再次返回工具调用时，runtime 发布 `tool_completed(status=failed, error.code=max_turns_reached)`，随后发布单一 `completed`，不会调用真实工具，也不会继续循环。
- 取消、confirmation、waiting_user 逻辑未修改；既有核心回归保持通过。

## 例外与剩余风险

- Ruff 的既有错误未在本轮修复，避免混入无关改动。
- 本轮未进行 REST/SSE/WS 人工测试；公开协议兼容性沿用已有自动化和用户此前真实验证结果。

## 后续兼容性修正验证

- 修正收尾模型签名兼容判断：由异常回退改为调用签名检查，避免把供应商内部 `TypeError` 重试成第二次模型调用。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py -q`：16 passed。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：244 passed, 1 skipped, 1 warning。
- 涉及文件 Ruff：通过；Agent runtime compileall：通过；`git diff --check`：通过。

## 非正最大轮数兼容验证

- 新增回归：`max_turns=0` 时仍执行模型和工具轮次，不在首轮前抛出无模型结果错误。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py -q`：17 passed。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：245 passed, 1 skipped, 1 warning。
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/tests/agent_runtime`：通过；`git diff --check`：通过。

## 阶段 2 状态契约验证

- 新增 `ToolOutcomeStatus.CANCELLED/BUDGET_EXCEEDED` 和 `RunStatus` 等待/预算状态测试。
- 未知工具状态现在安全映射为 `failed`；`expired/rejected` 映射为失败类 step；`cancelled`、`budget_exceeded` 保留独立 step 状态。
- `AgentRunLifecycle` 等待态可恢复，进入完成/失败/取消/预算终态后迟到转换不生效。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：251 passed, 1 skipped, 1 warning。
- Agent runtime Ruff：通过。

## 跨入口结果状态解析验证

- 新增 `resolve_result_run_status()`，固定按等待态、预算终态、失败终态、成功终态顺序解析结果。
- conversation 与 gateway 的最终 loop/generation 收尾均接入共享解析；确认等待仍映射为 `waiting_confirmation`，普通结果仍为 `completed`。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：255 passed, 1 skipped, 1 warning。
- 相关 Ruff 与 `git diff --check`：通过。

## Gateway 请求终态幂等验证

- `RequestRegistry.budget_exceeded()` 新增预算终态入口；后续 `complete()` 保持 `budget_exceeded`，不会覆盖为普通完成。
- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_cancel.py -q`：3 passed。
- 核心回归：`256 passed, 1 skipped, 1 warning`。
- Agent runtime、Gateway 相关 Ruff：通过；`git diff --check`：通过。

## 公开协议边界审计

- 检查预算终态接入时发现新增 WS payload 字段会违反“不修改公开协议”约束，已撤回该路径。
- 当前改动只保留内部 `RequestRegistry.budget_exceeded()` 和生命周期幂等能力，未改变 `message_completed` 字段。
- 核心回归重新通过：`256 passed, 1 skipped, 1 warning`；相关 Ruff 和 `git diff --check` 通过。

## 入站回调请求归属验证

- confirmation、ask_user、host tool 处理函数新增可选 `active_request_id`；消息携带不同 requestId 时拒绝唤醒与审计变更。
- 缺失 requestId 的消息保持旧客户端兼容，不做归属拒绝。
- 定向测试：`test_host_tool_result_idempotency.py` 与 question 流程共 12 passed。
- 核心回归：`257 passed, 1 skipped, 1 warning`；相关 Ruff 与 `git diff --check` 通过。

## 失败工具不升级 Agent 终态验证

- 新增 `_finish_embed_chat` 回归：结果包含 `tool_completed(status=failed)` 时，工具 step 为 failed，最终 `loop.status=completed`、`generation_step.status=succeeded`。
- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`：7 passed。
- 核心回归：`258 passed, 1 skipped, 1 warning`；相关 Ruff 与 `git diff --check` 通过。

## 阶段 3 模型错误与 usage 收敛验证

- `error_from_exception`：HTTP 502/5xx → `agent_upstream_unavailable/retryable=True`；上下文超限 → `context_length_exceeded/retryable=False`；401/429 等客户端错误保持不可重试。
- runtime 错误 details 只包含 `statusCode/exceptionType`，不包含供应商原始异常文本。
- usage 归一化支持 `usage_metadata`、`response_metadata.token_usage` 与 `response_metadata.usage` 三种来源。
- invalid tool call 不会进入 `tool_calls`；空内容模型结果保持 completed 终态。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：265 passed, 1 skipped, 1 warning。
- Ruff、compileall 与 `git diff --check`：通过。

## 阶段 4 runtime 混合上下文护栏验证

- 新增 `apply_runtime_context_guardrail` 回归：混合上下文含 assistant 工具调用与 `ToolOutcome` 时，裁剪后不存在孤立工具结果，System 与最近一轮配对保留。
- REST/WS runtime 灰度入口的 `context_transform` 已切换；legacy Graph 的 `apply_context_guardrail` 行为与测试保持不变。
- `_messages_chars` 现在估算 `ToolOutcome` 字符占用，避免护栏低估预算。
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`：267 passed, 1 skipped, 1 warning。
- Ruff、compileall 与 `git diff --check`：通过。

## conversation 工具步骤状态映射验证

- 新增取消与预算耗尽工具结果回归：分别落为 `cancelled`/`budget_exceeded`，展示摘要和结构化错误码保持一致。
- 未知状态默认失败的映射继续通过，未改变成功、确认等待和 ask_user 展示。
- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_runtime.py apps/backend/tests/agent_runtime apps/backend/tests/gateway -q`：222 passed, 1 skipped, 1 warning。

## 2026-09-04 阶段 5 验证：工具执行边界收敛（已确认）

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_tool_loop.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_host_tool_timeout.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_runtime.py -q -k "unknown_tool or tool_exception or cancellation or stream_unknown"`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway/dispatcher.py apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation/test_runtime.py`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation apps/backend/main.py`
- `git diff --check`

### 预期结果

- legacy `ToolRoundExecutor` 与 runtime/Pi 语义一致：未知工具与普通异常转为 `failed` 工具结果并继续同批次，不再静默跳过或升级为整请求错误；取消原样传播。
- host tool 等待按审计 `expires_at` 收敛：`awaiting_confirmation` 超时转为 `expired`，`running` 超时转为 `failed`（`host_tool_execution_timeout`）；取消/超时清理 pending Future；迟到页面结果不二次变更审计。
- 全量回归、Ruff、compileall 与 `git diff --check` 通过。

### 实际结果

- 工具轮定向测试：`6 passed`（新增未知工具失败结果化、异常归一化并继续后续工具、取消传播、流式失败事件）。
- host tool 超时测试：`4 passed`（running/确认超时转换、取消清理、超时与成功回调竞争恢复）。
- legacy conversation 未知工具回归：`1 passed`（两次未知工具均失败结果化，模型收到后可给出最终回答，不再空收尾）。
- 全量核心回归：`277 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用警告，与本轮无关）。
- Ruff：`All checks passed!`。
- compileall：通过，无编译错误。
- `git diff --check`：通过。

### 失败项与例外

- 首版 host tool 测试替身未模拟“首次查询无审计记录”，导致走了复用分支并抛错；已修正仓库替身语义后通过。
- host tool `running` 超时会把仍在执行的页面工具标记为 `failed`，迟到页面结果会被审计幂等忽略；该产品语义已在方案确认中明确，真实页面长耗时场景留待最终统一人工测试。

## 2026-09-04 阶段 6 审计验证：持久化与并发

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime_concurrency.py apps/backend/tests/agent_runtime/test_persistence.py apps/backend/tests/gateway/test_cancel.py apps/backend/tests/gateway/test_replay.py apps/backend/tests/gateway/test_sequence_after_replay.py apps/backend/tests/gateway/test_request_cancellation_cleanup.py apps/backend/tests/gateway/test_disconnect_cleanup.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`

### 预期结果

- 并发 stream 不串流；请求级 persistence 工厂各归其位；registry 终态幂等；取消/断线清理 pending Future；replay 与 sequence 续接正确。
- 阶段 6 为审计阶段，预期无代码变更，全量回归保持通过。

### 实际结果

- 定向并发/持久化/终态/replay 测试：`17 passed`。
- 全量核心回归：`277 passed, 1 skipped, 1 warning`（既有 FastAPI/httpx 弃用警告）。
- 审计结论：AsyncSession 按请求独立、runtime 事件缓冲按请求隔离、终态单写与 replay/sequence 均有实现与测试锁定；`AgentRunPersistence` 为保留 seam，正式落库由协议 Adapter 完成，未发现需要立即修改的并发缺口。

### 失败项与例外

- REST SSE 灰度入口仍缺少自动化端到端回归（现为单元层事件转换覆盖），列入阶段 7。

## 2026-09-04 阶段 7 灰度入口 parity 验证（自动化部分）

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q -k "runtime_gray or embed_chat_emits_started"`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`

### 预期结果

- 开启 `agent_runtime_enabled` 后，WS `stream_embed_chat` 的事件顺序与 legacy Graph 流程一致，公开事件形状不变。
- 全量核心回归与静态检查保持通过。

### 实际结果

- WS 灰度 parity 测试：`2 passed`（新增 `test_embed_chat_runtime_gray_keeps_legacy_event_shape`，legacy 对照测试同步通过）。
- 全量核心回归：`278 passed, 1 skipped, 1 warning`（既有 FastAPI/httpx 弃用警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。

### 失败项与例外

- REST/SSE 的真实人工测试按用户要求统一延期到最后阶段；REST SSE 灰度入口只有单元层事件转换覆盖与既有真实验证记录，尚未做灰度开关开启时的端到端人工回归。
- WS 断线重连后的前端消息列表渲染问题继续延期，不属于本 request 后端范围。

## 2026-09-05 阶段 7 REST 灰度 parity 自动化补全

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_langchain_adapter.py apps/backend/tests/agent_runtime/test_conversation_adapter.py apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/conversation/test_rest_parity.py apps/backend/tests/gateway/test_chat_flow.py apps/backend/tests/gateway/test_host_tool_timeout.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- 服务层 `execute_chat`（REST 非流式）与 `stream_chat`（REST SSE）在灰度开启时的结果形状、引用语义、工具步骤与事件序列和 legacy Graph 一致。
- runtime 工具事件携带工具分类与结构化参数，conversation 持久化可生成与 legacy 相同口径的 `input_summary` 与快照参数。
- 核心回归、Ruff、compileall 与 `git diff --check` 通过。

### 实际结果

- 定向测试：`44 passed`（新增 REST parity 4 个用例与工具类型适配用例）。
- 全量核心回归：`285 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：灰度 `knowledge_grounded` 引用语义、loop step 工具类型与
  `input_summary`、非流式图片改写与 content_blocks、流式 fallback 图片改写。

### 失败项与例外

- 尝试运行整个 `apps/backend/tests` 时，pytest collection 因仓库既有同名测试
  模块（`test_models.py`/`test_services.py`/`test_routes.py`）冲突中断；该问题
  与本轮改动无关，未修改无关测试文件，按 plan 的测试范围以
  `agent_runtime + conversation + gateway` 为核心回归。
- REST 非流式与 REST SSE 的真实人工测试（灰度开启）仍按用户要求延后到最后
  统一测试；REST SSE 灰度下的 reasoning/thinking 流与 host tool 长耗时超时
  真实场景也列入最终人工回归范围。
- WS 断线重连后前端消息列表渲染问题继续延期。

## 2026-09-05 阶段 7 thinking/reasoning 灰度 parity 补全

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_langchain_adapter.py apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/agent_runtime/test_runtime.py apps/backend/tests/conversation/test_rest_parity.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- 灰度路径与 legacy 使用同一份正文/思考提取规则；
- 流式 REST SSE/WS 在模型返回 reasoning 时按 legacy 顺序发布
  `thinking_delta`，最终结果合并工具轮与最终轮思考文本；
- 非流式 REST 的 `thinking_text` 与 legacy GraphResult 一致并落 loop step。

### 实际结果

- 定向测试：`49 passed`。
- 全量核心回归：`291 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：AgentRuntime 流式/非流式思考透出、跨轮思考累积、content 列表正文
  提取，以及 REST/WS 各入口 completed fallback 的 `thinking_text` 补齐。

### 失败项与例外

- 全量 `apps/backend/tests` collection 冲突为仓库既有同名测试模块问题，与
  本轮改动无关（见上一节记录）。
- REST 非流式与 REST SSE 的真实人工测试（灰度开启）仍延后；思考模型真实
  供应商流式样本列入最终人工回归范围。

## 2026-09-05 阶段 7 REST SSE astream 工具轮 parity

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_rest_parity.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- REST SSE 灰度在 astream 工具轮场景下的事件顺序、tool_call/tool_result
  payload、loop step（含 input_summary）与 legacy 一致；
- 工具快照内容一致（仅写入时间因两次独立运行不同，比较时忽略）。

### 实际结果

- `test_rest_parity.py`：`7 passed`。
- 全量核心回归：`292 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：conversation Adapter 工具参数摘要改为与 legacy 相同的紧凑 JSON +
  300 字符上限。

### 失败项与例外

- 真实模型供应商的 astream 工具调用与 thinking 混合流样本仍需最终人工回归
  确认（灰度开启）；WS 断线重连前端问题继续延期。

## 2026-09-05 阶段 7 REST 确认/等待态灰度 parity

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_rest_parity.py apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/agent_runtime/test_runtime.py apps/backend/tests/agent_runtime/test_conversation_adapter.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- 非流式 REST 灰度确认等待与 legacy 一致：`pending_confirmation_id` 透出、
  工具/model_generation 步骤落为 `waiting_confirmation`、loop 终态一致；
- REST SSE 灰度在 confirmation_required 后补齐
  `agent_step_completed/agent_loop_completed/completed` 收尾事件；
- AgentLoop 等待态结果携带工具事件与思考文本，且不改变 WS 事件流语义。

### 实际结果

- 定向测试：`45 passed`。
- 全量核心回归：`294 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。

### 失败项与例外

- REST 确认等待的真实人工回归（灰度开启，含确认→continuation）仍延后到最后
  统一测试；WS 确认/ask_user 已由用户真实验证过，不受本轮等待态结果修复影响
  （事件流未新增 completed）。

## 2026-09-05 阶段 7 REST SSE/WS 流式模型错误收尾 parity

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_runtime.py apps/backend/tests/conversation/test_rest_parity.py apps/backend/tests/gateway/test_chat_flow.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- 灰度流式路径在模型级错误（含首事件前失败）时以终止 `error` 事件结束，
  与 legacy `stream_graph` 一致；REST SSE 与 WS 协议层统一把生成步骤与
  loop 落为 failed 并向客户端发送稳定 error；
- 取消（`CancelledError`）语义不变，仍保持异常传播，不被错误收尾吞掉；
- REST 非流式两路在模型错误时抛出同一异常，灰度切换不产生额外分叉。

### 实际结果

- 定向测试：`36 passed`（agent_runtime/test_runtime.py 16、rest_parity 11、
  gateway/test_chat_flow.py 9）。
- 全量核心回归：`298 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。

### 失败项与例外

- REST 非流式与 REST SSE 的真实人工测试（灰度开启）继续按用户要求延后；
  模型供应商真实错误样本列入最终人工回归范围。

## 2026-09-06 阶段 7 REST 非流式模型错误失败落库补全

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_rest_parity.py apps/backend/tests/conversation/test_runtime.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- REST 非流式 `execute_chat` 在模型错误时，灰度与 legacy 都向调用方抛出
  同一原异常（REST 公开错误响应不变），同时补写 failed 的
  model_generation 步骤并把 loop 更新为 failed；
- 两路错误 payload 落库内容一致（共用 `build_agent_error_payload`）；
- `CancelledError` 不被错误收尾吞掉。

### 实际结果

- 定向测试：`68 passed`（rest_parity 11 + conversation/test_runtime.py 57）。
- 全量核心回归：`298 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：`execute_chat` 新增统一失败收尾，抽取
  `_run_execute_chat_model_round` 收敛灰度/legacy 模型调用分叉。

### 失败项与例外

- REST 非流式与 REST SSE 的真实人工测试（灰度开启）继续按用户要求延后；
  模型供应商真实错误样本（含超时/上下文超限/5xx）列入最终人工回归范围。

## 2026-09-07 阶段 7 多轮 usage 跨轮累积 parity

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/conversation/test_rest_parity.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- AgentLoop 对多轮工具/收尾场景的 usage 与 legacy Graph 一致（逐轮相加）；
  TOOL_STARTED/COMPLETED 事件 payload 与最终结果均携带跨轮累计值；
- REST 非流式 max_turns 收尾时，灰度与 legacy 的收尾回答、usage、模型
  调用次数一致。

### 实际结果

- 定向测试：`31 passed`。
- 全量核心回归：`300 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：`agent_runtime/contracts.py` 新增 `merge_usage()`，AgentLoop 跨轮
  累积 usage；`AgentRuntime._merge_usage` 委托同一实现。

### 失败项与例外

- max_turns 边界语义差异已在 2026-09-07 按 Pi 对齐解决（见下节），不再
  是待确认项。
- REST 非流式与 REST SSE 的真实人工测试（灰度开启）继续按用户要求延后。

## 2026-09-07 max_turns 边界语义按 Pi/legacy 对齐

### 参考依据

- Pi `/Users/lixingwen/xw/git/pi/packages/agent/src/agent-loop.ts`：
  `failToolCallsFromTruncatedMessage` 对输出达 token 上限截断的响应，把全部
  工具调用转为失败结果且不执行（预算/上限类边界“新工具不执行”）。
- legacy `conversation/runtime.py` run_graph：达到 `max_iterations` 的那次
  模型响应请求工具时不再执行该轮工具，直接进入收尾。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_loop.py apps/backend/tests/conversation/test_rest_parity.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/app/modules/gateway apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway`
- `git diff --check`

### 预期结果

- AgentLoop 达到 `max_turns` 的那次模型响应若请求工具，该轮新工具不再执行
  （与 legacy/Pi 一致），逐条转为 `failed(max_turns_reached)` 回填并发布失败
  工具事件；
- 随后执行一次禁工具的收尾模型调用；收尾仍返回工具则转稳定失败结果并结束，
  不无限循环；
- 成功执行的上限轮数两路一致（N 上限执行 N-1 轮），灰度仅多一条上限轮
  failed 记录事件。

### 实际结果

- 定向测试：`31 passed`。
- 全量核心回归：`300 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff：`All checks passed!`；compileall：通过；`git diff --check`：通过。
- 修复项：`AgentLoop.run` 上限检查移到“模型返回工具后、执行前”，收尾
  wrap-up 逻辑随上限轮触发；while 顶部保留兜底 break。

### 失败项与例外

- 灰度上限轮会多发布一条 `tool_completed(failed)` 记录事件（legacy 不记录
  上限轮调用），属记录口径差异；两路均不执行该轮有副作用工具，安全语义一致。
- REST 非流式与 REST SSE 的真实人工测试（灰度开启）继续按用户要求延后，
  最大轮数场景列入人工回归范围。

## 2026-09-07 阶段 7 REST SSE max_turns 收尾 parity 补全

### 背景

非流式 max_turns 对照已有自动化（记录七），但 REST SSE（`stream_chat`）
入口此前没有“达到上限后以收尾回答正常终止”的对照用例。本次补
`test_stream_chat_gray_max_turns_wrapup_terminates_like_legacy`，确认流式
入口在达上限时不卡死、不丢收尾事件，且灰度/legacy 事件序列与终态一致。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_rest_parity.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- 灰度与 legacy 都以 `completed`（内容“已到执行上限，基于已有信息回答。”）
  终结，均不卡死、不丢收尾正文；
- 两路模型调用次数一致为 3（执行轮 + 达上限轮 + 收尾轮），loop 均落
  `completed`；
- 灰度把达上限轮工具转为 `tool_result(status=failed)` 且
  `payload["error"]["code"] == "max_turns_reached"`；legacy 不发布该轮失败
  工具事件（记录口径差异，不执行有副作用工具的安全语义一致）。

### 实际结果

- 定向测试：`13 passed`（`test_rest_parity.py` 全量）。
- 全量核心回归：`301 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 本次修复：测试断言中 `payload.error` 改为 `payload["error"]`（服务层
  `tool_result` payload 是 `outcome.model_dump()` 后的 dict，错误代码位于
  `payload["error"]["code"]`）；生产代码无改动。

### 失败项与例外

- 灰度上限轮多发布一条 `tool_completed(failed)` 记录事件属预期记录口径差异。
- 仓库内存在既有（非本次范围）`app/modules/embed/repositories.py` 未使用导入
  F401，来自历史提交 `622ae73`；本次验证按任务范围限定 Ruff 路径，未改动
  无关文件。
- REST 非流式与 REST SSE 的真实人工测试（灰度开启）继续按用户要求延后，
  最大轮数场景列入人工回归范围。

## 2026-09-07 阶段 7 WS max_turns 收尾 parity 补全

### 背景

gateway WebSocket 入口（`stream_embed_chat`）此前没有完整的工具轮
max_turns 自动化对照。本次新增
`test_embed_chat_gray_max_turns_wrapup_terminates_like_legacy`，确认 WS
灰度路径在达上限时与 legacy 一样以收尾回答正常终止，并顺带补齐 WS 灰度
工具轮事件到步骤映射的首个自动化覆盖。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- 灰度与 legacy 都以 `message_completed` 终结、loop 均落 `completed`，
  收尾正文一致，不卡死、不产生重复完成事件；
- 两路模型调用次数一致为 3（执行轮 + 达上限轮 + 收尾轮）；
- 两路第 1 轮 lookup 工具步骤 `succeeded`；灰度第 2 轮达上限的 lookup 记为
  `failed` 工具步骤，legacy 不记录未执行的上限轮调用。

### 实际结果

- 定向测试：`1 passed`（新增 WS parity 用例），`test_chat_flow.py` 全量
  `10 passed`。
- 全量核心回归：`302 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 修复项：`FakeConversationRepository.create_loop_step` 补齐 ORM 列默认字段
  （output_summary/error 等），与 REST 替身 FakeStep 对齐；仅测试替身改动，
  生产代码无改动。

### 失败项与例外

- 灰度上限轮多一条 failed 工具步骤记录属预期记录口径差异，两路均不执行
  该轮有副作用工具。
- WS 断线重连、sequence/replay 前端问题按用户要求延期，不属本 request
  后端验收范围；REST 与 WS 真实人工测试继续按用户要求延后。

## 2026-09-07 阶段 7 WS confirmation 确认恢复 parity 补全

### 背景

WS 真实确认流程是连接层 dispatcher 在工具回调内等待页面决策（MCP
`pending_mcp_confirmations` Future 阻塞）后恢复模型循环。本次用
“进入确认等待 → 测试放行”的回调分别驱动 legacy 与灰度 `stream_embed_chat`，
锁定确认批准/拒绝两种决策下的引擎恢复行为 parity。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q -k confirmation`
- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- 批准：两路都恰好调用 2 次模型（工具轮 + 确认后回答轮）、事件类型序列
  一致、以 `message_completed` 终结、loop completed、pay 工具步骤
  succeeded；
- 拒绝：两路都只把 pay 工具步骤记为 failed，模型仍可正常收尾、loop
  completed；拒绝不升级为整请求失败、不伪装成取消、不自动重试被拒工具。

### 实际结果

- 定向测试：`2 passed`（approval + rejection）；`test_chat_flow.py` 全量
  `12 passed`。
- 全量核心回归：`304 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 修复项：无（生产代码零改动，纯测试增量；确认事件与页面决策回传属于
  dispatcher/连接层职责，已有独立单元测试覆盖）。

### 失败项与例外

- 真实 MCP 确认的超时（expired）、拒绝与页面回传竞争等由 dispatcher 层
  既有测试覆盖，未在本轮重复；WS 真实人工回归继续按用户要求延后。

## 2026-09-07 阶段 7 WS ask_user 提问恢复 parity 补全

### 背景

WS 的 ask_user 由 dispatcher 在工具回调内等待连接层回传用户答复后恢复模型
循环。本次用 `make_blocking_question_invoke` 模拟该等待并分别驱动 legacy
与灰度 `stream_embed_chat`，锁定引擎“提问等待后恢复”行为 parity。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- 两路都恰好调用 2 次模型（提问轮 + 答复后回答轮）、事件类型序列一致、
  以 `message_completed` 终结、loop 均 completed；
- ask_user 工具步骤两路均 succeeded；收尾正文一致（基于用户选择的“合并”）。

### 实际结果

- 定向测试：`test_chat_flow.py` 全量 `13 passed`（含新增 ask_user parity
  与既有 confirmation/max_turns 用例）。
- 全量核心回归：`305 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 修复项：无（生产代码零改动；`question_required` 协议形状与答复回传已有
  dispatcher 层测试覆盖）。

### 失败项与例外

- ask_user 超时（expired）、单请求提问上限等 dispatcher 层行为不在本用例
  范围；WS 真实人工回归继续按用户要求延后。

## 2026-09-07 阶段 7 WS 灰度取消路径 parity 补全

### 背景

灰度开关开启时，连接层取消模型 Task 会以 `CancelledError` 穿过
`stream_embed_chat`。此前没有灰度路径的取消对照自动化；本次在模型流式正文
首条 `message_delta` 到达时取消，验证取消点穿过 AgentRuntime 引擎路径。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- 取消发生在模型流式输出中途：只有用户消息落库、不写助手完成消息；
- loop 保持 running（取消不伪装成失败/完成终态）；
- `CancelledError` 原样传播，与 legacy 取消语义一致。

### 实际结果

- 定向测试：`test_chat_flow.py` 全量 `14 passed`（含新增灰度取消用例）。
- 全量核心回归：`306 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 修复项：无（生产代码零改动；首版用例把取消点放在 message_started，未
  穿过灰度引擎路径，已改为在首条 message_delta 时取消）。

### 失败项与例外

- 断线清理、RequestRegistry 取消竞争等连接层行为由既有 gateway 测试覆盖；
  WS 真实人工回归继续按用户要求延后。

## 2026-09-07 阶段 2 状态映射收拢验证：lifecycle 收尾字段助手

### 背景

用户确认阶段 2 方案后实施：把 conversation/gateway 三个收尾站点重复的
“结果终态 → 生成步骤状态 / loop 状态 / loop 摘要”推导收敛到
`agent_runtime/lifecycle.py` 新增的三个纯函数助手，行为严格保持现状。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime/test_lifecycle.py apps/backend/tests/conversation/test_rest_parity.py apps/backend/tests/gateway/test_chat_flow.py apps/backend/tests/gateway/test_cancel.py -q`
- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/gateway apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/gateway apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- lifecycle 助手把 `WAITING_CONFIRMATION` 映射为 waiting_confirmation /
  “等待用户确认后继续”，其余状态映射为 succeeded / completed /
  “已完成回答”（与既有行为逐字一致）；
- 三个收尾站点每个函数只调用一次 `resolve_result_run_status()`；
- REST/SSE/WS 既有 parity 与终态测试全部保持通过，无协议或数据库行为变化。

### 实际结果

- 定向测试：`36 passed`（lifecycle 矩阵 + REST parity + gateway chat flow
  + cancel）。
- 全量核心回归：`307 passed, 1 skipped, 1 warning`（FastAPI/httpx 既有弃用
  警告；新增 1 条 RunStatus 矩阵测试）。
- Ruff（任务限定范围）：`All checks passed!`；compileall：通过；
  `git diff --check`：通过。
- 修复项：`agent_runtime/lifecycle.py` 新增并导出
  `generation_step_status_for` / `loop_status_for` / `loop_summary_for`；
  conversation/services.py 与 gateway/runtime.py 三处收尾站点改用助手并
  去除重复 `resolve_result_run_status()` 调用；错误分支（failed 落库）未动。

### 失败项与例外

- host tool 审计状态（`awaiting_confirmation` 等）属于另一领域状态机，按
  方案范围未收拢；REST/WS 真实人工测试继续按用户要求延后。

## 2026-09-08 阶段 8 验证（8A：真实模型缓解迁入 AgentRuntime）

### 背景与结论

用户确认仅保留 `AgentLoopAgentRuntime` 并最终删除 legacy（选项甲：先迁入两处
真实模型缓解再删）。基线重跑全量核心回归 `307 passed, 1 skipped`（HEAD
`955a3dd`）。

### 8A-1：AgentLoop 模型错误降级重试钩子 + context-length 接入

- `agent_runtime/hooks.py` 新增 `on_model_error` 恢复器钩子（ModelErrorRecoverer）；
- `agent_runtime/loop.py` 每次模型调用包一层“一次性降级重试”：失败不算新增一轮、
  不发布错误事件，取消（`CancelledError`）原样传播，重试仅一次防死循环；
- `agent_runtime/runtime.py` `_new_loop` 与 `composition.py`
  `build_langchain_runtime` 透传 `on_model_error`；
- `conversation/runtime.py` 新增 `make_context_degrade_recoverer`；
  services（REST 非流式 + REST SSE）与 gateway（WS）三处灰度调用注入该恢复器，
  模型抛 context-length 时丢弃历史、只保留系统提示 + 当前用户消息重试一次；
- 测试：`tests/agent_runtime/test_loop.py` 新增重试一次 / 返回 None 不重试两用例。

### 8A-2：WS 纯文本拒图降级恢复

- `conversation/runtime.py` 新增 `make_multimodal_degrade_recoverer`：先判拒图
  错误（`_is_text_only_image_error`），裁掉 image_url 内容块（保留文本/文档）
  重试；再判 context-length 降级；其余错误返回 None；
- `gateway/runtime.py` WS 灰度改用该恢复器（保留文档文本与上下文降级两路）；
- 测试：新增 `tests/conversation/test_model_recover.py` 覆盖拒图裁图、保留文本/
  文档、context-length 降级与非匹配错误不重试。

### 实际结果

- 定向：`tests/agent_runtime/test_loop.py` + `tests/conversation/test_model_recover.py`
  `24 passed`；
- 全量核心回归：`312 passed, 1 skipped`；Ruff、compileall、`git diff --check` 通过；
- 提交：`efb64f3`（8A-1）、`14dcac4`（8A-2）。

### 失败项与例外

- legacy 引擎仍未删除（8B/8C 后续）；8D parity/直连测试迁移与 8E 全量收尾待做；
  legacy 独有的真实模型缓解语义已通过选项甲迁入 AgentRuntime 灰度路径。

## 2026-09-09 阶段 8 验证（8C：删除 legacy 主循环死代码；8D：直连测试收敛；8E 自动化收尾）

### 背景与结论

8B 已把 REST/SSE/WS 三协议生产入口统一只走 `AgentLoopAgentRuntime`
（提交 `82c48f5`）。本批删除 legacy 主循环死代码，并把直连
`run_graph`/`stream_graph`/`apply_context_guardrail` 的测试收敛到新引擎与
保留的共享函数入口，全量核心回归保持绿。

### 8C 删除范围（实际）

- `conversation/runtime.py` 删除：`run_graph`、`_stream_graph`、
  `stream_graph`、`_finish_tool_loop`、`_astream_collect`、`_drain_events`、
  `_execute_tool_round`、`_astream_with_image_fallback`、
  `apply_context_guardrail`、`_bind_tools_schema`、`_build_initial_messages`、
  `_resolve_max_iterations`、`_is_budget_exceeded_outcome`、state/常量类
  `_AstreamCollectState`/`_FinishResult`/`_ToolRoundResult` 等仅被它们引用的
  私有助手（module 约 2226 → 1395 行，ruff 顺带清理 9 处未用 import）。
- 删除 `agent_runtime/graph_bridge.py`、`legacy_adapter.py` 及测试
  `test_graph_bridge.py`、`test_legacy_adapter.py`。
- 保留 AgentRuntime/服务层/8A 复用的共享函数（build_history_messages、
  build_tool_snapshots、tool_step_values、build_step_payload、GraphResult、
  extract/merge_token_usage、build_agent_error_payload、image/custom_content_
  blocks、rewrite_image_markdown、make_*_degrade_recoverer、load_runtime_context、
  build_system_prompt、apply_runtime_context_guardrail 等）。
- 删除行为（用户确认的选项甲，不复现则不保留）：页面工具预算超限即停 +
  固定文案；max_turns 收尾模型失败回退固定文案。

### 8D 测试收敛（实际）

- 反查每个 legacy 直连用例锁定行为在 AgentRuntime/服务/WS parity 的覆盖：
  - 已覆盖（删冗余）：未知工具 `tool_not_found` 回填、多工具单次回填、
    tool_started→completed 顺序、流关闭后不执行工具、max_turns 收尾/
    wrapup 失败转 `max_turns_reached`/非正上限无限、跨轮 usage、thinking、
    context-length 与纯文本拒图降级、确认等待、citations/knowledge_grounded
    等——均已在 `test_loop.py`/`test_tool_loop.py`/`test_model_recover.py`/
    `test_rest_parity.py`/`test_chat_flow.py` 覆盖。
  - 未覆盖（迁移到新入口单测）：多模态 user content 构造与文档/图片顺序迁到
    `agent_runtime/langchain_adapter.build_langchain_messages`
    （`test_langchain_context.py`）；历史角色/工具配对注入与历史附件内容还原
    迁到 `conversation/runtime.build_history_messages`
    （`test_tool_snapshots.py`）。
  - thinking 提取收口到 `agent_runtime.message_text.extract_thinking_text`
    （`test_runtime.py` 用例改用该 canonical 入口）。
- `test_runtime.py` 收敛为共享函数单测集（28 个）；删除的 run_graph/stream 直连
  用例不迁移为死代码驱动。
- `test_runtime_context.py` 移除 legacy `apply_context_guardrail`（旧消息格式
  断言不再适用），仅保留 `apply_runtime_context_guardrail` 整轮单元覆盖。
- `test_runtime_integration.py`（builtin local invoker 单测）判定已由 composition/
  parity 覆盖，整文件删除。

### 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests/agent_runtime apps/backend/tests/conversation apps/backend/tests/gateway -q`
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/agent_runtime apps/backend/app/modules/conversation apps/backend/tests/agent_runtime apps/backend/tests/conversation`
- `apps/backend/.venv/bin/python -m compileall -q apps/backend/app apps/backend/tests`
- `git diff --check`

### 预期结果

- legacy 主循环及仅其引用的私有助手、graph_bridge/legacy_adapter 全部删除，
  生产与测试不再引用已删符号（仅保留描述 parity 的注释）。
- 收敛后全量核心回归通过；不再有 collection error。
- Ruff（任务范围）、compileall、`git diff --check` 通过。

### 实际结果

- 定向新入口测试：`test_runtime.py` + `test_tool_snapshots.py` +
  `test_runtime_context.py` + `test_langchain_context.py` 定向 `50 passed`；
- 全量核心回归：`283 passed, 1 skipped`（较 8A 基线 312 的减少来自选项甲删除
  的 legacy 独占用例与冗余直连用例的收敛，非覆盖缺失——等价行为已由新引擎/
  parity 用例保留或在迁移后的单测中继续断言）。
- Ruff（任务范围）`All checks passed!`；compileall 通过；`git diff --check` 通过。
- 遗留一项与本任务无关、位于 `embed/repositories.py` 的既有无用 import（HEAD
  即存在，不属于本 request 范围，未改动）。

### 失败项与例外

- 8E 最终 REST 非流式 / REST SSE 真实人工测试仍待用户执行（按用户要求延后，
  不阻塞自动化；因此 phase 保持 `verify/active`，不置 `done`）。
- WS 断线重连后的前端消息列表渲染问题继续按用户要求延期，不属于本 request
  后端验收范围。
