---
source: script
request: 2026-10-19-context-usage-and-compaction
ranAt: "2026-10-20 14:25:59 CST"
exitCode: 0
---

## 已执行的命令与结果

后端单元测试（改了 agent_runtime 的 loop/events 与 conversation 的上下文构造，
因此额外回归 agent_runtime / gateway / embed 三个目录）。新测试文件：
`tests/conversation/test_context_compaction.py`（纯函数与控制器顺序）、
`tests/conversation/test_compaction_persistence.py`（sqlite 落库/幂等/坏摘要 + 
自动触发的完整链路 transform→落库→事件 + 压缩后新请求从摘要续读）、
`tests/conversation/test_rest_parity.py`（REST 历史真的到达模型）、
`tests/agent_runtime/test_context_metrics.py`（新事件经 loop 发出）、
`tests/embed/test_context_compaction_route.py`（REST 投影与 404）。

### 后端单测：conversation（AC1）

```bash
step_unit_conversation
```

........................................................................ [ 44%]
........................................................................ [ 89%]
.................                                                        [100%]
161 passed in 8.88s
结果：通过

### 后端单测：agent_runtime（AC1/AC6 事件）

```bash
step_unit_agent_runtime
```

........................................................................ [ 60%]
...............................................                          [100%]
119 passed in 2.12s
结果：通过

### 后端单测：gateway（含祖传 golden 对拍）

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
118 passed, 1 skipped, 1 warning in 2.61s
结果：通过

### 后端单测：embed（AC5 手动压缩 REST）

```bash
step_unit_embed
```

...........................                                              [100%]
27 passed in 3.33s
结果：通过

### AC1：阈值必须早于护栏预算（否则护栏会先硬删历史）

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from app.core.config import get_settings
  from app.modules.conversation.runtime import (
      _resolve_guardrail_budget,
      resolve_compaction_threshold,
  )
  settings = get_settings()
  for window in (1000, 128_000, 1_000_000):
      threshold = resolve_compaction_threshold(window)
      guardrail = _resolve_guardrail_budget(
          window,
          input_ratio=settings.context_input_ratio,
          chars_per_token=settings.context_estimate_chars_per_token,
      )
      print(f"window={window} compaction_threshold={threshold} guardrail_budget={guardrail}")
      assert threshold <= guardrail, (window, threshold, guardrail)
  print("ok: 压缩阈值不晚于护栏预算")
  
PY
```

window=1000 compaction_threshold=1 guardrail_budget=900
window=128000 compaction_threshold=96000 guardrail_budget=115200
window=1000000 compaction_threshold=750000 guardrail_budget=900000
ok: 压缩阈值不晚于护栏预算
结果：通过

### AC1：切点永不落在 tool 行（工具调用与结果不拆散）

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from types import SimpleNamespace
  from app.modules.conversation.runtime import plan_compaction_cut
  
  rows = [
      SimpleNamespace(id=1, role="user", content="u" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=2, role="assistant", content="a" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=3, role="tool", content="t" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=4, role="user", content="u" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=5, role="assistant", content="a" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=6, role="tool", content="t" * 400, content_blocks=None, message_metadata=None),
      SimpleNamespace(id=7, role="user", content="最新一轮" * 40, content_blocks=None, message_metadata=None),
  ]
  cut = plan_compaction_cut(rows, keep_recent_tokens=100)
  print(f"cut={cut} cut_row_role={rows[cut].role}")
  assert cut is not None and rows[cut].role != "tool"
  print("ok: 切点落在非 tool 行")
  
PY
```

cut=6 cut_row_role=user
ok: 切点落在非 tool 行
结果：通过

### AC1：窗口未知时不产生百分比（只给绝对 token 数）

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from app.modules.conversation.compaction import ContextCompactionController
  print("percent(used, None) ->", end=" ")
  from app.modules.conversation.compaction import _percent
  assert _percent(1234, None) is None
  assert _percent(1234, 0) is None
  print("None（窗口未知/为 0）")
  print("ok")
  
