# 验收记录

## 当前结论

2026-07-31 临时工具增量已完成：默认三重白名单逻辑保持不变；Embed Client 后台开启临时工具能力后，SDK 工具仅在当前连接内存中注册，重连自动恢复，token 不再需要维护 `host_tool_names`。

增量验证：SDK 20 个测试通过；Gateway、Host Tool、Embed 后端测试 48 个通过、1 个跳过；Ruff、Black、类型检查和 diff 检查通过。

2026-07-31 轻量 Bugfix 已完成：后台提交完整策略对象时，未变化的 `input_schema` 不再覆盖 `is_enabled`，对应回归测试和静态检查通过。

Phase 2B 核心宿主工具自动调用链已达到验收条件，request 可标记 done。真实 PostgreSQL、DeepSeek 模型和 WebSocket 协议联调均已完成。

## 已达到

- 已实现独立宿主工具策略、Agent/Client 绑定、token claim、网关事件、调用状态和独立审计模型。
- 已实现三重白名单、确认状态、callId 幂等、结果大小限制、脱敏和 SDK 执行/清理。
- 已修复 WebSocket 非正常关闭时原生 timer 的 Illegal invocation，并通过回归测试。
- 后端全量测试 127 passed, 1 skipped；SDK 11 tests passed、type-check 和 build 通过。
- Demo 真实调用 `get_weather` 成功，审计状态为 `succeeded`，最终回答包含页面函数返回结果。

## 剩余风险

- `alembic check` 在当前受限环境中仍无法执行；迁移 head 和真实业务表写入已确认。
- SDK 当前是核心 Schema 校验器，尚未引入完整 JSON Schema Draft 2020-12 浏览器验证器。
- Redis 重放、多连接确认竞态和完整 Playwright E2E 仍需部署环境回归。

## 验收结论

验收结论：Phase 2B 核心目标完成，可以进入合并/归档；上述剩余风险作为后续增强项记录，不影响本次 Demo 自动调用主链路。
