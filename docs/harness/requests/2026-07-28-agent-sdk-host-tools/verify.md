# 验证记录

## 2026-09-19 宿主工具审计时间列读写口径修复（fix）

### 排查结论（真实链路证据）

用户提供的失败事件（`evt_53`，`toolName=page_snapshot`，`outputSummary=工具执行失败`）对应的服务端日志序列为：

```text
01:40:15,258 | INFO | gateway.dispatcher | Host tool dispatched request_id=msg_3_1789753210495 call_id=call_00_eyA8sEJUtvHdR9i2jE9Q2386 tool=page_snapshot side_effect=none requires_confirmation=False audit_status=running args={}
01:40:15,273 | INFO | gateway.router     | Host tool result received call_id=call_00_eyA8sEJUtvHdR9i2jE9Q2386 tool=page_snapshot result_bytes=5379
01:40:15,281 | INFO | gateway.runtime    | Tool step completed request_id=msg_3_1789753210495 tool=page_snapshot call_id=... status=failed error_code=tool_failed error_message=工具执行失败
```

- 页面**执行成功**（同一 `call_id` 有 `Host tool result received`，第二次调用 `result_bytes=5629`），但模型只收到失败结果。
- 同一请求内两次调用都缺 `Host tool completed` / `Host tool failed` / `Host tool wait timed out`，说明异常发生在 `Host tool dispatched` 之后、带日志的 `try` 之前的那段代码里，唯一可达的抛错点是等待上限换算：
  ```python
  timeout_seconds = max(0.0, (existing.expires_at - utc_naive_now()).total_seconds())
  ```
- 根因：`host_tool_call_audits.expires_at` 在 `migrations/versions/20260728_0010_host_tools.py` 里是 `sa.DateTime(timezone=True)`（PG `TIMESTAMP WITH TIME ZONE`），asyncpg 读回 **aware**；`utc_naive_now()` 是 naive；两者相减抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`。异常逃出 `_invoke_host_tool` 后被 AgentLoop 归一成失败的 `ToolOutcome`（`tool_failed`），于是"页面成功、模型看到失败"。
- 时间线解释"此前能用、现在不能用"：该换算式由 `1ae78ed`（2026-09-07）引入；本地数据卷在 2026-08-31 按 PG17 重建（`fe32a90` 注释：'本地既有数据卷由 PG17 初始化'）后，`host_tool_call_audits` 由 alembic 迁移建表（aware），而此前由 `create_all` 建表（naive，2026-07-29 的验证记录正是那一种形状）。

### 排查结论 2（读侧修好后的第二层根因：写入口径）

读侧修复后用户反馈页面回传结果落到了 `Host tool result ignored reason=no_pending_future`，即 Future 已不在连接容器里。定位为**写入侧口径错误**：

- `expires_at` / `started_at` / `completed_at` 用 `utc_naive_now()`（naive UTC）写入，而列是 `TIMESTAMP WITH TIME ZONE`。
- asyncpg 的 `timestamptz_encode`（`.venv/.../asyncpg/pgproto/codecs/datetime.pyx:202`）执行 `utc_dt = obj.astimezone(utc)`；Python 语义下 **naive 值按本地时间解释**，东八区即整体偏移 8 小时。
- 结果：新建审计行的 `expires_at` 读回是"8 小时前"，`wait_timeout_seconds()` 得到 0 → `Host tool wait timed out ... waited_seconds=0.0` → `finally` 释放 Future → 页面随后回传的结果被判为迟到结果丢弃（`reason=no_pending_future`），模型收到"工具执行超时"。
- 反向错误同样存在：`timestamp_encode`（同文件 `:142`）用 `obj - pg_epoch_datetime`（naive epoch），aware 值相减即抛 `can't subtract offset-naive and offset-aware datetimes` —— 正是 2026-07-29 记录的那次故障。两种口径混用都会坏，必须与列类型一致：本项目迁移里的列是 timestamptz，因此统一写 aware UTC。

修复前（把 `expires_at` 临时改回 naive）在回归用例中捕获到的日志，与线上症状完全一致：

