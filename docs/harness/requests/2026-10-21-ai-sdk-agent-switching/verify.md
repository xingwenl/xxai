---
source: script
request: 2026-10-21-ai-sdk-agent-switching
ranAt: "2026-10-21 12:36:57 CST"
exitCode: 0
---

## 已执行的命令与结果

### 后端开关字段与下发通道静态断言

```bash
backend_toggle_static
```

结果：通过

### 迁移文件成对且 revision 链正确

```bash
migration_static
```

结果：通过

### 后端单测（embed + gateway session_info）

```bash
backend_tests
```

....................................                                     [100%]
36 passed in 3.65s
结果：通过

### alembic 单一 head 指向本次迁移

```bash
alembic_heads
```

20261021_0044 (head)
结果：通过

### 迁移真实 upgrade→downgrade→upgrade

```bash
migration_roundtrip
```

INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 20261021_0044 -> 20261020_0043, Embed Client 增加「允许终端用户切换智能体」开关
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 20261020_0043 -> 20261021_0044, Embed Client 增加「允许终端用户切换智能体」开关
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
20261021_0044 (head)
结果：通过

### SDK 切换实现/UI/导出/README 静态断言

```bash
sdk_static
```

结果：通过

### SDK 单测（src 全量）

```bash
sdk_tests
```


 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/message-presentation.test.ts (10 tests) 3ms
 ✓ src/core/__tests__/agent-switching.test.ts (12 tests) 4ms
 ✓ src/ui/__tests__/window-layout.test.ts (12 tests) 3ms
 ✓ src/core/__tests__/protocol.test.ts (11 tests) 4ms
stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > queues messages until session_ready and does not reconnect after explicit disconnect
[xxai-agent][conversation] transport sending message { requestId: 'req-1', conversationId: undefined }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > includes the server conversation id on subsequent chat messages
[xxai-agent][conversation] transport sending message { requestId: 'req-2', conversationId: 'conversation-42' }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > uses a restored conversation id on the first message and can clear it
[xxai-agent][conversation] transport sending message { requestId: 'req-restored', conversationId: '42' }
[xxai-agent][conversation] transport sending message { requestId: 'req-new', conversationId: undefined }

 ✓ src/core/__tests__/websocket.test.ts (11 tests) 18ms
 ✓ src/ui/__tests__/markdown-diagram-renderers.test.ts (25 tests) 28ms
stderr | src/core/__tests__/agent-switch-client.test.ts > AgentClient agent switching > keeps the current agent and connection state when the target token is rejected
[xxai-agent][agent-switching] switch failed { agentId: '2', previousAgentId: '1', reason: 'not_bound' }

stderr | src/core/__tests__/agent-switch-client.test.ts > AgentClient agent switching > refuses to switch when the backend policy is off, even with candidates configured
[xxai-agent][agent-switching] switch failed { agentId: '2', previousAgentId: '1', reason: 'not_allowed' }

stderr | src/core/__tests__/agent-switch-client.test.ts > AgentClient agent switching > refuses to switch while a request is in flight
[xxai-agent][agent-switching] switch failed { agentId: '2', previousAgentId: '1', reason: 'busy' }

stderr | src/core/__tests__/agent-switch-client.test.ts > AgentClient agent switching > refuses to switch when the endpoint cannot carry a per-agent path
[xxai-agent][agent-switching] switch failed { agentId: '2', previousAgentId: '1', reason: 'not_supported' }

stderr | src/core/__tests__/agent-switch-client.test.ts > AgentClient agent switching > rejects targets that are not in the host-provided candidate list
[xxai-agent][agent-switching] switch failed { agentId: '99', previousAgentId: '1', reason: 'not_allowed' }

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

 ✓ src/core/__tests__/conversations.test.ts (12 tests) 11ms
 ✓ src/core/__tests__/agent-switch-client.test.ts (9 tests) 21ms
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
    at file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:533:5
    at runTest (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1056:11)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runFiles (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1262:5)
    at startTests (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3)
    at file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/vitest@2.1.9_@types+node@25.9.9_jsdom@26.1.0_lightningcss@1.33.0/node_modules/vitest/dist/chunks/runBaseTests.3qpJUEJM.js:126:11
    at withEnv (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/vitest@2.1.9_@types+node@25.9.9_jsdom@26.1.0_lightningcss@1.33.0/node_modules/vitest/dist/chunks/runBaseTests.3qpJUEJM.js:90:5)

