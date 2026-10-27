---
source: script
request: 2026-10-27-ai-sdk-message-usage
ranAt: "2026-10-27 17:46:01 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端：用量归一化与 provider 推导单测
```
..........                                                               [100%]
10 passed in 2.22s
--- PASS: 后端：用量归一化与 provider 推导单测
```

### 后端：消息快照透出 usage（含坏数据不炸）
```
..                                                                       [100%]
2 passed in 1.82s
--- PASS: 后端：消息快照透出 usage（含坏数据不炸）
```

### 后端：embed 消息快照响应契约（usage 可选）
```
..                                                                       [100%]
2 passed in 1.80s
--- PASS: 后端：embed 消息快照响应契约（usage 可选）
```

### 后端：网关端到端（payload + 元数据 + 计费表分工）
```
....................                                                     [100%]
20 passed in 1.84s
--- PASS: 后端：网关端到端（payload + 元数据 + 计费表分工）
```

### 后端：OpenAPI 里 MessageUsage 与消息快照路由齐备
```
PASS  MessageUsage 已注册，ConversationMessageRead.usage 存在，快照路由已注册
--- PASS
```

### 后端：受影响包回归
```
........................................................................ [ 18%]
........................................................................ [ 37%]
........................................................................ [ 56%]
........................................................................ [ 74%]
........................................................................ [ 93%]
.........................                                                [100%]
385 passed in 10.01s
--- PASS: 后端：受影响包回归
```

### 后端：改动文件 ruff 检查
```
All checks passed!
--- PASS: 后端：改动文件 ruff 检查
```

### SDK：用量解析与口径纯函数
```

 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/core/__tests__/usage.test.ts (12 tests) 3ms

 Test Files  1 passed (1)
      Tests  12 passed (12)
   Start at  17:45:46
   Duration  281ms (transform 29ms, setup 0ms, collect 23ms, tests 3ms, environment 0ms, prepare 49ms)

--- PASS: SDK：用量解析与口径纯函数
```

### SDK：chip 文案与明细行
```

 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/usage-view.test.ts (8 tests) 13ms

 Test Files  1 passed (1)
      Tests  8 passed (8)
   Start at  17:45:47
   Duration  297ms (transform 29ms, setup 0ms, collect 29ms, tests 13ms, environment 0ms, prepare 50ms)

--- PASS: SDK：chip 文案与明细行
```

### SDK：chip 展开/收起交互（jsdom 真点）
```

 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/usage-chip.component.test.ts (3 tests) 37ms

 Test Files  1 passed (1)
      Tests  3 passed (3)
   Start at  17:45:47
   Duration  826ms (transform 190ms, setup 0ms, collect 239ms, tests 37ms, environment 305ms, prepare 38ms)

--- PASS: SDK：chip 展开/收起交互（jsdom 真点）
```

### SDK：消息与列表渲染面（用户消息不出 chip、会话累计）
```

 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/ui/__tests__/usage-surface.ssr.test.ts (5 tests) 34ms

 Test Files  1 passed (1)
      Tests  5 passed (5)
   Start at  17:45:49
   Duration  1.05s (transform 392ms, setup 0ms, collect 502ms, tests 34ms, environment 246ms, prepare 42ms)

--- PASS: SDK：消息与列表渲染面（用户消息不出 chip、会话累计）
```

### SDK：历史映射透传 usage
```

 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/history/__tests__/map-history.test.ts (3 tests) 2ms

 Test Files  1 passed (1)
      Tests  3 passed (3)
   Start at  17:45:50
   Duration  268ms (transform 22ms, setup 0ms, collect 18ms, tests 2ms, environment 0ms, prepare 38ms)

--- PASS: SDK：历史映射透传 usage
```

