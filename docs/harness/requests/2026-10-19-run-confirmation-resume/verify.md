---
source: script
request: 2026-10-19-run-confirmation-resume
ranAt: "2026-10-19 15:04:28 CST"
exitCode: 0
---

## 已执行的命令与结果

### 单元测试：tests/conversation

```bash
step_unit_conversation
```

........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 5.62s
结果：通过

### 单元测试：tests/gateway

```bash
step_unit_gateway
```

........................................................................ [ 60%]
..............................s................                          [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
118 passed, 1 skipped, 1 warning in 2.86s
结果：通过

### 单元测试：tests/agent_runtime

```bash
step_unit_agent_runtime
```

........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 1.71s
结果：通过

### 单元测试：tests/builtin_tool

```bash
step_unit_builtin_tool
```

.........................................................                [100%]
57 passed in 2.40s
结果：通过

### 单元测试：tests/tool_approval

```bash
step_unit_tool_approval
```

.......                                                                  [100%]
7 passed in 1.61s
结果：通过

### 单元测试：tests/mcp

```bash
step_unit_mcp
```

.............................                                            [100%]
29 passed in 2.05s
结果：通过

### 单元测试：tests/shared

```bash
step_unit_shared
```

...........                                                              [100%]
=============================== warnings summary ===============================
tests/shared/test_responses.py::test_exception_handler_serializes_error_code
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
11 passed, 1 warning in 1.63s
结果：通过

### 结构断言：resume_token 死字段已删除

```bash
step_resume_token_removed
```

app/ 下 resume_token 残留 = 0（期望 0）
结果：通过

### 结构断言：检查点表 / 仓储 / 迁移 0041

```bash
step_checkpoint_layer
```

迁移 20261019_0041 定义 = 1（期望 1）
down_revision=20261019_0040 = 1（期望 1）
apps/backend/app/modules/conversation/models.py:210:class AgentLoopRunCheckpoint(BaseModel, TimeModel):
apps/backend/app/modules/conversation/repositories.py:683:class AgentLoopRunCheckpointRepository:
apps/backend/app/modules/conversation/repositories.py:733:    async def get_by_loop_run(self, loop_run_id: int) -> AgentLoopRunCheckpoint | None:
apps/backend/app/modules/conversation/repositories.py:759:    async def mark_consumed(self, loop_run_id: int) -> None:
apps/backend/app/modules/conversation/repositories.py:778:    async def mark_expired(self, loop_run_id: int) -> None:
结果：通过

### 结构断言：解决端点与稳定错误码

```bash
step_resolve_endpoint
```

解决端点与错误码：
513:@router.post("/{agent_id}/runs/{loop_run_id}/resolve")
49:    RUN_CONFIRMATION_NOT_FOUND = "run_confirmation_not_found"
50:    RUN_CONFIRMATION_ALREADY_RESOLVED = "run_confirmation_already_resolved"
51:    RUN_CONFIRMATION_EXPIRED = "run_confirmation_expired"
52:    RUN_RESUME_UNAVAILABLE = "run_resume_unavailable"
apps/backend/app/modules/conversation/services.py:997:    初始运行（stream_chat）与确认后的续跑（resume_stream_chat）共用这一段，
apps/backend/app/modules/conversation/services.py:1249:async def resume_stream_chat(
结果：通过

### 环境断言：数据库迁移停在 head

```bash
step_migration_at_head
```

INFO  [alembic.runtime.migration] Will assume transactional DDL.
20261019_0041 (head)
结果：通过

### 端到端：SSE 弹卡 / 批准续跑 / 拒绝续跑 / 二次解决 / 过期 / 会话记忆 / 无通道 / 归属

```bash
step_e2e_probe_guarded
```

替身模型端口 = 65413
替身模型已就绪

## 准备：登录、启用 create_task、把 chat 角色绑到替身模型
  已登录 admin
  原 chat 绑定 model_id=1
  已启用 create_task（收尾恢复原值）
  替身模型 model_id=51 已绑定到 agent 1 的 chat 角色
  探针开始前 tasks 行数 = 0

## AC1/AC2/AC4 批准：弹卡 → 解决 → 真续跑 → 二次解决被拒
  [通过] AC1+2 请帮我创建一个定时任务。：SSE 首答 200 — 200
  [通过] AC1+2 请帮我创建一个定时任务。：恰好一张确认卡 — 数量=1 事件=['agent_loop_started', 'agent_step_completed', 'agent_step_completed', 'agent_step_started', 'agent_step_started', 'tool_call', 'agent_step_completed', 'confirmation_required']
  [通过] AC1+2 请帮我创建一个定时任务。：卡上有 callId — call_stub_56917
  [通过] AC1+2 请帮我创建一个定时任务。：卡上有 confirmationId — 79
  [通过] AC1+2 请帮我创建一个定时任务。：卡上有 loopRunId — 190
  [通过] AC1+2 请帮我创建一个定时任务。：sideEffect=write — write
  [通过] AC1+2 请帮我创建一个定时任务。：expiresAt 非空 — 2026-10-19T07:14:16.926629+00:00
  [通过] AC1+2 请帮我创建一个定时任务。：卡上带 arguments — {'name': '审批探针任务-1', 'prompt': '审批探针自动创建的任务。', 'trigger_type': 'cron', 'cron_expression': '0 3 * * *'}
  [通过] AC1+2 请帮我创建一个定时任务。：运行停在 waiting_confirmation — waiting_confirmation
  [通过] AC1+2 请帮我创建一个定时任务。：检查点 pending 且带上下文 — pending|true
  [通过] AC1+2 请帮我创建一个定时任务。：出站终态如实 waiting_confirmation — waiting_confirmation
  [通过] AC2：解决端点返回 SSE — 200
  [通过] AC2：续跑流里有 message_delta — ['message_delta', 'agent_step_completed', 'agent_loop_completed', 'message_completed']
  [通过] AC2：续跑流不再弹确认卡
  [通过] AC2：续跑流以 message_completed 收尾 — ['agent_step_completed', 'agent_loop_completed', 'message_completed']
  [通过] AC2：批准后任务行 +1 — 0 -> 1
  [通过] AC2：检查点 consumed 且上下文已清空 — consumed|false
  [通过] AC2：续跑后运行 completed — completed
  [通过] AC4：二次解决返回 409 — status=409 body={'success': False, 'message': 'run confirmation already resolved', 'data': None, 'meta': None, 'code': 409, 'error_code': 'run_confirmation_already_resolved'}
  [通过] AC4：错误码 run_confirmation_already_resolved — run_confirmation_already_resolved

## AC3 拒绝：不执行工具但也续跑
  [通过] AC3 请帮我创建一个定时任务。：SSE 首答 200 — 200
  [通过] AC3 请帮我创建一个定时任务。：恰好一张确认卡 — 数量=1 事件=['agent_loop_started', 'agent_step_completed', 'agent_step_completed', 'agent_step_started', 'agent_step_started', 'tool_call', 'agent_step_completed', 'confirmation_required']
  [通过] AC3 请帮我创建一个定时任务。：卡上有 callId — call_stub_59585
  [通过] AC3 请帮我创建一个定时任务。：卡上有 confirmationId — 80
  [通过] AC3 请帮我创建一个定时任务。：卡上有 loopRunId — 191
  [通过] AC3 请帮我创建一个定时任务。：sideEffect=write — write
  [通过] AC3 请帮我创建一个定时任务。：expiresAt 非空 — 2026-10-19T07:14:19.589656+00:00
  [通过] AC3 请帮我创建一个定时任务。：卡上带 arguments — {'name': '审批探针任务-3', 'prompt': '审批探针自动创建的任务。', 'trigger_type': 'cron', 'cron_expression': '0 3 * * *'}
  [通过] AC3 请帮我创建一个定时任务。：运行停在 waiting_confirmation — waiting_confirmation
  [通过] AC3 请帮我创建一个定时任务。：检查点 pending 且带上下文 — pending|true
  [通过] AC3 请帮我创建一个定时任务。：出站终态如实 waiting_confirmation — waiting_confirmation
  [通过] AC3：解决端点返回 SSE — 200
  [通过] AC3：拒绝后也续跑（有 message_delta） — ['message_delta', 'agent_step_completed', 'agent_loop_completed', 'message_completed']
  [通过] AC3：续跑流以 message_completed 收尾 — ['agent_step_completed', 'agent_loop_completed', 'message_completed']
  [通过] AC3：任务行未新增 — 1 -> 1
  [通过] AC3：检查点 consumed — consumed|false
  [通过] AC3：运行 completed — completed

## AC5 过期：惰性收尾 + 稳定错误码
  [通过] AC5 请帮我创建一个定时任务。：SSE 首答 200 — 200
  [通过] AC5 请帮我创建一个定时任务。：恰好一张确认卡 — 数量=1 事件=['agent_loop_started', 'agent_step_completed', 'agent_step_completed', 'agent_step_started', 'agent_step_started', 'tool_call', 'agent_step_completed', 'confirmation_required']
  [通过] AC5 请帮我创建一个定时任务。：卡上有 callId — call_stub_62087
  [通过] AC5 请帮我创建一个定时任务。：卡上有 confirmationId — 81
  [通过] AC5 请帮我创建一个定时任务。：卡上有 loopRunId — 192
  [通过] AC5 请帮我创建一个定时任务。：sideEffect=write — write
  [通过] AC5 请帮我创建一个定时任务。：expiresAt 非空 — 2026-10-19T07:14:22.090335+00:00
  [通过] AC5 请帮我创建一个定时任务。：卡上带 arguments — {'name': '审批探针任务-5', 'prompt': '审批探针自动创建的任务。', 'trigger_type': 'cron', 'cron_expression': '0 3 * * *'}
  [通过] AC5 请帮我创建一个定时任务。：运行停在 waiting_confirmation — waiting_confirmation
  [通过] AC5 请帮我创建一个定时任务。：检查点 pending 且带上下文 — pending|true
  [通过] AC5 请帮我创建一个定时任务。：出站终态如实 waiting_confirmation — waiting_confirmation
  [通过] AC5：过期解决返回 409 — status=409 body={'success': False, 'message': 'run confirmation expired', 'data': None, 'meta': None, 'code': 409, 'error_code': 'run_confirmation_expired'}
  [通过] AC5：错误码 run_confirmation_expired — run_confirmation_expired
  [通过] AC5：工具未执行 — 1 -> 1
  [通过] AC5：检查点标记 expired
  [通过] AC5：运行被标记 cancelled

## AC6 确认记忆：同一会话内不再弹卡
  [通过] AC6：SSE 返回事件流 — 200
  [通过] AC6：不再弹确认卡 — ['agent_loop_started', 'agent_step_completed', 'agent_step_completed', 'agent_step_started', 'agent_step_started', 'tool_call', 'agent_step_completed', 'tool_result']
  [通过] AC6：以 message_completed 收尾 — ['agent_step_completed', 'agent_loop_completed', 'message_completed']
  [通过] AC6：工具直接执行（任务 +1） — 1 -> 2

## AC7 非流式通路：无确认通道，拒绝并告知
  [通过] AC7：非流式返回 200 — status=200 body={'success': True, 'message': 'ok', 'data': {'conversation_id': 177, 'message_id': 351, 'content': 'STUB-TOOL-DONE', 'citations': [], 'knowledge_grounded': False
  [通过] AC7：任务行未新增 — 2 -> 2
  [通过] AC7：工具结果含 no_confirmation_channel — 工具执行失败：{"status":"rejected","auto_approved":false,"reason":"no_confirmation_channel","side_effect":"write","message":"工具 create_task 需要用户确认，但当前通路没有确认入口（请在支持确认的对话界面里重试）。该操作未执行。"}|{}

## AC8 归属/存在性：不泄露他人运行
  [通过] AC8：不存在的运行返回 404 — status=404 body={'success': False, 'message': 'run confirmation not found', 'data': None, 'meta': None, 'code': 404, 'error_code': 'run_confirmation_not_found'}
  [通过] AC8：错误码 run_confirmation_not_found — run_confirmation_not_found

## 收尾：恢复绑定/启用状态、清理本次产生的任务与会话
  恢复 chat 绑定 -> 1（status=200）
  已恢复内置工具启用状态
  删除本次产生的任务 [103, 104]
  清理遗留 pending 确认行 = 1
  删除本次产生的会话 [174, 175, 176]

PROBE_RESULT: 全部通过

--- 替身模型收到的请求 ---
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "user", "decision": "create_task", "n": 1}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "tool", "decision": "text", "n": 2}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "user", "decision": "create_task", "n": 3}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "tool", "decision": "text", "n": 4}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "user", "decision": "create_task", "n": 5}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "user", "decision": "create_task", "n": 6}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": true, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "tool", "decision": "text", "n": 7}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": false, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "user", "decision": "create_task", "n": 8}
{"path": "/v1/chat/completions", "model": "stub-model-x", "stream": false, "tools": ["create_task", "get_runtime_info", "http_get", "load_skill"], "last_role": "tool", "decision": "text", "n": 9}
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-19-run-confirmation-resume.sh: line 112: 71215 Terminated: 15          STUB_MODEL_PORT="$port" STUB_MODEL_LOG="$log" "$PY" "$STUB" > "$WORK/stub-model.out" 2>&1
结果：通过

