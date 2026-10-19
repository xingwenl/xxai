---
source: script
request: 2026-10-19-sdk-protocol-alignment
ranAt: "2026-10-19 12:56:36 CST"
exitCode: 0
---

## 已执行的命令与结果

### 后端单测：gateway

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
118 passed, 1 skipped, 1 warning in 2.60s
结果：通过

### 后端单测：shared

```bash
step_unit_shared
```

...........                                                              [100%]
=============================== warnings summary ===============================
tests/shared/test_responses.py::test_exception_handler_serializes_error_code
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
11 passed, 1 warning in 1.93s
结果：通过

### 后端单测：model_registry

```bash
step_unit_model_registry
```

..........                                                               [100%]
10 passed in 2.58s
结果：通过

### 后端单测：agent_runtime

```bash
step_unit_agent_runtime
```

........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 1.77s
结果：通过

### 后端单测：conversation

```bash
step_unit_conversation
```

........................................................................ [ 62%]
............................................                             [100%]
116 passed in 5.05s
结果：通过

### 后端单测：asset

```bash
step_unit_asset
```

....................................                                     [100%]
36 passed in 2.06s
结果：通过

### 结构断言：错误码登记表是唯一来源（AC10）

```bash
step_error_code_registry
```

这四个文件里除豁免项之外的裸字符串码命中：
（无）
结果：通过

### 结构断言：四个文件已改用 ErrorCode（AC10）

```bash
step_error_code_registry_defined
```

gateway/router.py 引用 ErrorCode 的次数 = 17
apps/backend/app/modules/gateway/router.py:17:from app.modules.agent_runtime.error_codes import ErrorCode
apps/backend/app/modules/gateway/dispatcher.py:11:from app.modules.agent_runtime.error_codes import ErrorCode
apps/backend/app/modules/conversation/runtime.py:31:from app.modules.agent_runtime.error_codes import ErrorCode
apps/backend/app/modules/agent_runtime/errors.py:6:from app.modules.agent_runtime.error_codes import ErrorCode
结果：通过

### 结构断言：gateway/schemas.py 只留入站契约（AC11）

```bash
step_outbound_models_removed
```

schemas.py 里残留的出站协议模型：
（无）
--- 保留的入站契约 ---
25:class AttachmentRef(BaseModel):
56:class MessageSendPayload(BaseModel):
结果：通过

### 结构断言：capabilities 已双向删除（AC13）

```bash
step_no_capabilities
```

协议能力字段命中（双引号键或 auth 帧数组）：
（无）
CAPABILITIES 常量命中：
（无）
--- 对照：同目录下正当的 attachment capabilities 用法（不应被判失败）---
36:    ProviderAttachmentCapabilities,
98:    capabilities: ProviderAttachmentCapabilities | None = None,
244:    capabilities: ProviderAttachmentCapabilities | None = None,
结果：通过

### 文档：兼容矩阵已与实现对齐（变更点 14）

```bash
step_compat_matrix
```

--- SDK 版本行（期望 0.2.0，且注明运行期取自 package.json）---
11:| SDK 版本 | `0.2.0` | `apps/ai-sdk/package.json` 的 `version`（SDK 运行期读取，非硬编码） |
--- 4406 与 error_code 说明 ---
17:- 两种不兼容都先下发一条 `error` 事件（payload 带 `code`/`message`/`retryable` 与 `details{serverVersion, minimumSdkVersion, supportedProtocolVersion}`），随后以 close code `4406` 关闭连接。SDK 侧统一以 `AgentError` 暴露：`agent.on('compatibility_error')`、`onError` 与 `connect()` 的 reject 拿到的是同一个对象。
20:- REST 响应体在 HTTP 状态码之外提供稳定业务码 `error_code`（`code` 仍是 HTTP 状态码）；SDK 的 `AgentError.code` 取自 `error_code`。
--- 已删除的 capabilities 说明 ---
18:- 同一主版本允许新增可选 envelope 字段；客户端必须忽略未知可选字段。**协议能力声明（`capabilities`）已双向删除**：后端不再在 `session_ready` 返回，SDK 不再在 `auth` 上报。原因是两端取值命名空间不一致（后端曾是传输能力 `replay`/`host_tools`/`cancellation`，SDK 曾是交互能力 `questions`）且无消费者。若将来确需能力协商，应在新 request 中定义一份双方共享的能力清单，而不是恢复这两个字段。
过期的 SDK 版本行：
（无）
结果：通过

