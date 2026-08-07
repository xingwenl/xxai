# Embed 对话接入 MCP 工具验证记录

## 阶段

当前阶段：`verify`。

## 已执行验证

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| MCP、Gateway、Conversation 后端测试 | `cd apps/backend && poetry run pytest tests/mcp tests/gateway tests/conversation -q` | `74 passed, 1 skipped` |
| 后端静态检查 | `cd apps/backend && poetry run ruff check app/modules/mcp app/modules/gateway app/modules/conversation tests/mcp tests/gateway tests/conversation` | `All checks passed` |
| SDK 测试 | `cd apps/ai-sdk && pnpm test -- --run` | `8 files, 33 tests passed` |
| SDK 类型检查 | `cd apps/ai-sdk && pnpm run type-check` | 通过 |
| SDK 构建 | `cd apps/ai-sdk && pnpm run build` | 通过，生成 ESM/UMD/CSS/声明文件 |
| Embed bridge 定向 lint | `cd apps/front && pnpm exec eslint src/features/agent-navigation/agent-navigation-bridge.tsx` | 通过 |
| 迁移升级 | `cd apps/backend && poetry run alembic upgrade head` | 通过，运行 `20260807_0019 -> 20260807_0020` |
| 迁移往返 | `cd apps/backend && poetry run alembic downgrade 20260807_0019 && poetry run alembic upgrade head` | 通过 |
| 迁移最终版本 | `cd apps/backend && poetry run alembic current` | `20260807_0020 (head)` |
| 变更格式检查 | `git diff --check` | 通过 |

## 未通过或未执行项

- `cd apps/front && pnpm run build` 未通过。失败来自既有的 `src/features/agents/index.tsx` React Hook Form/Zod resolver 类型错误，不涉及本次修改的 bridge 文件；bridge 定向 ESLint 已通过。
- 迁移 downgrade 在已有 Embed-only 审计记录时按设计会因恢复 `user_id NOT NULL` 而失败；本次空数据往返已通过，生产回滚前需先按数据保留策略处理记录。

## 人工联调

- 2026-08-07：用户确认当前对话已经可以使用绑定的 MCP 服务，真实 MCP 可用性验收通过。
- 自动化测试已覆盖批准、拒绝、过期和重复 resolve；断线与超时的生产环境行为仍建议持续观察服务端审计终态。

## 变更文件

- 后端：MCP 双主体模型/迁移/服务、Gateway MCP 分流与确认恢复、定向测试。
- SDK：协议和类型、客户端确认状态、默认确认组件与样式、定向测试和公共导出。
- 前端：导航 bridge 移除 `window.confirm` 与非导航自动拒绝。