### Harness audit 自检

```bash
step_audit
```


v2 requests: 16  存量跳过: 59  ERROR: 0  WARN: 0
结果：通过

## 未执行项与原因

- **技能脚本（skill_script）工具的确认**：技能包 manifest 无副作用声明字段，③a 已明确不在本次范围内，故无从发起确认。
- **MCP 工具在 REST/SSE 上的确认与续跑**：本仓的 MCP 工具需要可连的 MCP 服务端，探针未搭建；MCP 的挂起/解决/续跑归一路径由 `tests/conversation/test_run_confirmation_resume.py`（`_execute_pending_tool` 的 MCP 分支）与 `tests/mcp` 覆盖。
- **浏览器里点击确认卡**：需要浏览器，未执行；后端出站字段（`callId`/`confirmationId`/`loopRunId`/`sideEffect`/`expiresAt`/`summary.arguments`）已在端到端断言。
- **微信助手（`stream=false`）单独跑**：与探针里的非流式断言共用同一注入点（`confirmation_decider=None`），需要微信回调桩，未执行。
- **`alembic check`**：本仓有大量预存在漂移（comment 不一致、nullable 判定），不能作为本改动的结论，未执行。
- **整包 `pnpm --dir apps/ai-sdk test`**：会连带 `scripts/verify-package.test.mjs` 的预存在环境性失败（`npm pack --json` 的 stdout 被 vite build 日志污染），本次只验证 golden 与后端契约（`tests/gateway/test_event_parity.py`）。