```text
WARNING Host tool wait window already expired request_id=req_1 call_id=call-tz tool=page_snapshot audit_status=running
        expires_at=2026-09-18 16:12:41.716599+00:00 now_utc=2026-09-19 00:02:41.717139+00:00
WARNING Host tool wait timed out ... waited_seconds=0.0
WARNING Host tool execution timed out waiting for page result ... audit_status=running
WARNING Host tool failed ... error_code=host_tool_execution_timeout
FAILED tests/gateway/test_host_tool_timeout.py::test_timestamptz_audit_expiry_keeps_full_wait_window
```

（`expires_at` 比 `now_utc` 早 8 小时 = Asia/Shanghai 偏移，即 naive 被当成本地时间编码的证据。）

### 复现（修复前）

- 独立探针（`/private/tmp/probe_expires.py`，验证后不作为仓库文件保留）直接调用 `RuntimeToolDispatcher._invoke_host_tool`：
  ```text
  aware=False -> outcome.status=completed
  aware=True  -> TypeError: can't subtract offset-naive and offset-aware datetimes
  ```
- 新增回归用例在旧实现下的真实输出：
  ```text
  FAILED tests/gateway/test_host_tool_timeout.py::test_aware_expires_at_dispatches_host_tool_successfully
  TypeError: can't subtract offset-naive and offset-aware datetimes
    File ".../app/modules/gateway/dispatcher.py", line 432, in _invoke_host_tool
      max(0.0, (existing.expires_at - utc_naive_now()).total_seconds())
  1 failed, 4 passed
  ```

### 本次改动

- `host_tool/services.py`：新增 `as_utc()` 与 `wait_timeout_seconds()`；删除只服务 naive 列的 `utc_naive_now()`。
- `host_tool/repositories.py`、`gateway/dispatcher.py`：`started_at`/`completed_at`/`expires_at` 一律写 `datetime.now(UTC)`（aware）。
- `host_tool/models.py`：三列显式声明 `DateTime(timezone=True)`（对齐迁移，无 DDL）。
- `gateway/dispatcher.py`：宿主工具与 MCP 确认两处等待上限改用 `wait_timeout_seconds()`；等待上限计算、下发与等待纳入同一 `try/except Exception`；新增 `Host tool future registered` / `Host tool future released`（`pending_keys`）、`Host tool wait window already expired`（`expires_at`/`now_utc`）；`Host tool dispatched` 增 `wait_timeout_seconds`。
- `gateway/router.py`：`no_pending_future` 分支补 `future_found`/`future_done`/`pending_keys`。
- `gateway/runtime.py`：`failed` 步骤后新增 `Tool step failed detail`（`outcome_status` + 真实 `outcome_error`），落库字段仍为 `tool_failed`。
- `agent_runtime/loop.py`：工具调用异常分支新增 `Tool invocation raised`（含堆栈）。
- 测试：`tests/gateway/test_host_tool_timeout.py` 的假仓库按 asyncpg 语义区分 timestamptz / naive 两种列形状，新增"等待窗口保持 600s 且结果能回填并回收 Future""历史 naive 列仍可用"两个用例；`tests/host_tool/test_services.py` 覆盖 `as_utc`/`wait_timeout_seconds`。

### 命令与结果

- `cd apps/backend && poetry run ruff check app/modules/host_tool/services.py app/modules/gateway/dispatcher.py app/modules/gateway/runtime.py app/modules/agent_runtime/loop.py`
  - 实际：`All checks passed!`
- `cd apps/backend && poetry run pytest tests/host_tool/test_services.py -q` → `7 passed`
- `cd apps/backend && poetry run pytest tests/gateway/test_host_tool_timeout.py -q` → `5 passed`
- `cd apps/backend && poetry run pytest tests/gateway tests/host_tool tests/mcp tests/agent_runtime tests/conversation tests/embed -q`
  - 实际：`352 passed, 1 skipped`
- `cd apps/backend && poetry run pytest -q --import-mode=importlib`
  - 实际：`681 passed, 1 skipped`（上一轮记录的 `tests/builtin_tool/test_runtime_info.py` 失败属 00:00–08:00 东八区窗口的既有时间问题，本轮已随日期推进自愈）。
- `cd apps/backend && poetry run ruff check app/modules/host_tool/ app/modules/gateway/ app/modules/agent_runtime/loop.py tests/host_tool/ tests/gateway/`
  - 实际：`All checks passed!`（仓库级 `ruff check app tests` 仍报 `app/modules/embed/repositories.py:10` 的既有 F401，与本次改动无关，未改）。
