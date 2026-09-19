# 验收记录

## 当前结论

2026-09-19 时间列读写口径修复：页面方法（如 `page_snapshot`）"执行失败"由一对相连缺陷造成——(1) 读侧 `expires_at`（timestamptz，aware）与 `utc_naive_now()`（naive）相减抛 `TypeError`，异常逃出带日志的 `try` 后被归一成 `tool_failed`，表现为"页面执行成功、模型看到失败、日志无失败行"；(2) 写侧用 naive 值写 timestamptz 列被 asyncpg 按本地时间编码，`expires_at` 读回早 8 小时，等待窗口算成 0 → 立即超时并释放 Future → 页面结果被判为迟到（`no_pending_future`）。修复：读侧 `as_utc()`/`wait_timeout_seconds()` 归一化（并移除 naive 写入助手）、写侧统一 aware UTC、三列 ORM 映射对齐迁移、下发+等待纳入同一异常日志窗口，并新增 `wait_timeout_seconds` / `Host tool wait window already expired` / `Host tool future registered|released` / `pending_keys` / `Tool step failed detail` / `Tool invocation raised` 日志。自动化验证：相关模块 352 passed、1 skipped；全量 681 passed、1 skipped；`ruff` 在改动范围内 `All checks passed!`；两处"旧实现必失败"证据见 `verify.md`。真实容器端到端复跑属未执行项，核对步骤见 `verify.md`。同批次的页面工具预算窗口语义缺陷仍待用户确认修复方案（每次请求重置 vs 滑动窗口）。

2026-09-19 排障增量：宿主工具执行链路补齐关键日志（服务端 `Host tool dispatched/completed/failed/result received/error received/wait timed out/result ignored`、`Tool step completed`，SDK `[xxai-agent][host-tool]`），并把 SDK "执行前工具丢失"的静默返回改为 `host_tool_not_registered` 错误回传。自动化验证：后端相关模块 326 passed、1 skipped；SDK 29 passed（全量 131 passed，1 个既有 `@vue/server-renderer` 缺失用例失败）。已复现并记录一个待确认的预算语义缺陷：页面工具预算窗口从实例首次调用开始计时且不重置，接入方配置 `maxDurationMs: 60_000` 时首次调用 60 秒后所有页面工具调用永久返回 `page_tool_budget_exceeded`；修复方案（每次请求重置 vs 滑动窗口）待用户确认后实施。

2026-09-19 修复增量：页面注册的宿主工具现在会与入口工具一起进入模型 `bind_tools`（`merge_model_tools()`），并新增 `Embed request host tools` / `Model tools bound` 两条关键排障日志；同时修复 Stream 不存在、重放异常与非数字游标导致建连失败的问题。自动化验证：gateway/replay 聚焦用例 24 passed（含修复前必失败的回归用例），gateway+host_tool+embed+conversation 212 passed；真实容器端到端复跑属未执行项，操作步骤见 `verify.md`。

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
