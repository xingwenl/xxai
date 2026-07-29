# 验证记录

## 当前阶段

- 阶段：verify
- 状态：验证完成
- 说明：已完成自动化检查、真实 PostgreSQL、DeepSeek 模型和 WebSocket 宿主工具联调。

## 已执行命令与结果

- `cd apps/backend && poetry run pytest`
  - 预期：后端全量测试通过。
  - 实际：`127 passed, 1 skipped, 1 warning`。

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

- `cd apps/backend && poetry run python scripts/seed_demo_host_tools.py`
  - 预期：写入 Demo 工具策略、Agent 绑定和 Client 绑定。
  - 实际：`已配置 Demo 宿主工具: get_weather, calculate_total, get_order_status`。

- 真实 WebSocket 联调脚本（使用 `httpx`、`websockets`、DeepSeek 和本地 PostgreSQL）
  - 预期：依次收到 `session_ready`、`message_started`、`host_tool_call`、`message_delta`、`message_completed`。
  - 实际：顺序符合预期；`host_tool_call` 为 `get_weather`，参数为 `{"city":"上海"}`；回传 Demo 结果后最终回答包含 `26°C`、`多雨`。
  - 审计证据：`host_tool_call_audits.call_id=call_00_eeoGEg9tZOSgRCSZXIyj7348`，状态 `succeeded`，结果包含 `temperature=26`、`condition=多雨`。

- `cd apps/ai-sdk && npm run type-check && npm run test -- --run && npm run build`
  - 预期：SDK 类型检查、Vitest 和生产构建通过。
  - 实际：`type-check` 通过；`3 test files / 11 tests passed`；Vite ESM/UMD 构建通过。

## 已覆盖行为

- 三重白名单求交、Schema 基本校验、状态迁移和敏感字段递归脱敏。
- Host Tool 策略/Agent 绑定/Client 绑定模型、管理路由、token `host_tools` claim。
- WebSocket 注册、`host_tool_call` 协议、确认、结果/错误回传和 `callId` 状态更新。
- Agent Runtime 的宿主工具绑定、页面结果回写和继续生成路径。
- SDK 注册、参数校验、确认回调、超时、结果大小限制和 destroy 清理。

## 未验证项与剩余风险

- 未在本轮执行 Redis 重放场景的多连接 E2E；真实 PostgreSQL、WebSocket 和模型 tool-call 主链路已完成。
- 未完成完整 Playwright 浏览器 E2E；本轮通过协议探针完成等价的真实 WebSocket 联调。SDK 校验器仍覆盖核心 object/required/properties/enum 语义，尚未引入完整 JSON Schema Draft 2020-12 浏览器验证器。
- 真实页面函数执行后的“结果已产生但回传丢失”恢复仍需部署环境验证；当前服务端遵守 `callId` 不盲目重试。
- 保留已有 FastAPI/Starlette 的一个弃用警告，不影响本次测试结果。

## Bugfix 验证

- 失败复现：新增的 native timer receiver 测试在修复前以 TypeError: Illegal invocation 失败。
- 修复后：同一测试通过，handleClose 触发重连时不再抛出 receiver 错误。

## Demo 自动调用接入

- 已验证：Demo token proxy 接收重复的 host_tool_names query 参数，并传入 EmbedTokenRequest。
- 已验证：seed 脚本通过 Ruff 和 Python compileall。
- 已完成：执行 seed 后，真实调用天气工具成功产生 `host_tool_call`，SDK/协议探针回传结果，后端审计为 `succeeded`，模型返回包含工具结果的最终回答。

## 本轮 Bugfix 验证

- 失败复现：真实 PostgreSQL 写入审计时因 `TIMESTAMP WITHOUT TIME ZONE` 接收到带时区 datetime，报 `can't subtract offset-naive and offset-aware datetimes`。
- 修复后：审计创建和状态更新使用 UTC 无时区时间；真实调用成功，审计状态为 `succeeded`。
- 额外修复：runtime 异常现在通过非空 `error` payload 回传客户端，避免页面永久停留在发送中。
