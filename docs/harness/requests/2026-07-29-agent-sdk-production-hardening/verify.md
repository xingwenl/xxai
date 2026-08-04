# 验证记录

## 当前阶段

已完成 research、spec、plan、implement 和 verify；2026-07-31 完成 npm 发布契约修复增量。

## 2026-08-04 增量验证

- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation/test_runtime.py apps/backend/tests/knowledge/test_knowledge_services.py -q`，`33 passed`。
- `apps/backend/.venv/bin/pytest apps/backend/tests/gateway/test_chat_flow.py -q`，`3 passed`。
- `apps/backend/.venv/bin/ruff check apps/backend/app/modules/conversation/runtime.py apps/backend/app/modules/conversation/services.py apps/backend/app/modules/gateway/runtime.py apps/backend/app/modules/knowledge/runtime.py apps/backend/tests/conversation/test_runtime.py apps/backend/tests/knowledge/test_knowledge_services.py`，通过。
- 覆盖点：runtime context 日志、chat graph 日志、embed chat 日志、knowledge embedding 配置日志，以及 embedding API Key 不再出现在日志中的回归。

## 已执行

- 基线后端：`poetry run pytest -q`，`127 passed, 1 skipped`。
- 基线 SDK：`npm run test -- --run`，`11 tests passed`；`npm run type-check` 通过。
- 配额 RED：缺少 `app.modules.quota`，按预期失败；修正计数器允许/拒绝返回契约后，`tests/quota/test_service.py` 为 `4 passed`。
- metrics/协议 RED：缺少模块/兼容函数，按预期失败；实现后对应测试为 `4 passed`。
- 后端定向：`poetry run pytest tests/quota tests/observability tests/gateway -q`，`27 passed, 1 skipped`。
- 后端全量：`poetry run pytest -q`，`136 passed, 1 skipped`。
- usage 增量：`extract_token_usage`、流式 completed usage 和 SDK `metadata.usage` 测试通过。
- SDK 兼容 RED：auth 缺少版本字段、兼容错误未结束连接；实现后 `compatibility.test.ts` 为 `2 passed`。
- SDK 全量：`npm run test -- --run`，`13 tests passed`；`npm run type-check` 通过。
- SDK 构建：`npm run build`，ESM、UMD 和类型声明构建通过。
- 包入口：`npm run verify-package`，通过。
- 包清单：`npm_config_cache=/tmp/ai-sdk-npm-cache npm pack --dry-run`，通过；首次默认 cache 失败原因为 root-owned npm cache，未修改用户 cache。
- Docker PostgreSQL：`poetry run alembic current` 显示 `20260728_0010 (head)`。
- Docker Redis：`PHASE2_REDIS_URL=redis://127.0.0.1:6379/0 poetry run pytest tests/gateway/test_replay_integration.py -q`，`1 passed`。
- 真实 Redis Lua 配额检查：同一窗口第一次返回 `allowed`，第二次返回 `quota_exceeded`。
- 真实 Redis `token_issue` 配额检查：同一 Client/Agent 窗口第一次返回 `allowed`，第二次返回 `quota_exceeded`。
- runtime usage 增量：usage 标准化和流式 completed usage 测试通过，定向 `13 passed`。
- Agent 1 v2 的 `model_options` 已确认是 `{"stream_usage": true}`。
- model usage 明细 RED：`poetry run pytest tests/gateway/test_chat_flow.py -q`，新增用例因 `stream_embed_chat()` 不支持 `client_id` 按预期失败。
- model usage 明细 GREEN：`poetry run pytest tests/gateway/test_chat_flow.py tests/conversation/test_usage_records.py -q`，`4 passed`。
- Docker PostgreSQL 迁移：`poetry run alembic current` 确认起点为 `20260729_0011`；`poetry run alembic upgrade head` 成功执行 `20260729_0011 -> 20260730_0012`；再次执行 `poetry run alembic current` 为 `20260730_0012 (head)`。
- 真实 DeepSeek E2E：在当前代码临时后端 `127.0.0.1:8011` 上通过 `/api/agent-token` 和 `ai-agent.v1` WebSocket 发送一条短消息。事件序列为 `session_ready`、`message_started`、`message_delta`、`message_delta`、`message_completed`；completed usage 与 PostgreSQL `model_usage_records` 同为 `prompt_tokens=16`、`completion_tokens=21`、`total_tokens=37`，模型名为 `deepseek-v4-pro`。

## 待执行

- `poetry run ruff check .`
- `poetry check`
- `npm run build` 后再次执行 `npm run verify-package` 和临时 cache 的 `npm pack --dry-run`，构建成功，包仅包含 README、package.json、ESM、UMD、CSS 和类型入口共 6 个文件。
- `git diff --check`，通过。

## 最终结果

- `poetry run ruff check .`：通过。
- `poetry check`：通过。
- 后端最终 `poetry run pytest -q`：`156 passed, 1 skipped`。
- SDK `npm run test -- --run`：`13 passed`。
- SDK `npm run type-check`：通过。
- SDK `npm run build`：ESM、UMD、类型声明通过。
- `npm run verify-package`：通过。
- `npm_config_cache=/tmp/ai-sdk-npm-cache npm pack --dry-run`：通过，39 个发布文件。
- 发布契约 RED：`npm run test -- --run scripts/verify-package.test.mjs`，旧实现按预期 3 项失败，暴露 tarball 类型缺失、CommonJS 空导出和缺少 `prepublishOnly`。
- 发布契约 GREEN：`npm run test -- --run scripts/verify-package.test.mjs`，`3 passed`。
- SDK 最终回归：`npm run test -- --run`，`16 passed`；`npm run type-check`，通过；`npm run verify-package`，通过。
- npm 包清单：`npm_config_cache=/tmp/ai-sdk-npm-cache npm pack --dry-run --json`，`39` 个文件，包含 `dist/core`、`dist/ui` 全部声明文件和 `dist/style.css`。
- 临时消费者安装：从真实 `xxai-agent-0.1.0.tgz` 安装后，CommonJS 导出、ESM 导出和 `import.meta.resolve('xxai-agent/style.css')` 均通过。
- `git diff --check`：通过。

## 未覆盖项与例外

- 真实 Redis/PostgreSQL 已完成基础联通和单实例验证，多实例压测尚未执行。
- quota 在开发环境默认关闭，生产部署必须显式确认 `QUOTA_ENABLED=true`。
- runtime 已读取 `usage_metadata`/`token_usage`，并在 completed 事件中返回 usage、按 `total_tokens` 扣减 model token quota。
- Agent 1 v2 的真实 usage 已由用户在 Demo 中确认可见；token 签发路径已接入 `token_issue` quota。
- 已新增独立 `model_usage_records` 明细表、ORM 模型、Repository 写入方法和运行时落库测试。
- 已完成真实 DeepSeek usage 到 `model_usage_records` 的端到端验证；验证只记录事件类型、模型名与 token 数字，未记录密钥、token、用户消息或完整模型回复。
- Playwright 断网、CDN 外部加载和反向代理矩阵未执行。
- Node.js 不直接执行 CSS 文件；CSS 子路径已通过消费者包解析验证，实际样式加载需由 bundler 或浏览器处理。
