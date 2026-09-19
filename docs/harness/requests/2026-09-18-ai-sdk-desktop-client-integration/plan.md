# 实施计划

## 变更文件

### 后端（本仓库，落实 `spec.md` 范围 1、2）

- `apps/backend/app/modules/embed/services.py`：`issue_configured_agent_token` 增加 `agent_id: int | None = None` 与 `host_tool_names: list[str] | None = None`；`agent_id` 缺省回退 `settings.embed_agent_id`，`host_tool_names` 原样透传（与 Embed Client 绑定工具求交集的逻辑已在 `issue_embed_token` 内）。
- `apps/backend/app/modules/shop_agent/schemas.py`：`ShopAgentSessionRequest` 增加 `agent_id`（alias `agentId`，可选，`ge=1`）与 `host_tool_names`（alias `hostToolNames`，默认空列表，`max_length=100`），沿用现有 camelCase alias 风格。
- `apps/backend/app/modules/shop_agent/router.py`：把两个新参数透传进 `issue_configured_agent_token`。
- `apps/backend/app/core/config.py`：新增 `cors_origins: list[str]`，`get_settings()` 读取 `CORS_ORIGINS`（逗号分隔），未配置时使用当前硬编码的四项。
- `apps/backend/app/__init__.py`：`CORSMiddleware` 改用 `settings.cors_origins`。
- `apps/backend/tests/shop_agent/test_session_params.py`（新增）：schema 别名与默认值、`agent_id`/`host_tool_names` 透传、`agent_id` 缺省回退。
- `apps/backend/tests/core/test_cors_config.py`（新增）：默认来源与现状一致、`CORS_ORIGINS` 解析、去重与去尾斜杠。

### 文档（本仓库，落实 `spec.md` 范围 3、4）

- `apps/ai-sdk/README.md`：新增「桌面客户端（Electron）接入」章节（http origin 要求、来源登记与 CORS、主进程换取 token 且不下发登录态 token、`agent_id`/`host_tool_names` 参数、`client_secret` 不下发的说明）。
- `docs/CHANGELOG.md`：记录本次后端参数扩展、CORS 配置化与文档补充。

### 接入方（跨仓，落实 `spec.md` 范围 5）

- `operations-desktop/electron/renderer-server.ts`（新增）：只监听 `127.0.0.1:5390` 的静态文件服务，承载 `dist/renderer`。
- `operations-desktop/electron/renderer-target.ts`：生产目标由 `file://` 改为 `http://127.0.0.1:5390`，dev 仍只信任 `http://127.0.0.1:5190`。
- `operations-desktop/electron/main.ts`：窗口创建前启动静态服务，关闭时释放；注册 agent 相关 IPC。
- `operations-desktop/electron/agent-session-ipc.ts`（新增）：用系统安全存储中的 hua8 token 调 AI Base `POST /api/v1/shop-agent/session?origin=http://127.0.0.1:5390`，携带 `{shopToken, shopUserId, agentId, hostToolNames}`，仅把 `access_token` 返回给渲染层。
- `operations-desktop/electron/agent-tools.ts`（新增）：4 个只读工具的实现，复用既有 workspace/本地任务数据服务。
- `operations-desktop/electron/preload.cjs`、`operations-desktop/src/shared/agent-ipc.ts`（新增）：暴露 `agent.session()` 与 4 个只读查询通道。
- `operations-desktop/src/components/AgentChatPanel.tsx`（新增）、`operations-desktop/src/App.tsx`：在右侧助手区以 `ui.mode: 'embedded'` 挂载 SDK，注册 4 个只读工具。
- `operations-desktop/tests/*`（新增）：静态服务、IPC 参数组装、工具只读约束的单测。

### 首批只读工具定义（需与后台策略 `input_schema` 指纹一致）