- 修复前必失败证据（两处，均已复跑确认）：
  1. 把换算式还原为 `existing.expires_at - utc_naive_now()` → 回归用例稳定报 `TypeError: can't subtract offset-naive and offset-aware datetimes`；
  2. 把 `expires_at` 还原为 naive 写入 → `test_timestamptz_audit_expiry_keeps_full_wait_window` 失败，日志复现"8 小时前已过期 + `waited_seconds=0.0`"。

### 未执行项（需人工环境）

- 未重建/重启容器复跑真实页面链路（沙箱内 `docker` 与本地 5432 访问均被拒绝）。建议用户在容器更新后按以下顺序确认：
  1. `rg "Host tool future registered|Host tool dispatched" apps/backend/logs/api/app-*.log`：确认 `wait_timeout_seconds=600.0` 且 `pending_keys` 含当前 callId；
  2. `rg "Host tool completed|Host tool result received" apps/backend/logs/api/app-*.log`：确认结果被接受并回填；
  3. 出现 `Host tool wait window already expired` → 说明审计行的过期时间在过去（时间列读写口径问题复发，日志已带 `expires_at`/`now_utc`）；
  4. 出现 `Host tool result ignored reason=no_pending_future ... pending_keys=[]` → 请求已结束、页面结果迟到；`pending_keys` 含别的 callId → 页面回传的 callId 与下发的不一致；
  5. 出现 `Tool step failed detail` / `Host tool invocation failed` / `Tool invocation raised` → 直接给出真实原因与堆栈。

### 剩余风险

- 既有历史审计行中已经写坏的 `expires_at`（比真实时间早一个时区偏移）不会被回填修正；这些行会按"已过期"处理（等待立即超时并进入 failed 终态），需要时可按 `completed_at` 人工核对。
- 若某个环境的 `host_tool_call_audits` 仍是由 `create_all` 建出的 naive 列，写入 aware 值会抛 `can't subtract offset-naive and offset-aware datetimes`；本地与服务器都由 `alembic upgrade head` 建表，ORM 映射已同步为 `DateTime(timezone=True)`，新库不会再出现 naive 列。

## 2026-09-19 宿主工具执行失败排障日志增量（fix）

### 排查结论

- 绑定链路已在上一增量修复：`Model tools bound` 中 `bound` 已包含 `page_*`，日志证明模型拿到了工具。
- 失败原因此前完全不可见：`host_tool_error` 只落审计表、网关分发与等待分支无日志、工具步骤落库把原因统一成"工具执行失败"、SDK 在执行前工具丢失时静默返回。
- 已定位并复现一个真实缺陷（待确认后实现修复）：页面工具预算窗口锚定在 SDK 实例的首次页面工具调用，且不随用户消息重置。
  - 探针用例（临时文件，验证后已删除）：
    ```ts
    vi.setSystemTime(new Date('2026-09-19T00:00:00Z'))
    const snapshot = createPageTools({ maxDurationMs: 60_000 }).find(t => t.name === 'page_snapshot')!
    await snapshot.execute({}, {})            // 第 1 次调用：开启预算窗口
    vi.setSystemTime(new Date('2026-09-19T00:01:01Z'))  // +61s
    await snapshot.execute({}, {})            // 抛 page_tool_budget_exceeded
    vi.setSystemTime(new Date('2026-09-19T00:30:00Z'))  // +30min
    await snapshot.execute({}, {})            // 仍抛 page_tool_budget_exceeded（永久失败）
    ```
  - 结论：长生命周期页面（接入方配置 `maxDurationMs: 60_000`）在首次页面工具调用 60 秒后，所有页面工具调用都会返回 `page_tool_budget_exceeded`，表现为"注册成功但执行失败"，刷新页面即恢复。

### 本次改动

- 服务端新增关键字：`Host tool dispatched`、`Host tool completed`、`Host tool failed`、`Host tool wait timed out`、`Host tool invocation failed`、`Host tool result received`、`Host tool error received`、`Host tool result too large`、`Host tool result ignored`、`Host tool confirmation resolved`、`Tool step completed`、`Tool not registered for execution`、`Tool not found in invoker catalog`、`Tool invocation raised`。
- SDK 新增关键字：`[xxai-agent][host-tool] call received` / `invalid arguments` / `result sent` / `execution failed` / `tool not registered` / `tool disappeared before execution`。
- SDK 行为修复：`runHostTool()` 在执行前找不到工具时不再静默返回，改为回传 `host_tool_not_registered`，避免服务端空等 10 分钟。

