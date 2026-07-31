# 实施计划

## 变更文件

- `apps/backend/app/modules/quota/`：新增 Redis 固定窗口配额服务，覆盖 token 签发、连接、消息和模型 token 消费。
- `apps/backend/app/modules/observability/`：新增 Prometheus 指标定义和 `/metrics` 暴露。
- `apps/backend/app/modules/gateway/`：接入协议兼容、连接/消息/model token 配额和 completed usage 返回。
- `apps/backend/app/modules/embed/`：接入 token 签发配额，超限前不创建最终用户。
- `apps/backend/app/modules/conversation/runtime.py`：读取并标准化模型 usage。
- `apps/backend/app/modules/conversation/models.py`、`repositories.py`：新增 `model_usage_records` 独立用量明细表和写入方法。
- `apps/backend/migrations/versions/20260730_0012_model_usage_records.py`：新增模型用量明细表迁移。
- `apps/ai-sdk/src/core/`：发送 SDK 版本、保存 server capabilities、暴露 `metadata.usage`。
- `apps/ai-sdk/scripts/verify-package.mjs`：验证 ESM/UMD/types 入口和敏感内容。
- `apps/ai-sdk/scripts/verify-package.test.mjs`：验证发布 tarball 文件清单、ESM/CommonJS 导出和 CSS 子路径契约。
- `apps/ai-sdk/package.json`、`apps/ai-sdk/vite.config.ts`：修正发布入口、类型文件清单和发布前构建流程。
- `docs/design/`、`docs/runbooks/`、`docs/harness/requests/2026-07-29-agent-sdk-production-hardening/`：补齐兼容矩阵、运行手册和 Harness 记录。

## 实施步骤

1. 先写配额、指标、协议兼容、usage 和 SDK 映射的失败测试。
2. 实现 Redis quota store、metrics、协议兼容函数和 SDK auth 版本声明。
3. 在 token exchange、WebSocket 连接、消息发送和模型 completed 边界接入 quota。
4. 从 LangChain/OpenAI 响应中标准化 `prompt_tokens`、`completion_tokens`、`total_tokens`。
5. 模型 completed result 带 usage 时，写入独立 `model_usage_records` 明细；缺失 usage 时不伪造、不落库。
6. 调整 SDK 发布包入口，补充 package 验证脚本。
7. 以失败测试复现 tarball 类型缺失和 CommonJS 空导出，修正 UMD 扩展名、完整类型发布、CSS 子路径和 `prepublishOnly`。
8. 补齐中文兼容矩阵、运行手册、verify 和 acceptance。

## 测试步骤

- `poetry run pytest -q`，预期后端全量通过。
- `poetry run ruff check .`，预期通过。
- `poetry check`，预期通过。
- `npm run test -- --run`，预期 SDK 单测通过。
- `npm run type-check`，预期通过。
- `npm run build`、`npm run verify-package`、`npm_config_cache=/tmp/ai-sdk-npm-cache npm pack --dry-run`，预期发布包只包含公共产物。
- `npm run test -- --run scripts/verify-package.test.mjs`，预期覆盖真实 tarball 的 ESM、CommonJS、类型和 CSS 入口。
- 真实 Redis 验证 replay、message quota 和 token_issue quota 第一次允许、第二次超限。
- `poetry run pytest tests/gateway/test_chat_flow.py tests/conversation/test_usage_records.py -q`，预期模型 usage 明细运行时和 Repository 写入测试通过。
- `poetry run alembic upgrade head`，预期 PostgreSQL 升级到 `20260730_0012`。

## 回滚说明

回滚时先评估是否保留 `model_usage_records` 已写入数据；若确认回滚模型用量明细，执行 Alembic downgrade 到 `20260729_0011` 会删除该表。其余回滚撤回 quota/observability 模块、网关与 token 路由接入、SDK 兼容字段和发布验证脚本即可。Redis quota key 带 TTL，不需要数据清理。

## 人工确认点

用户已确认 Phase 2C 生产核心范围，并于 2026-07-30 确认采用独立 `model_usage_records` 用量明细表。若后续新增计费事实表、余额扣减或后台配额管理 API，需要另行创建 request 并重新确认。
