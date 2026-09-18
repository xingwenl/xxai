# 实施计划

## 改动清单

### 1. 模型 Task 登记 + 最外层确定性 join（P0）

- `agent_runtime/runtime.py`：新增模块级 `cancel_and_join_tasks(tasks)`；`AgentRuntime` 新增 `on_task_started` 钩子，在 `asyncio.create_task(loop.run(...))` 之后上报 Task。
- `agent_runtime/composition.py`：`build_langchain_runtime` 透传 `on_task_started`。
- `gateway/runtime.py`（`stream_embed_chat`）/ `conversation/services.py`（`stream_chat`）：新增 `on_model_task_started` 参数并透传给 runtime。
- `gateway/router.py`（`produce_embed_request`）：登记模型 Task，在 `async with`（Session 作用域）内、退出前 `await cancel_and_join_tasks(model_tasks)`。
- `conversation/router.py`（SSE `events()`）：同上，由 SSE 生成器持有工具 Session 并负责 join。

理由：模型 Task 的取消原本由生成器 `finally` 驱动，而 `async for` 提前 `return` 不会同步终结被迭代的生成器（本地实验证明 `GeneratorExit` 不跨层传播）。把 Task 直接交给持有 Session 的作用域登记并 join，等价于"退出前不允许有其它 Task 仍在用这组 Session"这一真实约束，且只有一个收口点。

> 实施偏差（2026-09-18）：原计划的「逐层 `aclosing`」在实现时改为本方案，原因与影响见 `spec.md` 的「2026-09-18 实施方式细化」变更记录。

### 2. 内层 Task 确定性 join（P0）

- `agent_runtime/runtime.py`（`AgentRuntime.stream`）：
  - 保留 `finally` 中的 `task.cancel()`；
  - 明确等待 `task` 收尾，并补注释说明"调用方持有请求级 Session，提前返回会导致 Session 在工具仍 commit 时被关闭"。

### 3. 工具执行使用独立 Session（P1）

- `gateway/router.py`（`produce_embed_request`）：新增第二个 `get_session_factory()()` 作为工具 Session，构造 `RuntimeToolDispatcher(session=tool_session, host_tool_repo=HostToolRepository(tool_session))`；请求级 Session 只给 `ConversationRepository`。
- `conversation/router.py`（`_prepare`）：新增可选 `tool_session` 参数，`invoke` 闭包内的 MCP/技能/内置工具与 `AssetRepository` 使用工具 Session；`load_runtime_context`/检索仍用请求级 Session。
- `conversation/router.py`（SSE `events()`）：在生成器内创建工具 Session 并传入 `_prepare`。

### 4. 测试

- `tests/agent_runtime/test_stream_task_ownership.py`：`AgentRuntime.stream` 必须上报模型 Task；`cancel_and_join_tasks` 必须等到任务清理逻辑执行完成。
- `tests/gateway/test_stream_session_teardown.py`：流内提前结束（只有 error 事件）时，模型 Task 的清理必须早于任一 Session 关闭。
- `tests/conversation/test_tool_session_isolation.py`：`_prepare` 的 builtin/skill_script/skill_instruction/MCP 分支必须绑定工具 Session；工具 Session 只能读到已提交数据。

## 回滚方案

- P0/P1 均为纯内部改动，回滚方式为还原上述文件；无数据迁移、无协议变更，回滚不需要数据修复。

## 验证命令

```bash
cd apps/backend
poetry run pytest tests/gateway tests/conversation tests/agent_runtime -q
poetry run pytest tests -q \
  --ignore=tests/embed/test_models.py \
  --ignore=tests/user/test_routes.py \
  --ignore=tests/user/test_services.py \
  --ignore=tests/model_registry/test_models.py \
  --ignore=tests/skill_runner/test_services.py
poetry run ruff check app/modules/gateway app/modules/conversation app/modules/agent_runtime
```

## 风险与依赖

- 依赖 `BaseRepository` 每次写操作立即 commit 的既有约定（工具切到独立连接后只能看到已提交数据）。
- 连接占用增加，见 `spec.md` 风险章节。
