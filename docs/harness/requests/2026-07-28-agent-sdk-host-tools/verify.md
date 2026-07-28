# 验证记录

## 当前阶段

- 阶段：verify
- 状态：实现验证基本完成，等待真实数据库/浏览器联调补证据
- 说明：已完成 research、spec、plan、人工确认和运行时实现；request 暂不标记 done。

## 已执行命令与结果

- `cd apps/backend && poetry run pytest`
  - 预期：后端全量测试通过。
  - 实际：`126 passed, 1 skipped, 1 warning`。

- `cd apps/backend && poetry run ruff check <本次触及后端文件>`
  - 预期：本次触及范围无 Ruff 错误。
  - 实际：`All checks passed!`。

- `cd apps/backend && poetry run black --check <本次触及文件>`
  - 预期：本次新增/修改后端文件格式通过。
  - 实际：格式化后通过；全仓 Black 仍有 2A 之前已有文件未格式化，未对无关文件做批量改动。

- `cd apps/backend && poetry run alembic heads`
  - 预期：Phase 2B migration 为唯一 head。
  - 实际：`20260728_0010 (head)`。

- `cd apps/backend && poetry run alembic check`
  - 预期：迁移与模型无差异。
  - 实际：未完成；当前环境无法连接 PostgreSQL，报 `PermissionError: [Errno 1] Operation not permitted`。

- `cd apps/ai-sdk && npm run type-check && npm run test -- --run && npm run build`
  - 预期：SDK 类型检查、Vitest 和生产构建通过。
  - 实际：`type-check` 通过；`4 test files / 10 tests passed`；Vite ESM/UMD 构建通过。

## 已覆盖行为

- 三重白名单求交、Schema 基本校验、状态迁移和敏感字段递归脱敏。
- Host Tool 策略/Agent 绑定/Client 绑定模型、管理路由、token `host_tools` claim。
- WebSocket 注册、`host_tool_call` 协议、确认、结果/错误回传和 `callId` 状态更新。
- Agent Runtime 的宿主工具绑定、页面结果回写和继续生成路径。
- SDK 注册、参数校验、确认回调、超时、结果大小限制和 destroy 清理。

## 未验证项与剩余风险

- 未在真实 PostgreSQL/Redis 环境执行 migration、WebSocket 多连接和真实模型 tool-call 联调。
- 未完成 Playwright 浏览器 E2E；当前 SDK 校验器覆盖核心 object/required/properties/enum 语义，尚未引入完整 JSON Schema Draft 2020-12 浏览器验证器。
- 真实页面函数执行后的“结果已产生但回传丢失”恢复仍需部署环境验证；当前服务端遵守 `callId` 不盲目重试。
- 保留已有 FastAPI/Starlette 的一个弃用警告，不影响本次测试结果。