### 命令与结果

- `cd apps/backend && poetry run ruff check app/modules/gateway/dispatcher.py app/modules/gateway/router.py app/modules/gateway/runtime.py app/modules/agent_runtime/tool_loop.py app/modules/agent_runtime/composition.py`
  - 实际：`All checks passed!`
- `cd apps/backend && poetry run pytest tests/gateway -q`
  - 实际：`107 passed, 1 skipped`（首轮因测试替身没有 `tool_name` 字段报 3 处 AttributeError，已改为 `getattr(audit, "tool_name", None)` 后通过）。
- `cd apps/backend && poetry run pytest tests/gateway tests/host_tool tests/agent_runtime tests/conversation tests/embed -q`
  - 实际：`326 passed, 1 skipped`。
- `cd apps/ai-sdk && npx vitest run src/core/__tests__/client.test.ts src/core/__tests__/page-tools.test.ts`
  - 实际：`29 passed`（覆盖宿主工具执行与页面工具预算用例）。
- `cd apps/ai-sdk && npx vitest run`
  - 实际：`1 failed | 19 passed`，`131 passed`。唯一失败为既有环境问题：`chat-message.ssr.test.ts` 依赖未安装的 `@vue/server-renderer`，与本次改动无关（`npm run type-check` 报同一缺失模块）。

### 未执行项（需人工环境）

- 未重建容器（`docker compose up -d --build api` 后重启 API）复跑真实页面链路；复现一次后可用以下顺序核对：
  1. `rg "Host tool dispatched|Host tool (completed|failed|result received|error received)" apps/backend/logs/app-*.log`；
  2. 若只有 `Host tool dispatched` 且随后出现 `Host tool wait timed out`，说明页面没回传，继续看浏览器控制台的 `[xxai-agent][host-tool]`；
  3. `rg "Tool step completed" apps/backend/logs/app-*.log` 对照前端工具卡片文案。

## 2026-09-19 宿主工具未绑定给模型修复（fix）

### 失败复现（修复前，针对运行中的本地后端）

- 直连本地网关脚本 `/private/tmp/repro_host_tools_full.py`：用 `/api/agent-token` 取 token 连接 `ws://127.0.0.1:8000/api/v1/ws/agents/1`，注册宿主工具 `debug_ping` 后发送"请调用 debug_ping 工具"。
- 服务端日志：`Temporary host tools enabled for connection: ['debug_ping']`（注册被接受）。
- 客户端收到的模型回答：`我没有名为 debug_ping 的工具，无法调用它——当前会话的工具清单里并不存在这个名字。`，事件流中没有任何 `host_tool_call`。
- 服务端请求日志：`Embed chat started ... host_tool_count=1`（宿主工具只进了 system prompt），`Starting embed chat request ...` 行的工具清单里没有 `debug_ping`。
- 结论：注册链路正常，绑定链路断裂；根因位于 `app/modules/gateway/runtime.py` 的 `tools = runtime_tools if runtime_tools is not None else host_tools or []`。

### 修复后（本仓库自动化验证）

- `cd apps/backend && poetry run pytest tests/gateway/test_chat_flow.py tests/gateway/test_replay.py -q`
  - 实际：`24 passed`。新增用例：`test_merge_model_tools_keeps_runtime_and_host_tools`、`test_embed_chat_binds_host_tools_to_model`（断言模型 `bind_tools` 收到 `http_get` + `debug_ping`）、`test_embed_chat_dispatches_registered_host_tool_call`（断言模型 tool_call 真的分发到宿主工具回调并把结果回填回答）、`test_replay_store_skips_missing_stream`、`test_numeric_sequence_floor_accepts_redis_stream_id`。
- 回归验证：临时把 `runtime.py` 的绑定恢复成修复前的二选一写法后，`test_embed_chat_binds_host_tools_to_model` 与 `test_embed_chat_dispatches_registered_host_tool_call` 均失败（`assert [] == ['debug_ping']`），确认两个用例真实覆盖本次缺陷。
- `cd apps/backend && poetry run pytest tests/gateway tests/host_tool tests/embed tests/conversation -q`
  - 实际：`212 passed, 1 skipped`。
