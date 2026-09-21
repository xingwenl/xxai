---
source: script
request: 2026-09-21-ai-sdk-thinking-and-loop-visibility
ranAt: "2026-09-21 16:27:07 CST"
exitCode: 3
---

## 已执行的命令与结果

### 前端：思考/过程卡片开关 SSR 单测（默认关闭 + 显式开启）

```bash
bash -c cd apps/ai-sdk && npx vitest run src/ui/__tests__/chat-message.ssr.test.ts --reporter=verbose 2>&1 | grep -E '✓|×|Test Files|Tests ' | tail -15
```

 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage timeline rendering > renders rich content blocks (custom) even when timeline exists
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage timeline rendering > merges leading skill steps into one collapsible group
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage timeline rendering > renders thinking as a collapsed details after completion
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage timeline rendering > keeps thinking details open while generation is running
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage timeline rendering > does not merge skills that appear after generation
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage hides agent steps by default > renders only the answer text when showAgentSteps is not passed
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage hides agent steps by default > keeps timeline answer text while dropping step entries
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > ChatMessage hides agent steps by default > still shows the typing indicator for an empty pending message with a loop
 ✓ src/ui/__tests__/chat-message.ssr.test.ts > AgentLoopPanel fallback rendering > merges leading skill steps in the history fallback path
 Test Files  1 passed (1)
      Tests  9 passed (9)
结果：通过

### 前端：全量单测回归

```bash
bash -c cd apps/ai-sdk && npx vitest run 2>&1 | grep -E 'Test Files|Tests ' | tail -5
```

    at startTests (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3)
 Test Files  20 passed (20)
      Tests  153 passed (153)
结果：通过

### 前端：类型检查

```bash
bash -c cd apps/ai-sdk && npx vue-tsc --noEmit 2>&1 | tail -10
```

结果：通过

### 后端：思考开关翻译与构造行为单测

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/agent/test_thinking_switch.py -q 2>&1 | tail -5
```

.........                                                                [100%]
9 passed in 3.50s
结果：通过

### 后端：message_send 的 thinking 校验单测

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/gateway/test_thinking_payload.py -q 2>&1 | tail -5
```

...                                                                      [100%]
3 passed in 2.55s
结果：通过

### 后端：agent + gateway 单测回归

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/agent tests/gateway -q 2>&1 | tail -5
```

  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
143 passed, 1 skipped, 1 warning in 3.70s
结果：通过

### 后端：ruff 检查本次改动的模块与新增测试

```bash
bash -c cd apps/backend && .venv/bin/python -m ruff check app/modules/agent/services.py app/modules/gateway/router.py app/modules/gateway/schemas.py tests/agent/test_thinking_switch.py tests/gateway/test_thinking_payload.py
```

All checks passed!
结果：通过

### 前端：构建 + 包产物校验

```bash
bash -c cd apps/ai-sdk && npm run build >/dev/null 2>&1 && npm run verify-package 2>&1 | tail -3
```

> node scripts/verify-package.mjs

Package entries verified: ./dist/xxai-agent.es.js, ./dist/xxai-agent.umd.cjs, ./dist/index.d.ts, ./dist/style.css
结果：通过

### 端到端：真实模型是否因 thinking=false 而不返回 reasoning_content

结果：未执行（本机未检测到运行中的后端 http://127.0.0.1:8000）

## 未执行项与原因

- 真实模型端到端联调：未起真实后端与上游模型，未验证「thinking=false 时上游确不返回 reasoning_content」。单测只覆盖到「参数被正确翻译并注入构造器」这一层，上游实际是否遵守该参数需人工联调确认。
- 非 DeepSeek 厂商的实际兼容性：仅验证了参数翻译逻辑；未对 Qwen/GLM 等真实端点发起请求，无法确认其对 reasoning_effort=none 的接受度。
- 真实 PostgreSQL：本机后端单测不涉及数据库读写，本次改动未新增查询，故未做数据库级验证。

## 验收结论

- 达到 spec.md 验收标准：第 1~7 条均有对应自动化断言且通过（前端 9 项 SSR 用例、后端 12 项单测；全量回归前端 153 项、后端 143 项）。
- 剩余风险：单测只证明「参数被正确翻译并注入构造器」，未证明上游模型确实遵守该参数；非 DeepSeek 厂商对 reasoning_effort=none 的接受度未经真实验证。
- 可归档：可实现归档；建议合并前人工跑一次真实对话，确认 thinking=false 时不再出现思考文本。