| 名称 | 入参 schema | 返回 | 副作用 |
|---|---|---|---|
| `get_current_shop` | `{type: object, properties: {}, additionalProperties: false}` | 当前选中店铺的基础信息与登录态状态 | `none` |
| `list_shops` | `{type: object, properties: {keyword: {type: string}, limit: {type: integer}}, additionalProperties: false}` | 当前租户店铺列表（可按关键词过滤） | `none` |
| `get_session_health` | `{type: object, properties: {platform: {type: string}}, additionalProperties: false}` | 登录态健康统计与异常店铺 | `none` |
| `list_local_tasks` | `{type: object, properties: {status: {type: string}, limit: {type: integer}}, additionalProperties: false}` | 本地采集/同步任务状态列表 | `none` |

## 实施步骤

1. 后端参数扩展：先改 `issue_configured_agent_token`（保持默认行为不变），再改 `shop_agent` schema 与 router。
2. 补 `apps/backend/tests/shop_agent/test_session_params.py`，覆盖 schema 别名、默认值、透传与回退。
3. CORS 配置化：改 `core/config.py` 与 `app/__init__.py`，默认值逐条对齐现状。
4. 补 `apps/backend/tests/core/test_cors_config.py`。
5. 执行后端相关测试与全量测试。
6. 写 `apps/ai-sdk/README.md` 桌面客户端章节，更新 `docs/CHANGELOG.md`。
7. 接入方：先落地静态服务与加载链路改造，跑 `npm run typecheck`、`npm test`、`npm run build`，确认窗口可正常加载、导航行为不变。
8. 接入方：落地 agent IPC、渲染层面板与 4 个只读工具，补单测后重跑校验命令。
9. 真机联调（需要人工准备环境）：后台创建 Agent、绑定 Embed Client、把 4 个工具策略绑定到 Agent 与 Client、将桌面 origin 加入 `allowed_origins`、配置 `STORE_OPS_BASE_URL`/`EMBED_*` 环境变量；随后在 Electron 中完成一轮问答并触发店铺工具与只读桌面工具。
10. 更新 `verify.md`、`acceptance.md`、`meta.json`。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/shop_agent tests/embed tests/gateway tests/core -q`：预期新增与既有测试全部通过。
- `cd apps/backend && poetry run pytest -q`：预期全量通过（记录耗时与环境限制）。
- `cd apps/ai-sdk && npm run type-check`：未改 SDK 源码，作为回归确认。
- `cd /Users/lixingwen/xw/zhoudan/client/operations-desktop && npm run typecheck`：预期通过。
- `cd /Users/lixingwen/xw/zhoudan/client/operations-desktop && npm test`：预期新增单测与既有测试通过。
- 真机联调：Electron 中确认窗口以 `http://127.0.0.1:5390` 加载、完成一轮问答、触发 `store_ops_query` 与至少一个只读桌面工具；当前环境若缺少 AI Base 运行实例或 hua8 账号，需如实记录为未执行项并说明解除条件。

## 回滚说明

- 后端：全部为增量改动（两个可选参数 + 一个配置项），回滚即还原文件；`agent_id` 缺省回退与 `host_tool_names` 缺省空列表保证既有调用方（`apps/shop`）行为不变。
- CORS：删除 `CORS_ORIGINS` 配置即回到默认四项，不影响既有来源。
- 接入方：还原 `renderer-target.ts` 与 `main.ts` 的加载方式即可回到 `file://`，代价是 AI 面板不可用；静态服务与 IPC 均为新增文件，删除即回滚。
- 需要特别关注：接入方加载链路属应用启动关键路径，回滚后需确认窗口仍能正常加载与导航。

## 人工确认点

- 已完成：`spec.md` 第 2 次变更（`agent_id` + `host_tool_names` 扩参、CORS 配置化、首批只读工具范围为 4 个）经用户于 2026-09-18 确认。
- 实施中需要人工/后台操作的步骤：
  - AI Base 后台：创建桌面端 Agent、绑定 Embed Client、创建并绑定 4 个宿主工具策略（`input_schema` 必须与前端注册指纹一致）。
  - 部署配置：把桌面 origin `http://127.0.0.1:5390` 加入该 Embed Client 的 `allowed_origins`；确认 `STORE_OPS_BASE_URL`、`EMBED_CLIENT_ID`/`EMBED_CLIENT_SECRET`/`EMBED_AGENT_ID`/`EMBED_ORIGIN` 已配置。
  - 真机联调需要可用的 AI Base 环境与 hua8 账号。
