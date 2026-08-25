# 实施计划

## 变更文件

### 后端

- `apps/backend/app/modules/gateway/router.py`：
  - 新增模块级 `build_session_info(payload, *, agent_id, settings, quota_service, session_factory)` 与配额快照辅助函数，负责查询 client/agent、组装 `quota`，任一段失败返回 `null` 且不抛异常；
  - `agent_websocket` 在发送 `session_ready` 前调用该函数，把 `client`/`agent`/`quota` 并入 payload。
- `apps/backend/tests/gateway/test_session_info.py`（新增）：
  - payload 组装正确性（client/agent/quota 各字段）；
  - `quota_service is None` 时 `quota` 为 `null`；
  - Redis/DB 异常时对应段为 `null` 且不抛异常；
  - `token_issue.limit` 回退到 `settings.quota_token_issue_limit`。

### SDK（apps/ai-sdk）

- `src/core/types.ts`：新增 `EmbedClientInfo`、`AgentInfo`、`QuotaResourceUsage`、`QuotaUsage`。
- `src/core/client.ts`：`session_ready` 分支解析保存三组信息；新增 `clientInfo`/`agentInfo`/`quota` getter；新增 `client_info` 事件。
- `src/ui/header-name.ts`（新增）：导出 `resolveHeaderName(clientName?: string, title?: string)` 纯函数。
- `src/ui/components/ChatWidget.vue`：`.xxai-header-name` 改为 `resolveHeaderName(agent.clientInfo?.name, title)`。
- `src/ui/__tests__/header-name.test.ts`（新增）：client 名称优先、缺失回退、均为空时回退默认值的用例。
- `src/core/__tests__/client.test.ts`：新增 `session_ready` 解析与 `client_info` 事件用例。

### SDK UI 展示形态（增量）

- `src/ui/components/QuotaRing.vue`（新增）：SVG 圆形进度条，`limit`/`current` props，中心文本 `已用/限额`，三色状态，`title` 提示窗口语义。
- `src/ui/quota-ring.ts`（新增）：`quotaRingState(current, limit)` 纯函数（ratio/color/text，limit 缺失或 `<=0` 返回 null）。
- `src/ui/components/ChatMessageList.vue`：新增空状态（`agentName`/`agentDescription` props，无消息时居中展示）。
- `src/ui/components/ChatWidget.vue`：头部右侧挂载 `QuotaRing`（数据源 `agent.quota?.resources?.message`），向消息列表透传 agent 名称/描述。`2026-08-24` 用户注释停用 QuotaRing 展示（组件保留，可恢复）。
- `src/ui/__tests__/quota-ring.test.ts`（新增）：`quotaRingState` 的比例、颜色阈值、文本与非法 limit 用例。

### 文档

- `docs/harness/requests/2026-08-24-ai-sdk-session-info/`：`research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 实施步骤

1. 后端：实现 `build_session_info` 与配额快照组装（含 `token_issue` 的 limit 回退与无 end_user 维度），接入 `agent_websocket` 的 `session_ready`。
2. 后端：新增 `tests/gateway/test_session_info.py`（FakeClient/FakeAgent/FakeRedis 风格，参照 `tests/embed/test_client_services.py` 与 `tests/gateway/test_quota_gateway.py`）。
3. SDK 类型与客户端：`types.ts` 新增类型；`client.ts` 解析保存 + getter + `client_info` 事件。
4. SDK UI：`header-name.ts` 纯函数 + `ChatWidget.vue` 头部回退。
5. SDK 测试：解析/事件用例与 `resolveHeaderName` 回退用例。
6. SDK UI 增量：`quota-ring.ts` 纯函数 + `QuotaRing.vue` + `ChatMessageList` 空状态 + `ChatWidget` 挂载与透传。
7. 运行测试与格式化，记录真实结果到 `verify.md`。

## 测试步骤

- 后端：`cd apps/backend && poetry run pytest tests/gateway/test_session_info.py -q`，预期新增用例全部通过；再跑 `poetry run pytest tests/gateway tests/quota -q` 确认不回归；`poetry run ruff check` 相关文件。
- SDK：`cd apps/ai-sdk && pnpm test -- --run`（或仓库既有 SDK 测试命令）、`pnpm type-check`、`pnpm build`。
- 手工验证（可选）：本地起后端 + 前端，打开聊天窗口，确认头部显示后台配置的 client 名称。

## 回滚说明

- 后端：回滚 `router.py` 的 `build_session_info` 与 `session_ready` payload 改动即可；`session_ready` 恢复为原字段集合，旧客户端与新客户端均兼容（新客户端缺少字段时回退）。
- SDK：回滚 `types.ts`/`client.ts`/`header-name.ts`/`ChatWidget.vue` 与测试文件。
- 关注点：`quota` 快照仅为展示，不参与网关拦截；删除字段不会影响既有配额拦截逻辑。

## 人工确认点

- 必须：API 契约变化（`session_ready` 新增 `client`/`agent`/`quota` 字段）——用户已确认方案 A 与 payload 设计（2026-08-24 设计确认稿），spec 定稿后仍需用户在 `meta.json` 记录明确批准后进入实现。
- 无需：架构边界、数据模型、鉴权权限（见 `spec.md` 停点判断）。