- `cd apps/backend && poetry run pytest -q --import-mode=importlib`
  - 实际：`1 failed, 669 passed, 1 skipped`。
  - 唯一失败 `tests/builtin_tool/test_runtime_info.py::test_returns_model_version_usage_and_client_identity` 与本次改动无关，且可稳定复现成因：该用例写入的用量记录落在 UTC 日期，而工具用本地 `date.today()`（当前 `2026-09-19`，UTC 仍为 `2026-09-18`）统计"今日用量"，属 00:00–08:00（东八区）窗口内的既有时间相关失败。
  - 复核证据：`cd apps/backend && TZ=UTC poetry run pytest tests/builtin_tool/test_runtime_info.py -q` → `3 passed`（同一用例在本机时区下失败）。
- `cd apps/backend && poetry run ruff check app/modules/gateway/replay.py app/modules/gateway/router.py app/modules/gateway/runtime.py tests/gateway/test_chat_flow.py tests/gateway/test_replay.py`
  - 实际：`All checks passed!`。
- `cd apps/backend && poetry run black --check app/modules/gateway/{replay,runtime}.py`
  - 实际：两文件仍会 reformat，但差异行全部位于本次改动之前就存在的代码（已用 `git show HEAD:<file>` 复现同样失败）；本次新增行未出现在 Black diff 中，因此不批量改动无关行。

### 未执行项（需人工环境）

- 运行中的 `ai-base-api-1` 容器镜像内是构建时代码，本次未重启/重建容器，因此"修复后在真实页面上被模型调用"仍待人工确认：`docker compose up -d --build api` 后重跑 `/private/tmp/repro_host_tools_full.py`，预期收到 `host_tool_call`；并可查以下关键日志：
  - `Embed request host tools request_id=... registered=[...] bound=[...]`
  - `Model tools bound request_id=... runtime_tools=[...] host_tools=[...] bound=[...]`
  - `Starting embed chat request ... runtime_tools=[...] host_tools=[...]`

## 当前阶段

- 阶段：verify
- 状态：验证完成
- 说明：已完成自动化检查、真实 PostgreSQL、DeepSeek 模型和 WebSocket 宿主工具联调。

## 2026-07-31 临时工具增量验证

- `cd apps/ai-sdk && npm run test -- --run src/core/__tests__/websocket.test.ts && npm run type-check`
  - 实际：8 个 WebSocket 测试通过，类型检查通过；覆盖内存工具首次连接和重连自动注册。
- `cd apps/backend && poetry run pytest tests/host_tool/test_services.py -q`
  - 实际：5 个测试通过；覆盖临时工具策略仅在内存中生成。
- `cd apps/ai-sdk && npm run test -- --run && npm run type-check`
  - 实际：5 个测试文件、20 个测试通过，类型检查通过。
- `cd apps/backend && poetry run pytest tests/gateway tests/host_tool tests/embed -q`
  - 实际：48 个测试通过、1 个既有测试跳过；保留 1 个既有 Starlette 弃用警告。
- `git diff --check`
  - 预期：无空白错误。

## 已执行命令与结果

- `cd apps/backend && poetry run pytest`
  - 预期：后端全量测试通过。
  - 实际：`127 passed, 1 skipped, 1 warning`。

- `cd apps/backend && poetry run ruff check <本次触及后端文件>`
  - 预期：本次触及范围无 Ruff 错误。
  - 实际：`All checks passed!`。

- `cd apps/backend && poetry run black --check <本次触及文件>`
  - 预期：本次新增/修改后端文件格式通过。
  - 实际：格式化后通过；全仓 Black 仍有 2A 之前已有文件未格式化，未对无关文件做批量改动。

- `cd apps/backend && poetry run alembic heads`
  - 预期：Phase 2B migration 为唯一 head。
  - 实际：`20260728_0010 (head)`。

- `cd apps/backend && poetry run alembic check`
  - 预期：迁移与模型无差异。
  - 实际：未完成；当前环境无法连接 PostgreSQL，报 `PermissionError: [Errno 1] Operation not permitted`。

