# 设计说明

## 目标

- 解决 WebSocket 流式对话中请求级 `AsyncSession` 被跨 Task 并发使用、并在内层模型任务仍提交时被 `close()` 的问题；现象是客户端收到 `agent_request_failed`，`exceptionType=IllegalStateChangeError`。
- 受影响对象：网关 WebSocket 流式请求（`produce_embed_request`）、REST/SSE 流式请求（`stream_chat`）以及它们内部的工具执行链路。
- 完成后应产生可验证结果：任意提前结束路径（流内 `error` 事件、`result is None`、客户端取消、连接断开）下，内层模型 Task 在请求级 Session 关闭前已经结束；请求级 Session 在任一时刻只被一个 Task 使用。
- 引用 `research.md` 结论：`IllegalStateChangeError` 只能由同一 Session 被并发使用触发（SQLAlchemy 状态机挂在 SessionTransaction 实例上）；async generator 的终结不会跨层传播，必须逐层 `aclosing`；Pi 用"写入者唯一"的结构避免同类问题。

## 范围

- 流式事件链路的 Task 生命周期收口（P0）：
  - `apps/backend/app/modules/agent_runtime/conversation_adapter.py`：关闭其消费的 runtime 流。
  - `apps/backend/app/modules/gateway/runtime.py`：`stream_embed_chat` 关闭其消费的 `event_stream`。
  - `apps/backend/app/modules/conversation/services.py`：`stream_chat` 关闭其消费的 `event_stream`。
  - `apps/backend/app/modules/gateway/router.py`：`produce_embed_request` 关闭其消费的 `stream_embed_chat`。
  - `apps/backend/app/modules/conversation/router.py`：SSE 事件生成器关闭其消费的 `stream_chat`。
  - `apps/backend/app/modules/agent_runtime/runtime.py`：`AgentRuntime.stream` 的收尾必须等内层 Task 真正结束。
- 数据库 Session 归属收口（P1）：
  - 网关流式请求为模型/工具任务分配独立 Session；请求级 Session 只由消费方（loop step 与消息落库）使用。
  - 宿主工具审计仓库跟随工具 Session，连接级 `host_tool_session` 只服务连接主循环。
  - REST/SSE 流式请求同样为工具执行分配独立 Session。
- 测试：新增并发/生命周期回归测试；覆盖工具可读到已提交的会话数据。

## 非目标

- 不重构 `AgentRuntime.stream` 的 `asyncio.create_task` 结构（方案 C 留作后续 request）。
- 不改变任何对外协议字段、事件顺序、SSE/WS 消息格式。
- 不调整数据库连接池配置；仅在本 request 的风险章节记录连接占用变化。
- 不修复与本次无关的既有问题（如全量测试的同名模块收集冲突）。

## 风险

- 连接占用上升：每个流式请求会多占用一个数据库连接（请求级 + 工具 + 连接级宿主工具）。当前未配置 `pool_size`，使用 SQLAlchemy 默认（5 + 10 overflow），并发流式请求较多时需要后续评估。
- 可见性假设：工具切到独立 Session 后，只能看到已提交数据。依赖 `BaseRepository` 每次写操作都 `commit` 的既有约定，需用测试验证会话/消息在工具执行前已提交。
- 回归风险：`aclosing` 会在提前结束路径上新增一次生成器关闭，可能触发此前从未执行的清理分支（如 `AgentRuntime.stream` 的 `finally`），需跑通网关与对话相关全部用例。
- 兼容性风险：无对外契约变化。

## 停点判断

- 是否涉及架构边界变化：否，仍在网关/对话模块内部，模块边界不变。
- 是否涉及数据模型变化：否，无迁移。
- 是否涉及 API 契约变化：否，WS/SSE 事件与 REST 响应字段不变。
- 是否涉及鉴权或权限行为变化：否。
- 结论：不触发四类人工确认条件；方案要点仍需用户确认后进入实现（用户已确认"P0+P1 一起修"）。

## 验收标准

- 流式请求在任何提前结束路径下，内层模型 Task 都在请求级 Session 关闭前结束；`close()` 不再与 `commit()` 并发。
- 请求级 Session 只被消费方 Task 使用；工具执行使用独立 Session；连接级宿主工具 Session 只被连接主循环使用。
- WS 与 REST/SSE 两条流式路径行为一致。
- 现有 `tests/gateway`、`tests/conversation`、`tests/agent_runtime` 用例全部通过，且新增回归测试能拦住"提前结束时不关闭内层流"的退化。
- `ruff check` 通过。

## 变更记录

### 初始版本

- 时间：2026-09-18
- 变更原因：首次创建 request，承接 WS 流式请求 `IllegalStateChangeError` 的定位结论
- 变更内容：确定 P0（逐层关闭生成器 + 内层 Task 确定性 join）与 P1（工具执行独立 Session）两项修改，并明确两者必须同批完成
- 影响章节：全部
- 是否触发人工确认：否（不改变数据模型/API/鉴权/模块边界）；用户已确认方案方向

### 2026-09-18 实施方式细化：P0 从「逐层 aclosing」改为「Model Task 登记 + 最外层 join」

- 时间：2026-09-18
- 变更原因：进入实现后发现，按「逐层 `aclosing`」落地需要同时改 5 层生成器，任一层漏改或将来新增一层都会静默复现同一个竞态；而真正需要守住的约束只有一条——**在退出持有数据库 Session 的作用域之前，不允许还有其它 Task 使用这组 Session**。
- 变更内容：
  - `AgentRuntime` 新增 `on_task_started` 钩子，把内部 `asyncio.create_task(loop.run(...))` 生成的模型 Task 交给调用方登记（`agent_runtime/runtime.py`、`agent_runtime/composition.py`）。
  - 网关 `produce_embed_request` 与 REST/SSE `events()` 在退出 `async with`（关闭 Session）前调用新增的 `cancel_and_join_tasks`，确定性取消并等待全部模型 Task 收尾。
  - 逐层 `aclosing` 不再作为实现手段；调研结论（`GeneratorExit` 不跨层传播）仍作为「为什么不能只改一层」的依据保留。
- 影响章节：范围（P0 的实现手段）、风险、验收标准
- 是否触发人工确认：否（仅实现手段细化，不改变范围、对外契约、数据模型与模块边界）