PY
```

percent(used, None) -> None（窗口未知/为 0）
ok
结果：通过

### AC6：坏摘要（finish_reason=length 或异常）不落库

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from app.modules.conversation.compaction import _summary_max_tokens
  from app.core.config import get_settings
  settings = get_settings()
  expected = settings.context_compaction_summary_max_tokens or max(256, int(settings.context_compaction_reserve_tokens * 0.8))
  print(f"summary_max_tokens={_summary_max_tokens()} expected={expected}")
  assert _summary_max_tokens() == expected
  print("ok（截断判定与「宁可不存」由 tests/conversation/test_compaction_persistence.py 覆盖）")
  
PY
```

summary_max_tokens=13107 expected=13107
ok（截断判定与「宁可不存」由 tests/conversation/test_compaction_persistence.py 覆盖）
结果：通过

### AC1/AC4：护栏不会把注入的摘要 SystemMessage 当历史删掉

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
  from app.modules.conversation.runtime import apply_runtime_context_guardrail
  
  summary = SystemMessage("以下是此前对话的压缩摘要（原始消息仍完整保留在会话记录中）：\n" + "摘要" * 2000)
  messages = [
      SystemMessage("系统提示"),
      summary,
      HumanMessage("很早的一轮问题" * 200),
      AIMessage("很早的一轮回答" * 200),
      HumanMessage("更早的一轮问题" * 200),
      AIMessage("更早的一轮回答" * 200),
      HumanMessage("当前问题"),
  ]
  out = apply_runtime_context_guardrail(messages, window_tokens=1000)
  print(f"输入 {len(messages)} 条 -> 输出 {len(out)} 条")
  print("摘要对象仍在：", any(m is summary for m in out))
  print("首条仍是原系统提示对象：", out[0] is messages[0])
  assert any(m is summary for m in out)
  assert out[0] is messages[0]
  print("ok")
  
PY
```

Runtime context guardrail cannot fit budget window_tokens=1000 budget_chars=900 kept_chars=4039; system+current still exceed
输入 7 条 -> 输出 3 条
摘要对象仍在： True
首条仍是原系统提示对象： True
ok
结果：通过

### 迁移建表可用（sqlite 内存库按模型元数据建表）

```bash
apps/backend/.venv/bin/python - <<'PY'
  
  from sqlalchemy import create_engine, inspect
  from app.shared.base_model import BaseModel
  from app.modules.conversation import models  # noqa: F401  触发模型注册
  engine = create_engine("sqlite://")
  BaseModel.metadata.create_all(engine)
  inspector = inspect(engine)
  assert "conversation_context_compactions" in inspector.get_table_names()
  cols = {c["name"] for c in inspector.get_columns("conversation_context_compactions")}
  print("表已建，列 =", sorted(cols))
  for required in ("summary", "first_kept_message_id", "tokens_before", "tokens_after", "trigger", "instructions", "model_name", "usage"):
      assert required in cols, required
  print("ok")
  
