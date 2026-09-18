# 业界调研记录

## 调研问题

- 本次要解决什么问题：WebSocket 流式对话中，请求级 `AsyncSession` 被两个 asyncio Task 共用，且在外层任务收尾时被 `close()`，与内层模型任务的 `commit()` 相撞，抛出 `IllegalStateChangeError`（`Method 'close()' can't be called here; method 'commit()' is already in progress ... <SessionTransactionState.CLOSED: 5>`），请求以 `agent_request_failed` 结束。
- 调研结果将影响哪些范围、架构、接口或实现决策：影响网关/对话流式路径的任务生命周期归属、工具执行的数据库 Session 归属；不改变对外 API 契约和数据模型。

## 功能复杂度

- 级别：核心功能（Agent 主循环 + 会话持久化）
- 选择理由：涉及 Agent Loop、工具执行、会话持久化的非局部决策，属于仓库 AGENTS.md 明确要求先调研的方向
- 最低调研要求：至少一个成熟 Agent 项目或官方资料的实际实现

## 参考依据

### 来源 1

- 类型：成熟开源项目（本机源码）
- 名称：Pi `packages/session-backends/sqlite-node`
- 链接：`/Users/lixingwen/xw/git/pi/packages/session-backends/sqlite-node/src/sqlite/repo.ts`、`.../sqlite/types.ts`
- 版本或发布日期：本机 checkout（2026-09 读取）
- 调研日期：2026-09-18
- 核心做法：会话持久化走**同步 SQLite**，写操作用 `db.transaction(() => {...})` 同步回调提交，并对元数据写入引入 writer lease（`claimWriterLease`/`releaseWriterLease`）串行化写入者；事务回调内不允许返回 Promise。
- 对本项目的启发：Pi 从结构上排除了"事务在 await 中间被挂起、另一个任务插进来"的可能。我们无法改成同步驱动，因此等价目标是：**一个 AsyncSession 同一时刻只属于一个 Task**，且任何 Task 结束前必须完成自己 Session 的收尾。

### 来源 2

- 类型：官方文档 / 官方源码
- 名称：SQLAlchemy 2.0 `IllegalStateChangeError` 状态机（isce）
- 链接：`apps/backend/.venv/lib/python3.12/site-packages/sqlalchemy/orm/state_changes.py:120`；错误页 https://sqlalche.me/e/20/isce
- 版本或发布日期：本机安装版本（SQLAlchemy 2.x）
- 调研日期：2026-09-18
- 核心做法：`SessionTransaction.commit/close` 由 `_StateChange.declare_states` 装饰，状态（`_state`/`_next_state`/`_current_fn`）挂在 **SessionTransaction 实例**上；当某方法仍在进行中（`_next_state = CHANGE_IN_PROGRESS`）时再次进入另一个状态变更方法，即抛 `IllegalStateChangeError`。
- 对本项目的启发：该报错只能由"同一个 Session 对象被并发使用"触发；`close()` 在 `commit()` 进行中被调用，说明关闭方与提交方不是同一个 Task。

### 来源 3

- 类型：本项目历史决策 + 现存补丁
- 名称：`2026-08-05-agent-loop-observability` 的 fix 记录；`apps/backend/app/modules/builtin_tool/services.py:103-108`
- 链接：`docs/harness/requests/2026-08-05-agent-loop-observability/spec.md`
- 版本或发布日期：2026-08-05
- 调研日期：2026-09-18
- 核心做法：当时同类问题（实时 `tool_started` 落库与工具查询复用同一 `AsyncSession`）的解法是"事件消费确认握手，落库完成后才放行工具访问仓储"；统一 AgentRuntime 后该握手已不存在，只剩 `get_runtime_info` 单点使用独立 Session 的绕行补丁。
- 对本项目的启发：问题会复发，说明补在"某个工具"上不成立；需要补在**Session 归属**这条接缝上。

### 来源 4

- 类型：本地可复现实验（Python 语言语义）
- 名称：async generator 终结语义实验
- 链接：`/tmp/asyncgen_demo.py`、`/tmp/asyncgen_demo2.py`
- 版本或发布日期：Python 3.12.12（后端 venv）
- 调研日期：2026-09-18
- 核心做法：从 `async for` 循环体内 `return` 时，被迭代的 async generator **不会同步终结**；只在最外层加 `contextlib.aclosing` 也不够，因为 `GeneratorExit` 不会向内层生成器传播。
- 实验结果：
  - 仅最外层 `aclosing`：`result: early-return | inner finalized: []`（内层 `finally` 未执行）
  - 每一层都 `aclosing`：`result: early-return | inner finalized: ['inner-finally']`
- 对本项目的启发：模型循环 task 的取消是被生成器 `finally` 驱动的，因此**必须每一层都 aclose**，否则"消费方已退出、内层 task 还活着"是必然竞态，而不是偶发。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：只在最外层 `aclosing` | 改动最小 | 实验证明 `GeneratorExit` 不跨层传播，内层 task 仍会孤儿化 | 低 |
| 方案 B：逐层 `aclosing` + 内层 task 确定性 join + 工具执行独立 Session | 同时消除"close/commit 撞车"和"同 Session 并发写"两类问题；改动集中在流式路径接缝 | 每请求多占用一个数据库连接；需要同时改 WS 与 REST/SSE 两条路径 | 高 |
| 方案 C：取消 `asyncio.create_task`，改成同 Task 驱动事件消费 | 从根上消除跨任务 | 需要重构 AgentRuntime 流式实现，改动面与回归风险大 | 中（留作后续） |
| 方案 D：恢复"事件消费确认握手"串行化同一 Session | 复用历史方案 | 只缓解并发写，`close()` 与 `commit()` 的时序仍不可控；降低流式吞吐 | 中 |

## 最终决策

- 选择方案：方案 B
- 选择原因：报错由"跨 Task 共用 Session + Task 生命周期不闭环"共同造成，只解决其中一半仍会复发（来源 3 已证明）。方案 B 的两个动作分别对应两个必要条件，且不改变对外契约。
- 不选择其他方案的原因：A 已被实验证伪；C 改动过大，与本次止血目标不匹配；D 治标且牺牲吞吐，历史实现已被统一运行时移除。
- 对后续 spec、plan 或人工确认的影响：不触发架构/数据模型/API/鉴权四类人工确认条件；实现前仍需用户确认方案要点。

## 剩余风险

- 资料时效性：SqlAlchemy 与 Python 语义均为本机版本实测，结论稳定。
- 与本项目上下文的差异：Pi 使用同步 SQLite，无法直接照搬，只取其"写入者唯一"的结论。
- 尚未验证的假设：把工具执行迁到独立 Session 后，工具是否仍能读到请求级 Session 已提交的会话/消息数据（依赖 `BaseRepository` 每次写操作都 commit 的既有约定，需在验证阶段用测试覆盖）。