### SDK 单测（vitest）

```bash
step_sdk_unit
```


 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/message-presentation.test.ts (10 tests) 4ms
 ✓ src/ui/__tests__/window-layout.test.ts (12 tests) 4ms
 ✓ src/core/__tests__/protocol.test.ts (11 tests) 4ms
stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > queues messages until session_ready and does not reconnect after explicit disconnect
[xxai-agent][conversation] transport sending message { requestId: 'req-1', conversationId: undefined }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > includes the server conversation id on subsequent chat messages
[xxai-agent][conversation] transport sending message { requestId: 'req-2', conversationId: 'conversation-42' }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > uses a restored conversation id on the first message and can clear it
[xxai-agent][conversation] transport sending message { requestId: 'req-restored', conversationId: '42' }
[xxai-agent][conversation] transport sending message { requestId: 'req-new', conversationId: undefined }

 ✓ src/core/__tests__/websocket.test.ts (11 tests) 14ms
 ✓ src/core/__tests__/compatibility.test.ts (4 tests) 50ms
 ✓ src/ui/__tests__/markdown-diagram-renderers.test.ts (18 tests) 43ms
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

 ✓ src/core/__tests__/conversations.test.ts (12 tests) 31ms
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

 ✓ src/core/__tests__/client.test.ts (28 tests) 56ms
 ✓ src/ui/__tests__/markdown-content.test.ts (7 tests) 9ms
 ✓ src/core/__tests__/errors.test.ts (8 tests) 3ms
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

 ✓ src/core/__tests__/client-replay.test.ts (3 tests) 5ms
 ✓ src/core/__tests__/attachments.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/quota-ring.test.ts (5 tests) 3ms
 ✓ src/core/__tests__/page-tools.test.ts (3 tests) 3ms
 ✓ src/ui/__tests__/markdown-fence-registry.test.ts (5 tests) 26ms
 ✓ src/ui/__tests__/window-storage.test.ts (3 tests) 2ms
 ✓ src/ui/__tests__/header-name.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/two-step-confirm.test.ts (6 tests) 9ms
 ✓ src/ui/__tests__/chat-scroll.test.ts (2 tests) 1ms
 ✓ src/ui/__tests__/chat-message.ssr.test.ts (9 tests) 24ms
 ✓ src/ui/__tests__/markdown-diagram-dom.test.ts (7 tests) 131ms

 Test Files  21 passed (21)
      Tests  172 passed (172)
   Start at  12:56:08
   Duration  2.00s (transform 1.24s, setup 0ms, collect 2.72s, tests 427ms, environment 848ms, prepare 1.92s)

结果：通过

### SDK 类型检查（vue-tsc）

```bash
step_sdk_typecheck
```


> xxai-agent@0.2.0 type-check
> vue-tsc --noEmit

结果：通过

### SDK 构建并产出 dist

```bash
step_sdk_build
```


> xxai-agent@0.2.0 build
> vite build

vite v5.4.21 building for production...
transforming...
✓ 108 modules transformed.
rendering chunks...

[vite:dts] Start generate declaration files...
computing gzip size...
dist/style.css          44.38 kB │ gzip:   7.97 kB
dist/xxai-agent.es.js  447.48 kB │ gzip: 136.80 kB
[vite:dts] Declaration files built in 2002ms.

dist/style.css            44.38 kB │ gzip:   7.97 kB
dist/xxai-agent.umd.cjs  302.64 kB │ gzip: 112.20 kB
✓ built in 2.85s
结果：通过

### SDK 产物不再含 serverCapabilities

```bash
step_sdk_dist_no_server_capabilities
```

dist 里的 serverCapabilities 命中：
（无）
结果：通过

### SDK 包根导出 PROTOCOL_VERSION / SDK_VERSION（AC9）

```bash
step_sdk_root_exports
```

--- 包根导出（变更点 10 / AC9）---
85:export { PROTOCOL_VERSION, SDK_VERSION } from './core/protocol'
--- 构建产物里的同一条导出（dist/index.d.ts 是 shim，真身在 dist/src/index.d.ts）---
apps/ai-sdk/dist/src/core/protocol.d.ts:1:export declare const PROTOCOL_VERSION: 1;
apps/ai-sdk/dist/src/core/protocol.d.ts:2:export declare const SDK_VERSION: string;
apps/ai-sdk/dist/src/core/protocol.d.ts:53:    protocolVersion: typeof PROTOCOL_VERSION;
apps/ai-sdk/dist/src/index.d.ts:13:export { PROTOCOL_VERSION, SDK_VERSION } from './core/protocol';
--- 值来源（运行期读 package.json，避免与产物版本漂移）---
6:export const SDK_VERSION: string = packageJson.version
src/index.ts 导出条数=1（期望 1）；dist 里同名导出文件数=1（期望 >=1）
结果：通过

