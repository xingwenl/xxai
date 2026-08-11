# 验证记录

## 执行命令与结果

| 命令 | 预期结果 | 实际结果 |
|---|---|---|
| `cd apps/ai-sdk && npm run test -- --run` | SDK 全量测试通过 | 9 个测试文件、43 项测试通过 |
| `cd apps/ai-sdk && npm run type-check` | TypeScript/Vue 类型检查通过 | 通过 |
| `cd apps/ai-sdk && npm run build` | ESM、UMD、CSS 和声明文件构建成功 | 构建成功，73 个模块完成转换 |
| `cd apps/backend && poetry run pytest tests/gateway/test_chat_flow.py tests/conversation/test_runtime.py -q` | 网关会话和系统提示词测试通过 | 28 passed |
| `cd apps/backend && poetry run ruff check app/modules/gateway app/modules/conversation tests/gateway tests/conversation` | 后端相关目录无静态检查错误 | All checks passed |
| `git diff --check` | 本次差异无空白错误 | 通过 |

## 验证覆盖

- SDK 能恢复版本化本地消息和会话 ID，并将 `Date` 时间戳复原。
- 恢复的会话 ID 在刷新后的第一条消息中同时进入顶层 envelope 和 payload。
- 清空会话 ID 后下一条消息不再携带旧 ID。
- `systemPrompt` 随消息发送，后端合并后仍保留 Agent 基础提示词。
- localStorage 不可用、非法或旧版本时会降级为内存状态，不阻塞初始化。

## 失败项与例外

- 无验证失败。
- 测试输出中的连接错误日志来自既有错误路径测试的预期行为，对应测试已通过。
- 工作区原有 `apps/backend/app/modules/gateway/runtime.py` 两行临时历史日志删除改动不属于本次实现，本次未恢复或覆盖。
