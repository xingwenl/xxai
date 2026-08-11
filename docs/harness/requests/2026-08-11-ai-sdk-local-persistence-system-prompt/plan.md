# 实施计划

## 变更文件

- `apps/ai-sdk/src/core/types.ts`：增加存储配置和可选请求字段类型。
- `apps/ai-sdk/src/core/client.ts`：恢复和持久化消息、会话 ID、发送 systemPrompt，实现清空本地历史。
- `apps/ai-sdk/src/core/websocket.ts`：支持初始会话 ID和显式清除，并保持后续消息携带 ID。
- `apps/backend/app/modules/gateway/router.py`、`runtime.py`：读取可选 systemPrompt 并传入运行时，合并基础提示词。
- `apps/backend/app/modules/conversation/runtime.py`：支持调用方提示词作为受控附加系统消息。
- SDK/后端测试与 `apps/ai-sdk/README.md`：覆盖行为并补充接入说明。
- 本 request 的 `verify.md`、`acceptance.md`、`meta.json`：记录真实验证和结论。

## 实施步骤

1. 实现版本化 localStorage 状态读写，定义默认隔离 key，捕获读写异常。
2. 在 `AgentClient` 初始化恢复消息和会话 ID，监听消息变更保存；实现 `clearLocalHistory()`。
3. 让 WebSocket transport 接收恢复的会话 ID，并将 `systemPrompt` 放入 `message_send`。
4. 扩展网关和运行时参数，将调用方提示词附加到基础系统提示词且保留基础约束。
5. 增加 SDK 和后端定向测试，更新 README。
6. 执行 type-check、测试、build 和 diff 检查，填写 verify/acceptance。

## 测试步骤

- `cd apps/ai-sdk && npm run test -- --run src/core/__tests__/client.test.ts src/core/__tests__/websocket.test.ts`
- `cd apps/ai-sdk && npm run type-check && npm run build`
- `cd apps/backend && poetry run pytest tests/gateway/test_chat_flow.py tests/conversation/test_runtime.py -q`
- `cd apps/backend && poetry run ruff check app/modules/gateway app/modules/conversation tests/gateway tests/conversation`
- `git diff --check`

## 回滚说明

回滚 SDK 本地存储、transport 字段和后端可选参数改动即可恢复原行为，无需数据库回滚；旧客户端不发送 systemPrompt 时后端继续使用基础提示词。

## 人工确认点

- 已确认：WebSocket `message_send` 增加可选 `systemPrompt`，本地缓存消息与 `conversationId`，清空后开启新会话。