### 端到端：真进程 WS 握手与 REST error_code（AC1/AC2/AC2b/AC3/AC4/AC13）

```bash
step_e2e_probe_guarded apps/backend/.venv/bin/python tools/harness/verify/2026-10-19-sdk-protocol-alignment.probe.py
```


--- 准备：登录、准备嵌入客户端、记录原 chat 绑定 ---
  已登录 admin@平台1
  嵌入客户端 client_id=client_xEq-9OI23D9ISL1xoCOaq0n4 已绑定 agent 1
  原 chat 绑定 model_id=1

--- AC1/AC2/AC2b：auth 帧版本字段不合法或缺失都必须在 token 校验前被拒 ---
  protocolVersion=2 事件类型=['error'] close=4406 err=None
  通过：AC1 收到 error 事件 —— [{'id': 'evt_1', 'type': 'error', 'protocolVersion': 1, 'sequence': 1, 'timestamp': '2026-10-19T04:56:20.294206+00:00', 'payload': {'code': 'unsupported_protocol_version', 'message': '不支持的协议主版本，请升级客户端：服务端支持协议版本 1', 'retryable': False, 'details': {'serverVersion': '0.1.0', 'minimumSdkVersion': '0.1.0', 'supportedProtocolVersion': '1'}}}]
  通过：AC1 code=unsupported_protocol_version —— unsupported_protocol_version
  通过：AC1 retryable=false —— False
  通过：AC1 details.serverVersion 非空 —— {'serverVersion': '0.1.0', 'minimumSdkVersion': '0.1.0', 'supportedProtocolVersion': '1'}
  通过：AC1 details.minimumSdkVersion 非空 —— {'serverVersion': '0.1.0', 'minimumSdkVersion': '0.1.0', 'supportedProtocolVersion': '1'}
  通过：AC1 服务端以 4406 关闭 —— 4406
  sdkVersion=0.0.1 事件类型=['error'] close=4406
  通过：AC2 code=unsupported_sdk_version —— [{'id': 'evt_1', 'type': 'error', 'protocolVersion': 1, 'sequence': 1, 'timestamp': '2026-10-19T04:56:20.302864+00:00', 'payload': {'code': 'unsupported_sdk_version', 'message': '当前 SDK 版本过低，请升级到 0.1.0 或更高版本', 'retryable': False, 'details': {'serverVersion': '0.1.0', 'minimumSdkVersion': '0.1.0', 'supportedProtocolVersion': '1'}}}]
  通过：AC2 服务端以 4406 关闭 —— 4406
  缺版本字段 事件类型=['error'] close=4406
  通过：AC2b 缺版本字段仍被拒（unsupported_protocol_version） —— [{'id': 'evt_1', 'type': 'error', 'protocolVersion': 1, 'sequence': 1, 'timestamp': '2026-10-19T04:56:20.306901+00:00', 'payload': {'code': 'unsupported_protocol_version', 'message': '不支持的协议主版本，请升级客户端：服务端支持协议版本 1', 'retryable': False, 'details': {'serverVersion': '0.1.0', 'minimumSdkVersion': '0.1.0', 'supportedProtocolVersion': '1'}}}]
  通过：AC2b 服务端以 4406 关闭 —— 4406

--- AC3：不请求子协议 ai-agent.v1 → 先关闭、发不出 error 事件 ---
  connected=False close=None err=InvalidStatus: server rejected WebSocket connection: HTTP 403
  通过：AC3 未能进入协议层（未连接） —— InvalidStatus: server rejected WebSocket connection: HTTP 403
  通过：AC3 未收到 error 事件 —— []
  通过：AC3 关闭码为 4406（或握手期 HTTP 拒绝） —— close=None err=InvalidStatus: server rejected WebSocket connection: HTTP 403