### SDK：src 全量单测（不含 scripts/ 下的打包门禁用例）
```
 ✓ src/core/__tests__/client-replay.test.ts (3 tests) 5ms
 ✓ src/ui/__tests__/markdown-content.test.ts (7 tests) 11ms
 ✓ src/core/__tests__/errors.test.ts (8 tests) 12ms
 ✓ src/ui/__tests__/context-ring.test.ts (10 tests) 7ms
 ✓ src/ui/__tests__/usage-view.test.ts (8 tests) 25ms
 ✓ src/history/__tests__/map-history.test.ts (3 tests) 3ms
 ✓ src/ui/__tests__/two-step-confirm.test.ts (6 tests) 12ms
 ✓ src/core/__tests__/page-tools.test.ts (3 tests) 4ms
 ✓ src/ui/__tests__/markdown-fence-registry.test.ts (5 tests) 5ms
 ✓ src/core/__tests__/attachments.test.ts (4 tests) 3ms
 ✓ src/ui/__tests__/window-storage.test.ts (3 tests) 3ms
 ✓ src/ui/__tests__/header-name.test.ts (4 tests) 1ms
 ✓ src/ui/__tests__/quota-ring.test.ts (5 tests) 14ms
 ✓ src/ui/__tests__/context-ring.component.test.ts (4 tests) 12ms
 ✓ src/ui/__tests__/chat-scroll.test.ts (2 tests) 2ms
 ✓ src/ui/__tests__/usage-chip.component.test.ts (3 tests) 46ms
 ✓ src/ui/__tests__/markdown-diagram-dom.test.ts (7 tests) 142ms
 ✓ src/ui/__tests__/chat-message.ssr.test.ts (9 tests) 24ms
 ✓ src/ui/__tests__/usage-surface.ssr.test.ts (5 tests) 35ms

 Test Files  31 passed (31)
      Tests  270 passed (270)
   Start at  17:45:51
   Duration  2.09s (transform 1.39s, setup 0ms, collect 3.58s, tests 636ms, environment 1.26s, prepare 2.46s)

--- PASS: SDK：src 全量单测（不含 scripts/ 下的打包门禁用例）
```

### SDK：类型检查
```

> xxai-agent@0.2.0 type-check /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
> vue-tsc --noEmit

--- PASS: SDK：类型检查
```

### SDK：构建
```

> xxai-agent@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
> vite build

vite v5.4.21 building for production...
transforming...
✓ 119 modules transformed.
rendering chunks...

[vite:dts] Start generate declaration files...
computing gzip size...
dist/style.css          49.59 kB │ gzip:   8.85 kB
dist/xxai-agent.es.js  482.86 kB │ gzip: 148.10 kB
[vite:dts] Declaration files built in 2239ms.

dist/style.css            49.59 kB │ gzip:   8.85 kB
dist/xxai-agent.umd.cjs  327.68 kB │ gzip: 119.81 kB
✓ built in 3.25s
--- PASS: SDK：构建
```

### SDK：产物含 chip 文案与类名
```
PASS  dist 内命中「本轮用量」「用量 」「本会话累计」与两个类名
```

### 仓库：空白错误检查
```
--- PASS: 仓库：空白错误检查
```

## 未执行项与原因

- 真实模型下的缓存命中数字：需要供应商（DeepSeek / OpenAI）返回 usage 明细的真实调用，本地只覆盖了替身模型与归一化单测。
- 浏览器里的最终视觉核对（chip 圆角、明细卡宽度、窄窗 375px 换行）：需要人工打开 demo 页面看截图，脚本未跑无头浏览器。
- 存量消息（本方案上线前产生的 assistant 消息）的兼容表现：本地库没有对应数据，只能靠「缺 usage 不渲染 chip」的单测与契约断言，未做真实历史会话回放。
- `apps/ai-sdk/scripts/verify-package.test.mjs`：预存在失败（`npm pack --dry-run --json` 的 stdout 被 `prepare` 的 vite 构建日志污染成非 JSON），与本轮改动无关，未作为通过项。
- 端到端「刷新页面后 chip 仍在」：需要前端 + 后端 + 浏览器联调，脚本只验证了历史映射函数与快照字段两段。

## 验收结论

通过：归一化、落库/事件、快照契约、SDK 展示与历史回放映射、构建与回归测试全部成功；未执行为真实供应商数字、浏览器视觉与存量消息回放。