- `cd apps/backend && poetry run python scripts/seed_demo_host_tools.py`
  - 预期：写入 Demo 工具策略、Agent 绑定和 Client 绑定。
  - 实际：`已配置 Demo 宿主工具: get_weather, calculate_total, get_order_status`。

- 真实 WebSocket 联调脚本（使用 `httpx`、`websockets`、DeepSeek 和本地 PostgreSQL）
  - 预期：依次收到 `session_ready`、`message_started`、`host_tool_call`、`message_delta`、`message_completed`。
  - 实际：顺序符合预期；`host_tool_call` 为 `get_weather`，参数为 `{"city":"上海"}`；回传 Demo 结果后最终回答包含 `26°C`、`多雨`。
  - 审计证据：`host_tool_call_audits.call_id=call_00_eeoGEg9tZOSgRCSZXIyj7348`，状态 `succeeded`，结果包含 `temperature=26`、`condition=多雨`。

- `cd apps/ai-sdk && npm run type-check && npm run test -- --run && npm run build`
  - 预期：SDK 类型检查、Vitest 和生产构建通过。
  - 实际：`type-check` 通过；`3 test files / 11 tests passed`；Vite ESM/UMD 构建通过。

## 已覆盖行为

- 三重白名单求交、Schema 基本校验、状态迁移和敏感字段递归脱敏。
- Host Tool 策略/Agent 绑定/Client 绑定模型、管理路由、token `host_tools` claim。
- 临时工具模式下 token 不需要 `host_tool_names`；工具注册定义由 SDK 内存缓存并在重连后重新发送。
- WebSocket 注册、`host_tool_call` 协议、确认、结果/错误回传和 `callId` 状态更新。
- Agent Runtime 的宿主工具绑定、页面结果回写和继续生成路径。
- SDK 注册、参数校验、确认回调、超时、结果大小限制和 destroy 清理。

## 未验证项与剩余风险

- 未在本轮执行 Redis 重放场景的多连接 E2E；真实 PostgreSQL、WebSocket 和模型 tool-call 主链路已完成。
- 未完成完整 Playwright 浏览器 E2E；本轮通过协议探针完成等价的真实 WebSocket 联调。SDK 校验器仍覆盖核心 object/required/properties/enum 语义，尚未引入完整 JSON Schema Draft 2020-12 浏览器验证器。
- 真实页面函数执行后的“结果已产生但回传丢失”恢复仍需部署环境验证；当前服务端遵守 `callId` 不盲目重试。
- 保留已有 FastAPI/Starlette 的一个弃用警告，不影响本次测试结果。

## Bugfix 验证

- 失败复现：新增的 native timer receiver 测试在修复前以 TypeError: Illegal invocation 失败。
- 修复后：同一测试通过，handleClose 触发重连时不再抛出 receiver 错误。

## Demo 自动调用接入

- 已验证：Demo token proxy 接收重复的 host_tool_names query 参数，并传入 EmbedTokenRequest。
- 已验证：seed 脚本通过 Ruff 和 Python compileall。
- 已完成：执行 seed 后，真实调用天气工具成功产生 `host_tool_call`，SDK/协议探针回传结果，后端审计为 `succeeded`，模型返回包含工具结果的最终回答。

## 本轮 Bugfix 验证

- 失败复现：`cd apps/backend && poetry run pytest tests/host_tool/test_repositories.py::test_updating_status_with_unchanged_schema_keeps_tool_enabled -q`，修复前失败，确认相同 Schema 会被错误禁用。
- 修复后：`cd apps/backend && poetry run pytest tests/host_tool -q`，10 passed。
- 静态检查：`cd apps/backend && poetry run ruff check app/modules/host_tool/repositories.py tests/host_tool/test_repositories.py`，通过。
- 未执行项：未使用用户提供的真实 JWT/curl 直接联调，原因是当前验证已覆盖导致状态不变的 repository 根因；仍建议在后台页面人工点击一次启用开关确认端到端响应。

- 失败复现：真实 PostgreSQL 写入审计时因 `TIMESTAMP WITHOUT TIME ZONE` 接收到带时区 datetime，报 `can't subtract offset-naive and offset-aware datetimes`。
- 修复后：审计创建和状态更新使用 UTC 无时区时间；真实调用成功，审计状态为 `succeeded`。
- 额外修复：runtime 异常现在通过非空 `error` payload 回传客户端，避免页面永久停留在发送中。
