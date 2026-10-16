---
source: script
request: 2026-10-16-run-event-model-unification
ranAt: "2026-10-16 19:07:43 CST"
exitCode: 3
---

## 已执行的命令与结果

### gateway/events.py 已删除（内容整体迁入 agent_runtime/events.py）

```bash
assert_gateway_events_removed
```

结果：通过

### 信封形状只在 agent_runtime/events.py 组装，旧映射助手无源码命中

```bash
assert_wire_shape_single_source
```

信封键定义点：
apps/backend/app/modules/agent_runtime/events.py:82:        "protocolVersion": PROTOCOL_VERSION,
结果：通过

### SSE 路由里不再有 item["type"] 字面量分支

```bash
assert_router_has_no_type_branches
```

结果：通过

### 共享 golden 可解析且条数固定

```bash
python3 -c import json,pathlib; d=json.loads(pathlib.Path('apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json').read_text()); print(len(d), 'envelopes'); assert len(d) == 20
```

20 envelopes
结果：通过

### 两个编码器逐条等于共享 golden（SSE 与 WS 一致性）

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/gateway/test_event_parity.py -q
```

...                                                                      [100%]
3 passed in 1.83s
结果：通过

### 后端回归 tests/conversation tests/gateway tests/agent_runtime

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/conversation tests/gateway tests/agent_runtime -q
```