--- AC13：正常握手 → session_ready 不再含 capabilities，且带两版本字段 ---
  通过：AC13 收到 session_ready —— ['session_ready']
  session_ready.payload 键=['agent', 'client', 'latestSequence', 'minimumSdkVersion', 'quota', 'recovered', 'serverVersion', 'subject']
  通过：AC13 payload 不含 capabilities —— ['agent', 'client', 'latestSequence', 'minimumSdkVersion', 'quota', 'recovered', 'serverVersion', 'subject']
  通过：AC13 payload 含 serverVersion —— 0.1.0
  通过：AC13 payload 含 minimumSdkVersion —— 0.1.0
  通过：AC13 信封 protocolVersion == 1 —— 1

--- AC4：非流式 REST 的 ChatModelUnavailable → 409 + error_code ---
  已把 agent 1 的 chat 绑定指向停用模型 model_id=50
  HTTP 409 body={"success": false, "message": "该 Agent 绑定的对话模型已被停用，请联系管理员启用或重新绑定模型", "data": null, "meta": null, "code": 409, "error_code": "chat_model_unavailable"}
  通过：AC4 HTTP 409 —— 409
  通过：AC4 body.code == 409（int，语义未变） —— 409
  通过：AC4 body.error_code == chat_model_unavailable —— chat_model_unavailable
  通过：AC4 body.success is False —— False

--- 收尾：恢复 chat 绑定、清掉探针模型与嵌入客户端绑定 ---
  已恢复 chat 绑定 model_id=1
  已删除探针模型 model_id=50（status=200）
  已解绑并停用探针嵌入客户端

--- 结论 ---
  全部通过
结果：通过

### Harness 自检：audit.py（AC12）

```bash
step_audit
```


v2 requests: 14  存量跳过: 59  ERROR: 0  WARN: 0
除预期的「缺少 verify.md」之外的 ERROR：
（无）
结果：通过

## 未执行项与原因

- 浏览器人工点击：本轮无前端改动，SDK 确认卡与错误展示由 vitest + 类型检查覆盖，未做浏览器点检。
- `pnpm --dir apps/ai-sdk test`（整包 vitest）会连带 `scripts/verify-package.test.mjs` 的**预存在环境性失败**：
  该用例用 `npm pack --dry-run --json` 取包清单后直接 `JSON.parse`，而 `prepare` 脚本的 vite build 日志
  与 JSON 同走 stdout，导致 `SyntaxError: Unexpected token 'v', "vite v5.4."...`。与本次改动的 golden/协议无关，
  故本轮只跑 `npx vitest run src`（21 文件 / 172 用例）。
- 真实模型端点出词：本轮不涉及模型调用路径，AC4 刻意用「已停用的 chat 绑定」触发 `ChatModelUnavailable`，无需外部余额。
- `alembic check`：本仓存在大量**预存在**漂移（几十张表 comment 不一致、`sys_users.email` nullable 等），
  不能作为本改动的验证结论；本轮无迁移，未执行。

## 验收结论

| 验收标准 | 结果 |
| --- | --- |
| 1. protocolVersion=2 → error 事件（code/retryable=false/details 三字段）+ close 4406 | 端到端探针通过 |
| 2. sdkVersion=0.0.1 → unsupported_sdk_version；缺字段同样被拒 | 端到端探针 + tests/gateway 通过 |
| 3. 缺子协议 → 关闭且不发 error 事件 | 端到端探针通过（客户端侧表现为握手 HTTP 403） |
| 4. 非流式 REST ChatModelUnavailable → 409 + error_code=chat_model_unavailable | 端到端探针通过 |
| 5. 既有 code int 断言不变 | tests/workflows / tests/shared 等 pytest 通过 |
| 6. SDK onError 与 agent.on('error') 收到同一 AgentError | vitest（client.test.ts / errors.test.ts）通过 |
| 7. close 4406 只上报一次且不退避重连 | vitest（compatibility.test.ts）通过 |
| 8. REST 4xx 抛 AgentError，无字符串码时回落 http_<status> | vitest 通过 |
| 9. 包根可导入 PROTOCOL_VERSION / SDK_VERSION | 结构断言 + 构建产物通过 |
| 10. 错误码登记表为唯一来源 | 结构断言通过 |
| 11. schemas.py 不再含运行时协议模型；golden 对拍全绿 | 结构断言 + tests/gateway 通过 |
| 12. audit.py ERROR: 0 | Harness 自检通过（本 request 缺 verify.md 属预期，由 verify.sh 产出） |
| 13. capabilities 双向删除 | 结构断言 + 端到端探针通过 |