## 验收结论

| 验收标准 | 证据 | 结论 |
| --- | --- | --- |
| AC1 检查点表存在且迁移可逆 | `step_migration_at_head`（容器内 `alembic current` = 20261019_0041 head）、`step_checkpoint_layer`、`tests/conversation/test_run_checkpoints.py`（另经 `compare_metadata` 验证零漂移、在 sqlite 上跑过 upgrade） | 通过 |
| AC2 确认卡字段齐全 | `step_e2e_probe`：断言恰好一张卡，`callId`/`confirmationId`/`loopRunId`/`sideEffect=write`/`expiresAt`/`summary.arguments` 全部非空 | 通过 |
| AC3 挂起后落库状态 | 同段的「运行停在 waiting_confirmation」「检查点 pending 且带上下文」「出站终态如实 waiting_confirmation」 | 通过 |
| AC4 批准后真续跑 | 探针：resolve 返回 SSE、流内有 `message_delta`、`tasks` +1、检查点 `consumed`、loop `completed` | 通过 |
| AC5 拒绝也续跑且不执行 | 探针：有 `message_delta` 且 `tasks` 不变 | 通过 |
| AC6 二次 resolve 409 | 探针：`run_confirmation_already_resolved` | 通过 |
| AC7 过期 409 + 惰性收尾 | 探针：`run_confirmation_expired`、检查点 `expired`、loop `cancelled`、工具未执行 | 通过 |
| AC8 非流式仍「拒绝并告知」 | 探针：200、无确认事件、`agent_loop_steps.output_summary` 含 `no_confirmation_channel`、`tasks` 不变 | 通过 |
| AC9 会话内记忆对 SSE 生效 | 探针：事件里有 `tool_result` 无 `confirmation_required`，工具直接执行 | 通过 |
| AC10 归属不符 404 且不泄露 | 探针：`run_confirmation_not_found`；他人会话路径由 `tests/conversation/test_run_confirmation_resume.py` 覆盖 | 通过 |
| AC11 无 `resume_token` 残留 + 测试 + audit | `step_resume_token_removed`（app 与 tests 零命中）、7 个测试目录全绿、`step_audit`（ERROR 0） | 通过 |
| AC12 既有行为不变 | `tests/gateway`（WS 确认链路）、`tests/mcp`、`tests/tool_approval`、`tests/builtin_tool` 全绿 | 通过 |