PY
```

表已建，列 = ['conversation_id', 'created_at', 'first_kept_message_id', 'id', 'instructions', 'model_name', 'summary', 'tokens_after', 'tokens_before', 'trigger', 'updated_at', 'usage']
ok
结果：通过

SDK 只跑 `vitest run src`：整包 `pnpm exec vitest run` 会连带 `scripts/verify-package.test.mjs`
的**预存在**失败（详见文末），与本次改动无关。

### AC2：SDK 单测（含 run-events.golden.json 对拍）

```bash
step_sdk_vitest
```


 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/message-presentation.test.ts (10 tests) 5ms
 ✓ src/ui/__tests__/window-layout.test.ts (12 tests) 5ms
 ✓ src/core/__tests__/protocol.test.ts (11 tests) 5ms
stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > queues messages until session_ready and does not reconnect after explicit disconnect
[xxai-agent][conversation] transport sending message { requestId: 'req-1', conversationId: undefined }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > includes the server conversation id on subsequent chat messages
[xxai-agent][conversation] transport sending message { requestId: 'req-2', conversationId: 'conversation-42' }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > uses a restored conversation id on the first message and can clear it
[xxai-agent][conversation] transport sending message { requestId: 'req-restored', conversationId: '42' }
[xxai-agent][conversation] transport sending message { requestId: 'req-new', conversationId: undefined }

 ✓ src/core/__tests__/websocket.test.ts (11 tests) 14ms
 ✓ src/ui/__tests__/markdown-content.test.ts (7 tests) 6ms
 ✓ src/ui/__tests__/markdown-diagram-renderers.test.ts (18 tests) 29ms
 ✓ src/core/__tests__/compatibility.test.ts (4 tests) 53ms
stdout | src/core/__tests__/conversations.test.ts > conversations_changed 事件 > 会在首条消息创建会话后通知列表刷新
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_started',
  requestId: 'r',
  previousConversationId: undefined,
  conversationId: '88'
}

stdout | src/core/__tests__/conversations.test.ts > conversations_changed 事件 > 会在回答完成后通知列表刷新，让消息数与摘要更新
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_started',
  requestId: 'r',
  previousConversationId: undefined,
  conversationId: '88'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_delta',
  requestId: 'r',
  previousConversationId: '88',
  conversationId: '88'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_completed',
  requestId: 'r',
  previousConversationId: '88',
  conversationId: '88'
}

stdout | src/core/__tests__/conversations.test.ts > conversations_changed 事件 > 同一会话内不会因为每条 delta 都触发刷新
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_started',
  requestId: 'r',
  previousConversationId: undefined,
  conversationId: '88'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_delta',
  requestId: 'r',
  previousConversationId: '88',
  conversationId: '88'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_delta',
  requestId: 'r',
  previousConversationId: '88',
  conversationId: '88'
}

stdout | src/core/__tests__/conversations.test.ts > conversations_changed 事件 > 请求失败后也会通知刷新，避免半截会话不出现在列表里
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_started',
  requestId: 'r',
  previousConversationId: undefined,
  conversationId: '88'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'error',
  requestId: 'r',
  previousConversationId: '88',
  conversationId: '88'
}

 ✓ src/core/__tests__/conversations.test.ts (12 tests) 7ms
stdout | src/core/__tests__/client.test.ts > AgentClient protocol events > 同步服务端事件顶层的 conversationId 到客户端消息和工具上下文
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_started',
  requestId: 'r',
  previousConversationId: undefined,
  conversationId: '42'
}

stderr | src/core/__tests__/client.test.ts > AgentClient protocol events > ends a queued request when the transport fails before message_started
Connection error: Error: WebSocket closed (4401)
    at /Users/lixingwen/xw/study/ai-base/apps/ai-sdk/src/core/__tests__/client.test.ts:279:29
    at processTicksAndRejections (node:internal/process/task_queues:105:5)
    at file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:533:5
    at runTest (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1056:11)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runFiles (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1262:5)
    at startTests (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3)
    at file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/vitest@2.1.9_jsdom@26.1.0/node_modules/vitest/dist/chunks/runBaseTests.3qpJUEJM.js:126:11
    at withEnv (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/vitest@2.1.9_jsdom@26.1.0/node_modules/vitest/dist/chunks/runBaseTests.3qpJUEJM.js:90:5)

stderr | src/core/__tests__/client.test.ts > AgentClient protocol events > 兼容性失败只上报一次（compatibility_error 与 error 成对发出时不重复）
Connection error: Error [AgentError]: 当前 SDK 版本过低，请升级到 0.2.0 或更高版本
    at /Users/lixingwen/xw/study/ai-base/apps/ai-sdk/src/core/__tests__/client.test.ts:602:26
    at file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:146:14
    at file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:533:11
    at runWithTimeout (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:39:7)
    at runTest (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1056:17)
    at processTicksAndRejections (node:internal/process/task_queues:105:5)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runFiles (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1262:5)
    at startTests (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3) {
  code: 'unsupported_sdk_version',
  retryable: false
}

 ✓ src/core/__tests__/client.test.ts (37 tests) 33ms
 ✓ src/core/__tests__/errors.test.ts (8 tests) 3ms
stdout | src/core/__tests__/client-replay.test.ts > replayed assistant events > materializes a completed message when message_started was not replayed
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_completed',
  requestId: 'r1',
  previousConversationId: undefined,
  conversationId: '42'
}

 ✓ src/core/__tests__/client-replay.test.ts (3 tests) 5ms
stdout | src/core/__tests__/client-replay.test.ts > replayed assistant events > accumulates replayed deltas before the completion event
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_delta',
  requestId: 'r1',
  previousConversationId: undefined,
  conversationId: '42'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_delta',
  requestId: 'r1',
  previousConversationId: '42',
  conversationId: '42'
}
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_completed',
  requestId: 'r1',
  previousConversationId: '42',
  conversationId: '42'
}

 ✓ src/ui/__tests__/context-ring.test.ts (8 tests) 3ms
 ✓ src/core/__tests__/attachments.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/markdown-fence-registry.test.ts (5 tests) 3ms
 ✓ src/ui/__tests__/two-step-confirm.test.ts (6 tests) 4ms
 ✓ src/ui/__tests__/quota-ring.test.ts (5 tests) 5ms
 ✓ src/core/__tests__/page-tools.test.ts (3 tests) 5ms
 ✓ src/ui/__tests__/window-storage.test.ts (3 tests) 2ms
 ✓ src/ui/__tests__/context-ring.component.test.ts (3 tests) 5ms
 ✓ src/ui/__tests__/chat-scroll.test.ts (2 tests) 2ms
 ✓ src/ui/__tests__/header-name.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/chat-message.ssr.test.ts (9 tests) 24ms
 ✓ src/ui/__tests__/markdown-diagram-dom.test.ts (7 tests) 132ms

 Test Files  23 passed (23)
      Tests  192 passed (192)
   Start at  14:25:51
   Duration  1.81s (transform 1.15s, setup 0ms, collect 2.41s, tests 353ms, environment 785ms, prepare 2.01s)

结果：通过

### SDK 类型检查（vue-tsc）

```bash
step_sdk_typecheck
```


> xxai-agent@0.2.0 type-check /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
> vue-tsc --noEmit

结果：通过

### AC3：SDK 构建

```bash
step_sdk_build
```


> xxai-agent@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
> vite build

vite v5.4.21 building for production...
transforming...
✓ 111 modules transformed.
rendering chunks...

[vite:dts] Start generate declaration files...
computing gzip size...
dist/style.css          45.07 kB │ gzip:   8.07 kB
dist/xxai-agent.es.js  456.23 kB │ gzip: 139.60 kB
[vite:dts] Declaration files built in 2040ms.

dist/style.css            45.07 kB │ gzip:   8.07 kB
dist/xxai-agent.umd.cjs  308.40 kB │ gzip: 114.10 kB
✓ built in 2.93s
结果：通过

### AC3：产物契约（导出齐全 / 引擎外置且惰性 / 入口 <1MB）

```bash
step_sdk_dist_contract
```

CJS 入口导出（包根可用的新符号）：
createAgentClient: function
AgentClient: function
ChatWidget: object
PROTOCOL_VERSION: number
SDK_VERSION: string
contextRingState: function
formatTokens: function

图表引擎仍是外置的惰性动态 import（打包器把说明符折叠成跨模块成员访问，
因此断言形如 import(x.mermaid) / import(x.echarts)，而不是字面量 import("mermaid")）：
   1 import(jc.echarts)
   1 import(jc.mermaid)
命中种类 = 2（期望 2）

入口体积（要求 <1MB，同时说明引擎没有被内联进来）：
-rw-r--r--@ 1 lixingwen  staff  460133 10 20 14:25 apps/ai-sdk/dist/xxai-agent.es.js
-rw-r--r--@ 1 lixingwen  staff  310443 10 20 14:25 apps/ai-sdk/dist/xxai-agent.umd.cjs

类型声明包含新增公共类型：
结果：通过

### AC7：Harness 自检 audit.py（本 request 的 ERROR 归零）

```bash
step_audit
```


v2 requests: 17  存量跳过: 59  ERROR: 0  WARN: 0
结果：通过

## 未执行项与原因

- **真进程端到端（AC4）**：本机没有运行中的 API/PostgreSQL/Redis（`docker compose` 未起），
  无法执行「真进程 WS 发消息 → 观察 header 占用增长 → 调小窗口触发自动压缩 → 查库出现新行」。
  等价覆盖：`tests/conversation/test_compaction_persistence.py`——其中
  `test_auto_trigger_compacts_through_controller_and_emits_event` 按 loop 的真实顺序跑
  `transform()` → 自动压缩 → 落库 → `drain_events()` 事件（含「不重复压缩」），
  `test_load_model_history_resumes_from_latest_compaction` 覆盖下一轮请求从摘要 + 保留边界续读；
  另有 `tests/embed/test_context_compaction_route.py`（REST 投影、404、幂等）、
  `tests/agent_runtime/test_context_metrics.py`（事件经 loop 进入事件流）、
  `tests/conversation/test_rest_parity.py`（REST 历史真的到达模型）、
  SDK `context-ring.component.test.ts`（header 环渲染）与 `client.test.ts`（事件接住与 getter）。
- **真实模型 token 增长观测**：没有可用的外部模型端点到本机对话链路上，未跑真实模型；
  占用口径由 provider 真值（`prompt_tokens`）决定，其正确性由 `test_context_metrics.py` 的
  fake usage 与 `tests/conversation/test_context_compaction.py` 的基线+增量断言覆盖。
- **`alembic upgrade head`**：需要真实 PostgreSQL，未执行。改用 `alembic heads`（离线可用，
  确认链头是 20261019_0042 且唯一）+ 迁移脚本文本断言 + `BaseModel.metadata.create_all` 在 sqlite 上建表。
- **浏览器人工点检**：无运行中的前端与 API，未做浏览器点检；SDK 侧由 vitest（含 SSR 组件测试）与类型检查覆盖。
- **`node scripts/verify-package.mjs`（AC3 的一半）**：**预存在失败**，在 HEAD 上同样失败，
  与本次改动无关：脚本断言产物含字面量 `import("mermaid")`，而源码 
`apps/ai-sdk/src/ui/markdown/optional-engines.ts` 故意通过跨模块可变映射取值，产物是 `import(jc.mermaid)`。
  取证：`git worktree add /tmp/ai-base-head HEAD` 后在该 worktree 里 `pnpm build` + 
`node scripts/verify-package.mjs` → 同样 `Error: Chart engine must stay external and be imported lazily: mermaid`（EXIT 1）。
  本脚本改用等价断言：引擎仍是外置惰性动态 import、两个入口 <1MB、CJS 导出齐全。
- **`pnpm exec vitest run`（整包）**：会连带 `scripts/verify-package.test.mjs > 发布包包含公共类型依赖和 CSS 入口`
  的**预存在环境性失败**（`npm pack --dry-run --json` 触发 `prepare` 的 vite build，日志与 JSON 同走 stdout，
  导致 `SyntaxError: Unexpected token 'v', "vite v5.4."... is not valid JSON`；该用例与 `package.json` 本次均未改动）。
  故本脚本只跑 `vitest run src`。

## 验收结论

| 验收标准 | 结果 |
| --- | --- |
| 1. 后端四目录单测全绿，且覆盖切点不拆工具调用与结果 / 坏摘要不落库 / 窗口未知只给绝对值 / 二次压缩并入旧摘要 | pytest conversation + agent_runtime + gateway + embed 通过；见上文断言 |
| 2. SDK 单测全绿，共享 golden 两端形状一致 | vitest run src 通过；tests/gateway/test_event_parity.py 通过（golden 22 事件含两条新事件） |
| 3. 产物无密钥、入口齐全 | pnpm build 通过；CJS 导出齐全、引擎外置惰性、入口 <1MB。`verify-package.mjs` 为预存在失败（HEAD 同样失败），已用等价断言替代 |
| 4. 端到端：占用随真实 token 增长；窗口调小后自动压缩落库；模型可见上下文 = 摘要 + 保留边界之后 | **未执行真进程端到端**（无 API/DB）；sqlite 落库测试 + 控制器顺序单测 + 护栏保留摘要断言等价覆盖 |
| 5. 手动压缩 REST 幂等，并发两次只产生一行 | tests/embed/test_context_compaction_route.py + tests/conversation/test_compaction_persistence.py 通过（会话行锁串行化） |
| 6. 摘要失败不写新行、请求仍完成、客户端收到 context_compacted{ok:false} | test_compaction_persistence.py（finish_reason=length / 抛异常 → summary_failed 且 0 行）+ test_context_metrics.py（ok=false 事件仍发出）通过 |
| 7. audit.py 无 ERROR | 见上文 audit 步骤 |