........................................................................ [ 20%]
........................................................................ [ 41%]
........................................................................ [ 62%]
s....................................................................... [ 83%]
..........................................................               [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
345 passed, 1 skipped, 1 warning in 5.69s
结果：通过

### AI SDK 单元测试（npx vitest run src）

```bash
bash -c cd apps/ai-sdk && npx vitest run src
```


 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/window-layout.test.ts (12 tests) 3ms
 ✓ src/ui/__tests__/message-presentation.test.ts (10 tests) 3ms
 ✓ src/core/__tests__/protocol.test.ts (11 tests) 5ms
stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > queues messages until session_ready and does not reconnect after explicit disconnect
[xxai-agent][conversation] transport sending message { requestId: 'req-1', conversationId: undefined }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > includes the server conversation id on subsequent chat messages
[xxai-agent][conversation] transport sending message { requestId: 'req-2', conversationId: 'conversation-42' }

stdout | src/core/__tests__/websocket.test.ts > WebSocketTransport > uses a restored conversation id on the first message and can clear it
[xxai-agent][conversation] transport sending message { requestId: 'req-restored', conversationId: '42' }
[xxai-agent][conversation] transport sending message { requestId: 'req-new', conversationId: undefined }

 ✓ src/core/__tests__/websocket.test.ts (11 tests) 11ms
 ✓ src/ui/__tests__/markdown-content.test.ts (7 tests) 6ms
 ✓ src/ui/__tests__/markdown-diagram-renderers.test.ts (18 tests) 22ms
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

 ✓ src/core/__tests__/conversations.test.ts (12 tests) 8ms
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

 ✓ src/core/__tests__/client.test.ts (26 tests) 21ms
 ✓ src/core/__tests__/attachments.test.ts (4 tests) 2ms
 ✓ src/ui/__tests__/quota-ring.test.ts (5 tests) 2ms
 ✓ src/core/__tests__/page-tools.test.ts (3 tests) 4ms
 ✓ src/ui/__tests__/markdown-fence-registry.test.ts (5 tests) 4ms
 ✓ src/core/__tests__/compatibility.test.ts (2 tests) 3ms
 ✓ src/ui/__tests__/header-name.test.ts (4 tests) 1ms
 ✓ src/ui/__tests__/two-step-confirm.test.ts (6 tests) 6ms
 ✓ src/ui/__tests__/window-storage.test.ts (3 tests) 2ms
 ✓ src/ui/__tests__/chat-scroll.test.ts (2 tests) 5ms
 ✓ src/ui/__tests__/chat-message.ssr.test.ts (9 tests) 20ms
 ✓ src/ui/__tests__/markdown-diagram-dom.test.ts (7 tests) 125ms

 Test Files  20 passed (20)
      Tests  160 passed (160)
   Start at  19:07:29
   Duration  1.72s (transform 1.22s, setup 0ms, collect 2.12s, tests 257ms, environment 690ms, prepare 1.78s)

结果：通过

### 前端构建与类型检查 pnpm --dir apps/front build

```bash
pnpm --dir apps/front build
```


> shadcn-admin@2.2.1 build /Users/lixingwen/xw/study/ai-base/apps/front
> tsc -b && vite build

19:07:39 [vite] warning: `esbuild` option was specified by "vite:react-swc" plugin. This option is deprecated, please use `oxc` instead.
vite v8.0.3 building client environment for production...
[2Ktransforming...✓ 4769 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                        4.29 kB │ gzip:   1.11 kB
dist/assets/dashboard-light-P68E3aSp.png             450.98 kB
dist/assets/dashboard-dark-XXx_X8s4.png              461.76 kB
dist/assets/_workflowId-DLioOiRN.css                  15.41 kB │ gzip:   2.56 kB
dist/assets/chats-CaOP_eO-.css                        27.42 kB │ gzip:   5.18 kB
dist/assets/authenticated-layout-CDYeKAlx.css         43.25 kB │ gzip:   7.79 kB
dist/assets/index-C7reYhsj.css                       119.22 kB │ gzip:  19.46 kB
dist/assets/dist-BU2KVkaz.js                           0.06 kB │ gzip:   0.08 kB
dist/assets/404-Y2rE3Vpu.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/500-BxUXSqKl.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/403-BRqf98c3.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/503-BopP2-6o.js                            0.08 kB │ gzip:   0.09 kB
dist/assets/401-B-39_H_3.js                            0.08 kB │ gzip:   0.09 kB
dist/assets/route-C_bRoZzB.js                          0.08 kB │ gzip:   0.09 kB
dist/assets/route-Lvw0WWoo.js                          0.08 kB │ gzip:   0.09 kB
dist/assets/check-B_unxq20.js                          0.12 kB │ gzip:   0.14 kB
dist/assets/chevron-down-Bc3q33zG.js                   0.12 kB │ gzip:   0.14 kB
dist/assets/matchContext-qVyDZbt3.js                   0.14 kB │ gzip:   0.12 kB
dist/assets/loader-circle-CMyn1grl.js                  0.14 kB │ gzip:   0.15 kB
dist/assets/plus-fTpbcDk4.js                           0.15 kB │ gzip:   0.15 kB
dist/assets/arrow-left-k8R5G8rH.js                     0.16 kB │ gzip:   0.16 kB
dist/assets/arrow-right-Ccm5WDmK.js                    0.16 kB │ gzip:   0.16 kB
dist/assets/search-DrCKhDEc.js                         0.17 kB │ gzip:   0.17 kB
dist/assets/auth-DgSui9mY.js                           0.19 kB │ gzip:   0.14 kB
dist/assets/smartphone-CBjGnhcd.js                     0.19 kB │ gzip:   0.18 kB
dist/assets/rotate-cw--9XEly3e.js                      0.20 kB │ gzip:   0.18 kB
dist/assets/time-B4xQYaxw.js                           0.20 kB │ gzip:   0.16 kB
dist/assets/credit-card-C3h36KXr.js                    0.20 kB │ gzip:   0.18 kB
dist/assets/sign-up-DUYuxDKK.js                        0.22 kB │ gzip:   0.19 kB
dist/assets/git-branch-j3QCD4s-.js                     0.22 kB │ gzip:   0.19 kB
dist/assets/upload-B29dcOQU.js                         0.23 kB │ gzip:   0.19 kB
dist/assets/copy-BvKuWiOn.js                           0.23 kB │ gzip:   0.21 kB
dist/assets/link-2-DlfNa-v1.js                         0.24 kB │ gzip:   0.20 kB
dist/assets/skeleton-Bcb6XioF.js                       0.24 kB │ gzip:   0.20 kB
dist/assets/database-tPcUSlPG.js                       0.24 kB │ gzip:   0.20 kB
dist/assets/chart-column-DkD_NHo1.js                   0.25 kB │ gzip:   0.19 kB
dist/assets/external-link-DQuYHGle.js                  0.25 kB │ gzip:   0.20 kB
dist/assets/eye-Bm8LtpzF.js                            0.25 kB │ gzip:   0.20 kB
dist/assets/dist-BncS-ueq.js                           0.25 kB │ gzip:   0.18 kB
dist/assets/dist-56EZmKtB.js                           0.26 kB │ gzip:   0.21 kB
dist/assets/triangle-alert-Bn8dKm_c.js                 0.26 kB │ gzip:   0.21 kB
dist/assets/shield-CTdVjnzm.js                         0.27 kB │ gzip:   0.22 kB
dist/assets/send-osa1GHNn.js                           0.29 kB │ gzip:   0.23 kB
dist/assets/sign-in-Dyl2DA6V.js                        0.29 kB │ gzip:   0.24 kB
dist/assets/square-pen-CFDJHkrt.js                     0.32 kB │ gzip:   0.24 kB
dist/assets/refresh-cw-Clx8RcqG.js                     0.32 kB │ gzip:   0.22 kB
dist/assets/bot-oM3mG9yd.js                            0.32 kB │ gzip:   0.23 kB
dist/assets/trash-2-BWAOBt-T.js                        0.32 kB │ gzip:   0.21 kB
dist/assets/server-DffUI9RW.js                         0.33 kB │ gzip:   0.21 kB
dist/assets/platform-C0kyzZon.js                       0.34 kB │ gzip:   0.19 kB
dist/assets/main-C2Sxkjt2.js                           0.35 kB │ gzip:   0.26 kB
dist/assets/useNavigate-lmXrTWj5.js                    0.35 kB │ gzip:   0.25 kB
dist/assets/key-round-Bvqfhw5I.js                      0.35 kB │ gzip:   0.26 kB
dist/assets/file-code-corner-BY_BVQZE.js               0.36 kB │ gzip:   0.25 kB
dist/assets/show-submitted-data-ClfjgKfP.js            0.36 kB │ gzip:   0.27 kB
dist/assets/messages-square-BfvGWyL5.js                0.36 kB │ gzip:   0.25 kB
dist/assets/dist-B1m5gfE0.js                           0.37 kB │ gzip:   0.27 kB
dist/assets/dist-BEhS7_6s.js                           0.42 kB │ gzip:   0.32 kB
dist/assets/wrench-BtNizEuh.js                         0.48 kB │ gzip:   0.31 kB
dist/assets/cable-CQzS3SYI.js                          0.49 kB │ gzip:   0.27 kB
dist/assets/conversation-list-island-BJyKyXU7.js       0.51 kB │ gzip:   0.36 kB
dist/assets/dist-B0IovpU2.js                           0.53 kB │ gzip:   0.37 kB
dist/assets/logo-CGVUe-wf.js                           0.54 kB │ gzip:   0.36 kB
dist/assets/auth-layout-DXa3GdRw.js                    0.54 kB │ gzip:   0.31 kB
dist/assets/dist-DP4XSlwp.js                           0.55 kB │ gzip:   0.36 kB
dist/assets/redirect-l1N9PZdQ.js                       0.56 kB │ gzip:   0.33 kB
dist/assets/model-usage-DbIgbkuk.js                    0.56 kB │ gzip:   0.29 kB
dist/assets/content-section-oY_-uLY0.js                0.62 kB │ gzip:   0.32 kB
dist/assets/role-C3-YuOoP.js                           0.63 kB │ gzip:   0.31 kB
dist/assets/user-B-C2pHv0.js                           0.63 kB │ gzip:   0.32 kB
dist/assets/textarea-am35hNOF.js                       0.67 kB │ gzip:   0.41 kB
dist/assets/useRouter-DHFlR_BM.js                      0.69 kB │ gzip:   0.39 kB
dist/assets/label-CXoMKpCv.js                          0.71 kB │ gzip:   0.45 kB
dist/assets/maintenance-error-HFHHUYxO.js              0.73 kB │ gzip:   0.41 kB
dist/assets/embed-clients-eyCQ-33K.js                  0.75 kB │ gzip:   0.27 kB
dist/assets/separator-C0o5egtw.js                      0.80 kB │ gzip:   0.44 kB
dist/assets/shim-cR3Cro0T.js                           0.82 kB │ gzip:   0.44 kB
dist/assets/model-registry-hwRkmglT.js                 0.83 kB │ gzip:   0.35 kB
dist/assets/useSearch-DoidwBfb.js                      0.84 kB │ gzip:   0.47 kB
dist/assets/input-CZPbkjGW.js                          0.86 kB │ gzip:   0.47 kB
dist/assets/lazyRouteComponent-QIzUmY2c.js             0.88 kB │ gzip:   0.52 kB
dist/assets/forbidden-DgrXM5BR.js                      0.90 kB │ gzip:   0.49 kB
dist/assets/learn-more--FVd8Ncf.js                     0.90 kB │ gzip:   0.53 kB
dist/assets/unauthorized-error-Cqfrdqc1.js             0.91 kB │ gzip:   0.50 kB
dist/assets/http-gEJdvpHl.js                           0.95 kB │ gzip:   0.57 kB
dist/assets/_error-DOnmM9F7.js                         0.96 kB │ gzip:   0.51 kB
dist/assets/header-e-JjnRIG.js                         0.97 kB │ gzip:   0.58 kB
dist/assets/host-tools-evlqmIMs.js                     1.03 kB │ gzip:   0.29 kB
dist/assets/search-JORJNJCy.js                         1.03 kB │ gzip:   0.61 kB
dist/assets/task-DU10LCt7.js                           1.07 kB │ gzip:   0.39 kB
dist/assets/sign-in-CPwRLm7G.js                        1.09 kB │ gzip:   0.54 kB
dist/assets/card-qIsdcATF.js                           1.10 kB │ gzip:   0.44 kB
dist/assets/alert-D9g1IYyX.js                          1.11 kB │ gzip:   0.55 kB
dist/assets/radio-group-BAtl8s-y.js                    1.11 kB │ gzip:   0.58 kB
dist/assets/agent-CuX7IN9u.js                          1.12 kB │ gzip:   0.37 kB
dist/assets/help-center-BZOCIudt.js                    1.12 kB │ gzip:   0.65 kB
dist/assets/preload-helper-C5gCWwwF.js                 1.19 kB │ gzip:   0.68 kB
dist/assets/agent-form-schema-DO6xyOKw.js              1.20 kB │ gzip:   0.69 kB
dist/assets/table-BQLO90Aw.js                          1.20 kB │ gzip:   0.48 kB
dist/assets/users-C6xLDaSw.js                          1.20 kB │ gzip:   0.59 kB
dist/assets/badge-OmG5jraG.js                          1.22 kB │ gzip:   0.59 kB
dist/assets/dist-D_83zX3a.js                           1.25 kB │ gzip:   0.63 kB
dist/assets/mcp-servers-9DxUboq9.js                    1.30 kB │ gzip:   0.42 kB
dist/assets/theme-provider-D2sOwWPv.js                 1.37 kB │ gzip:   0.70 kB
dist/assets/createLucideIcon-DTF1kO5E.js               1.38 kB │ gzip:   0.77 kB
dist/assets/theme-switch-Bd4-qe1A.js                   1.40 kB │ gzip:   0.67 kB
dist/assets/password-input-BOTawp3e.js                 1.42 kB │ gzip:   0.77 kB
dist/assets/profile-dropdown-Dd2G5T9q.js               1.46 kB │ gzip:   0.70 kB
dist/assets/form-D42SCiIp.js                           1.73 kB │ gzip:   0.76 kB
dist/assets/display-DBTbTdSt.js                        1.79 kB │ gzip:   0.86 kB
dist/assets/knowledge-CC9QoLOF.js                      1.82 kB │ gzip:   0.61 kB
dist/assets/skills-BuA18IXb.js                         1.89 kB │ gzip:   0.52 kB
dist/assets/sign-in-2-Cry6Jt-5.js                      2.08 kB │ gzip:   0.85 kB
dist/assets/dist-BXvp9l4E.js                           2.10 kB │ gzip:   0.93 kB
dist/assets/use-active-platform-BeBF1qxw.js            2.15 kB │ gzip:   0.99 kB
dist/assets/forgot-password-DykYFXop.js                2.19 kB │ gzip:   1.08 kB
dist/assets/useMutation-DWTRf81I.js                    2.29 kB │ gzip:   0.96 kB
dist/assets/workflow-dUbMJ8ft.js                       2.31 kB │ gzip:   0.85 kB
dist/assets/dialog-ByDf2rLR.js                         2.37 kB │ gzip:   0.88 kB
dist/assets/collapsible-1KwHNzu7.js                    2.53 kB │ gzip:   1.05 kB
dist/assets/switch-Bs7_MNE3.js                         2.79 kB │ gzip:   1.33 kB
dist/assets/route-CL1x_aUb.js                          3.21 kB │ gzip:   1.31 kB
dist/assets/user-auth-form-DbKk1xo5.js                 3.44 kB │ gzip:   1.50 kB
dist/assets/settings-CQM3UZAP.js                       3.45 kB │ gzip:   1.40 kB
dist/assets/react-dom-B0mxLzjk.js                      3.54 kB │ gzip:   1.34 kB
dist/assets/dist-BmBKpw8c.js                           3.56 kB │ gzip:   1.60 kB
dist/assets/dist-CQ70Vynn.js                           3.61 kB │ gzip:   1.59 kB
dist/assets/tabs--9NGdQAq.js                           3.68 kB │ gzip:   1.54 kB
dist/assets/route-DKbWkppA.js                          3.75 kB │ gzip:   1.80 kB
dist/assets/route-DPMVd5e8.js                          3.93 kB │ gzip:   1.59 kB
dist/assets/route-DsRILG6Q.js                          4.18 kB │ gzip:   1.21 kB
dist/assets/button-DldY7v7e.js                         4.20 kB │ gzip:   1.81 kB
dist/assets/checkbox-CkenTkU3.js                       4.31 kB │ gzip:   1.83 kB
dist/assets/dist-C8je_4Yy.js                           4.46 kB │ gzip:   1.92 kB
dist/assets/sign-up-DyvP4HnI.js                        4.47 kB │ gzip:   1.54 kB
dist/assets/appearance-BiL9wnWO.js                     4.55 kB │ gzip:   1.36 kB
dist/assets/_principalType._principalId-B-GyiaXX.js    4.68 kB │ gzip:   1.91 kB
dist/assets/notifications-CUIIyYEj.js                  4.83 kB │ gzip:   1.33 kB
dist/assets/user-management-Dc0nWHUL.js                5.09 kB │ gzip:   2.05 kB
dist/assets/confirm-dialog-CrYzLFZv.js                 5.30 kB │ gzip:   1.92 kB
dist/assets/sign-out-dialog-Ws1evsYQ.js                5.43 kB │ gzip:   2.39 kB
dist/assets/dist-DRN9m38s.js                           5.45 kB │ gzip:   2.11 kB
dist/assets/popover-DkSPeN_8.js                        5.58 kB │ gzip:   1.99 kB
dist/assets/_conversationId-CWY3fciF.js                5.91 kB │ gzip:   2.52 kB
dist/assets/apps-C9f0b789.js                           6.38 kB │ gzip:   2.28 kB
dist/assets/ai-html-pages-A2xHGCJ_.js                  6.88 kB │ gzip:   2.67 kB
dist/assets/platforms-BxUXdtEd.js                      6.93 kB │ gzip:   2.60 kB
dist/assets/bots-AQhHGp2U.js                           7.80 kB │ gzip:   2.90 kB
dist/assets/jsx-runtime-Bg_NI1en.js                    8.52 kB │ gzip:   3.25 kB
dist/assets/useQuery-BZD8L8q4.js                       8.75 kB │ gzip:   3.20 kB
dist/assets/conversations-CDEc1Zox.js                  8.88 kB │ gzip:   2.90 kB
dist/assets/value-Dow4fuvN.js                          9.23 kB │ gzip:   3.96 kB
dist/assets/roles-h04a4Y_E.js                          9.25 kB │ gzip:   3.19 kB
dist/assets/wechat-bots-C_-N8NKW.js                    9.90 kB │ gzip:   3.71 kB
dist/assets/_taskId-DHVJqJBM.js                       10.40 kB │ gzip:   3.50 kB
dist/assets/users-DC87BS5g.js                         10.91 kB │ gzip:   3.66 kB
dist/assets/brand-icons-DGmgmC1s.js                   11.03 kB │ gzip:   2.11 kB
dist/assets/model-usage-uRwpLW6J.js                   11.52 kB │ gzip:   3.56 kB
dist/assets/authenticated-layout-CwTORe6e.js          11.69 kB │ gzip:   4.24 kB
dist/assets/workflows-9n97cZ9_.js                     11.83 kB │ gzip:   4.09 kB
dist/assets/models-CF5F5sXi.js                        12.43 kB │ gzip:   4.20 kB
dist/assets/tasks-tegaC6Vu.js                         12.70 kB │ gzip:   4.34 kB
dist/assets/react-icons.esm-qPRC21--.js               12.79 kB │ gzip:   3.46 kB
dist/assets/otp-CvjdC0mV.js                           12.89 kB │ gzip:   5.02 kB
dist/assets/QueryClientProvider-CRtxJhSP.js           13.79 kB │ gzip:   4.75 kB
dist/assets/embed-clients-DGKVdHOA.js                 14.07 kB │ gzip:   4.57 kB
dist/assets/host-tools-BOqhZA0Z.js                    14.14 kB │ gzip:   4.35 kB
dist/assets/command-58vnU76i.js                       14.32 kB │ gzip:   5.36 kB
dist/assets/mcp-servers-CcYTDlAS.js                   14.56 kB │ gzip:   4.36 kB
dist/assets/knowledge-bases-D68bRzAK.js               16.35 kB │ gzip:   5.16 kB
dist/assets/search-provider-C2Krb9hD.js               20.40 kB │ gzip:   7.01 kB
dist/assets/select-BxzfdJ3f.js                        21.66 kB │ gzip:   7.37 kB
dist/assets/config-drawer-Dx3iBnyx.js                 22.36 kB │ gzip:   4.62 kB
dist/assets/link-BJ-XaPVI.js                          22.59 kB │ gzip:   8.41 kB
dist/assets/skills-BYcqTMRQ.js                        25.44 kB │ gzip:   7.35 kB
dist/assets/utils-D09HVMnN.js                         26.86 kB │ gzip:   8.63 kB
dist/assets/dist-BWfAzbbh.js                          32.57 kB │ gzip:   9.13 kB
dist/assets/zod-DWZmEUKy.js                           34.70 kB │ gzip:  12.20 kB
dist/assets/axios-ClY8Pl96.js                         36.26 kB │ gzip:  14.39 kB
dist/assets/dropdown-menu-Bkn_G0CZ.js                 43.20 kB │ gzip:  11.85 kB
dist/assets/dist-BIRMShzw.js                          45.80 kB │ gzip:  16.71 kB
dist/assets/account-CvW0Edvo.js                       75.42 kB │ gzip:  22.45 kB
dist/assets/dist-Brmf1C2e.js                          89.55 kB │ gzip:  24.72 kB
dist/assets/_workflowId--BoG2T3q.js                  217.23 kB │ gzip:  68.95 kB
dist/assets/zod-C2m4cF4N.js                          260.92 kB │ gzip:  59.69 kB
dist/assets/index-BNEYTT46.js                        284.75 kB │ gzip:  88.17 kB
dist/assets/xxai-agent.es-s5HOIfJZ.js                289.52 kB │ gzip: 106.84 kB
dist/assets/_agentId-Bmeh5Fnp.js                     339.20 kB │ gzip:  97.97 kB
dist/assets/users-DnlGYvz2.js                        497.40 kB │ gzip: 176.56 kB
dist/assets/chats-CodFlf3R.js                        860.30 kB │ gzip: 297.88 kB

✓ built in 898ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 真进程 SSE：每条 data 含 protocolVersion，message_completed 带 usage 且为驼峰

```bash
sse_probe
```

data 行数：26
   1 event: agent_loop_completed
   1 event: agent_loop_started
   3 event: agent_step_completed
   7 event: agent_step_delta
   1 event: agent_step_started
   1 event: message_completed
  12 event: message_delta
缺少 protocolVersion 的 data 行：0
data: {"id":"evt_26","type":"message_completed","protocolVersion":1,"sequence":26,"timestamp":"2026-10-16T11:07:43.285648+00:00","payload":{"content":"我是「开发助手」，为这个仓库的本地开发与联调提供支持，需要时能查证运行时配置与用量信息。","contentBlocks":[{"id":"answer_markdown","type":"markdown","text":"我是「开发助手」，为这个仓库的本地开发与联调提供支持，需要时能查证运行时配置与用量信息。","status":"completed"}],"citations":[],"knowledgeGrounded":false,"usage":{"prompt_tokens":1712,"completion_tokens":90,"total_tokens":1802},"loop":{"id":"9","requestId":"sse-12913fb79efe4f078a41c40171b76ede","status":"completed","summary":"已完成回答","steps":[]}},"conversationId":"7","requestId":"sse-12913fb79efe4f078a41c40171b76ede"}
结果：通过

### python3 tools/harness/audit.py（排除两个「verify.md 尚未生成」的预期 ERROR）

```bash
audit_expect_known_errors
```

ERROR  2026-10-16-model-registry-unification: v2 request 缺少 verify.md

v2 requests: 12  存量跳过: 59  ERROR: 1  WARN: 0
结果：通过

## 未执行项与原因

- 浏览器人工点击：apps/front 内没有任何 SSE 消费代码（grep EventSource / text/event-stream 为空），
  控制台实时对话走 WebSocket SDK 浮窗，因此没有可点的 SSE 界面；SSE 的权威证据是真进程 curl。
- WebSocket 端到端复跑：需要浏览器里的 SDK 会话（embed token + 子协议握手），本次未在浏览器里跑；
  网关编码器改动由 tests/gateway 的 22 个用例覆盖。
- `pnpm --dir apps/ai-sdk test` 会连带跑 scripts/verify-package.test.mjs，该用例在本次改动之前就失败：
  `npm pack --dry-run --json` 的 stdout 被 prepare 脚本（vite build）日志污染导致 JSON.parse 抛错，
  且 vite-plugin-dts 产出 dist/src/**\/*.d.ts 而用例期望 dist/core/**、dist/ui/** —— 打包契约与产物布局漂移。
  与本 request 无关，未修复；本请求的 SDK 证据是 `npx vitest run src`（20 文件 / 160 用例）。
- 真实模型端点出词：真进程 SSE 一步依赖外部 OPENAI_BASE_URL / OPENAI_API_KEY 与余额。
- ② model-registry-unification：本 request 未触及，其 spec.md 已在仓库但尚无 verify.md。

## 验收结论

- 验收标准①~③（共享趋势）：parity 测试断言 SSE/WS 两个编码器逐条等于同一份 golden（20 条），
  `message_completed.payload` 在两条通道上逐字段相同（含 camelCase `usage`），tool_call/tool_result 形状与 SDK 读取一致。
- 验收标准④⑤：后端三目录测试全绿；SDK 单元测试全绿；前端 build（含 tsc -b）通过。
- 验收标准⑥：真进程 `:8080` SSE 每条 data 都带 protocolVersion，message_completed 带 usage 且键名为驼峰。
- 验收标准⑦：信封键、事件构造器与废弃映射助手都收口到 agent_runtime/events.py；SSE 路由不再按事件类型分派。
- 剩余风险：WS 侧本轮仍不发 tool_call/tool_result（有意保留，见 ADR 0007）；SDK 里对应读取分支仍是死分支。
- 是否可归档：达到验收标准；未执行项均为环境依赖或与本 request 无关的既有问题。
