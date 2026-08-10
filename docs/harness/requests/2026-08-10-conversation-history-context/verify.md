# 验证记录

## 已执行命令

| 命令 | 预期结果 | 实际结果 |
|---|---|---|
| `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py -q` | 对话运行时测试通过 | 21 passed |
| `cd apps/backend && poetry run pytest tests/gateway/test_chat_flow.py tests/conversation/test_runtime.py -q` | SDK WebSocket 网关和运行时测试通过 | 27 passed |
| `cd apps/backend && poetry run ruff check app/modules/conversation app/core/config.py tests/conversation/test_runtime.py` | 无静态检查错误 | All checks passed |
| `cd apps/ai-sdk && npm run build` | SDK 可正常构建并生成声明文件 | 构建成功 |
| `cd apps/ai-sdk && npm test -- --run src/core/__tests__/websocket.test.ts` | SDK 后续消息携带会话 ID | 通过 |
| `cd apps/ai-sdk && npm test -- --run src/core/__tests__/client.test.ts src/core/__tests__/websocket.test.ts` | SDK 客户端与传输层使用同一会话 ID | 21 passed |
| `cd apps/backend && poetry run pytest tests/gateway/test_chat_flow.py -q` | 会话诊断日志不影响网关行为 | 6 passed |
| `cd apps/backend && poetry run pytest tests/gateway/test_connection_limits.py tests/gateway/test_chat_flow.py -q` | conversationId 类型归一化和网关流程通过 | 17 passed |
| `cd apps/backend && poetry run pytest -q` | 全后端测试通过 | 未完成：仓库已有同名测试模块导致 3 个 collection mismatch（`tests/embed/test_models.py`、`tests/user/test_routes.py`、`tests/user/test_services.py`） |
| `git diff --check` | 变更无空白错误 | 未通过：现有 `apps/ai-sdk/index.html` 包含尾随空格，且该文件有本次任务之外的未提交改动 |
| `docker compose config` | 历史窗口变量可被 Compose 解析并传入后端 | 配置解析成功，默认值为 3600 |

## 验证结论

本次历史消息逻辑的定向测试、后端静态检查和 SDK 构建均通过。全量测试阻塞于既有测试模块命名冲突，不属于本次改动引入；未修改无关脏文件。

## 未解决问题

- 尚未通过全后端测试收集阶段，需要后续统一测试模块命名或补充包初始化文件。
- 尚未做真实模型联调，需在部署环境配置 `CONVERSATION_HISTORY_WINDOW_SECONDS` 后人工确认 token 成本。