stderr | src/core/__tests__/client.test.ts > AgentClient protocol events > 兼容性失败只上报一次（compatibility_error 与 error 成对发出时不重复）
Connection error: Error [AgentError]: 当前 SDK 版本过低，请升级到 0.2.0 或更高版本
    at /Users/lixingwen/xw/study/ai-base/apps/ai-sdk/src/core/__tests__/client.test.ts:602:26
    at file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:146:14
    at file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:533:11
    at runWithTimeout (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:39:7)
    at runTest (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1056:17)
    at processTicksAndRejections (node:internal/process/task_queues:105:5)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runSuite (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1205:15)
    at runFiles (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1262:5)
    at startTests (file:///Users/lixingwen/xw/study/ai-base/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3) {
  code: 'unsupported_sdk_version',
  retryable: false
}

 ✓ src/core/__tests__/client.test.ts (43 tests) 76ms
 ✓ src/core/__tests__/upload-mime.test.ts (10 tests) 4ms
 ✓ src/ui/__tests__/context-ring.test.ts (10 tests) 3ms
stdout | src/core/__tests__/client-replay.test.ts > replayed assistant events > materializes a completed message when message_started was not replayed
[xxai-agent][conversation] client synchronized conversation id {
  eventType: 'message_completed',
  requestId: 'r1',
  previousConversationId: undefined,
  conversationId: '42'
}

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

 ✓ src/core/__tests__/client-replay.test.ts (3 tests) 4ms
 ✓ src/core/__tests__/errors.test.ts (8 tests) 3ms
 ✓ src/ui/__tests__/markdown-content.test.ts (7 tests) 7ms
 ✓ src/core/__tests__/compatibility.test.ts (4 tests) 53ms
 ✓ src/ui/__tests__/markdown-fence-registry.test.ts (5 tests) 6ms
 ✓ src/core/__tests__/attachments.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/two-step-confirm.test.ts (6 tests) 42ms
 ✓ src/ui/__tests__/quota-ring.test.ts (5 tests) 2ms
 ✓ src/core/__tests__/page-tools.test.ts (3 tests) 3ms
 ✓ src/ui/__tests__/header-name.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/window-storage.test.ts (3 tests) 2ms
 ✓ src/ui/__tests__/chat-scroll.test.ts (2 tests) 1ms
 ✓ src/ui/__tests__/context-ring.component.test.ts (4 tests) 6ms
 ✓ src/ui/__tests__/chat-message.ssr.test.ts (9 tests) 19ms
 ✓ src/ui/__tests__/markdown-diagram-dom.test.ts (7 tests) 130ms

 Test Files  26 passed (26)
      Tests  239 passed (239)
   Start at  12:36:52
   Duration  1.58s (transform 1.11s, setup 0ms, collect 2.39s, tests 456ms, environment 503ms, prepare 2.02s)

结果：通过

### SDK 类型检查

```bash
sdk_typecheck
```

结果：通过

### 宿主侧候选列表与后台开关静态断言

```bash
front_static
```

结果：通过

### 宿主侧改动文件格式检查

```bash
front_format
```

Checking formatting...
All matched files use Prettier code style!
结果：通过

### 文档（ADR/spec/CONTEXT）静态断言

```bash
docs_static
```

结果：通过

## 未执行项与原因

- 无（本机数据库可达，迁移升降级已真实执行）。
- 未做浏览器端真机联调：切换入口需要「后台开启开关 + 宿主传入 ≥2 个候选」的真实租户配置，本脚本只覆盖静态断言与单测；交互态由 ChatWidget 事件单测与 SDK 切换单测覆盖。

## 验收结论

通过：后端开关与下发通道、迁移、SDK 切换实现与 UI、宿主接入、文档均在真实输出中验证通过。
