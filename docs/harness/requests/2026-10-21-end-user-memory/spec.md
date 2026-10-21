---
id: 2026-10-21-end-user-memory
tier: A
risk: medium
approval:
  required: true
  granted: true
  why: ["数据模型变化：user_memories 增加终端用户主体列并重建唯一索引", "鉴权行为变化：Embed token 增加可选的签发者后台用户声明", "架构边界变化：记忆主体从「后台用户」扩展为「后台用户或终端用户」", "工具语义变化：记忆工具在端用户会话从一律拒绝改为按主体读写"]
---

## 目标与范围

- 做成什么：后台内嵌助手（AI-SDK 浮动助手）里说「我叫李一，记一下」「我搬到上海了」时，记忆真的落库、下个会话能查回来；接入方页面（Embed SDK）的终端访客同样能拥有自己的记忆。
- 记忆主体（谁拥有这条记忆）分两种，落在同一张 `user_memories` 表：
  - **后台用户主体**：受信任入口 `GET /embed/agent-token` 签发的 token 带 `user_id` 声明，运行时据此按 `sys_users.id` 记录；管理台「我的记忆」页与 REST 口径不变，刚记的东西立刻可见。
  - **终端用户主体**：公开入口 `POST /embed/tokens` 签发的 token 不带后台身份，按 `(platform_embed_clients.client_id, platform_end_users.id)` 记录；同一 Client 的不同访客互相隔离，同一访客在两个 Client 下的记忆也互相隔离。
- 端用户会话的系统提示补一行「已有 N 条记忆（事实 x / 经历 y）」，只有条数、不含内容（沿用 ADR 0013 的注入口径）。
- 不做：端用户记忆在管理台列表 / 导出 / 检索页展示；端用户记忆跨 Client 共享；记忆共享给他人；向量检索；改 AI-SDK 线协议（token 换发、重连流程不变）；把 Embed 会话的 `conversations.user_id` 补填成后台用户。

## 来源与方案比较

- **LangChain LangGraph Stores 文档**（https://docs.langchain.com/oss/python/langgraph/stores ，调研 2026-10-21）：长期记忆存在 Store 中，键由「命名空间元组 + key」组成，官方示例用 `("memories", user_id)` 一类前缀表达归属；不同命名空间天然不可见。本设计对应为「主体列 + 平台/Client 作用域」的 SQL 版命名空间。
- **Mem0 增强元数据过滤**（https://docs.mem0.ai/open-source/features/metadata-filtering ，调研 2026-10-21）：记忆写入时携带 `user_id` / `agent_id` 等元数据，检索按元数据精确过滤，而不是把所有记忆放在一个池子里靠语义碰运气。对应到本设计：主体列参与唯一索引与查询条件，隔离由数据库条件保证。
- **PostgreSQL 18 部分索引**（https://www.postgresql.org/docs/current/indexes-partial.html ，沿用 ADR 0013 的引用）：`WHERE` 子句可以让唯一约束只作用于行的子集，用来表达「同一主体同一 key 只有一条有效事实」。
- 方案 A（选中）：`user_memories` 保留 `user_id` 并新增 `client_id` + `end_user_id`（外键到 `platform_end_users`，删除级联），用 CHECK 约束保证「主体恰好一种」，唯一索引按主体类型拆成两条部分唯一索引；后台入口用 token 里的 `user_id` 声明决定落哪种主体。
- 方案 B：多态主体列 `principal_type` + `principal_id`（会话控制台已有同款表达）。列更少，但 `principal_id` 无法同时外键到两张表，删用户 / 删端用户 / 删 Client 后会留下读不到也删不掉的孤儿记忆，与 ADR 0013「忘记即物理删除」的隐私口径冲突。
- 方案 C：只给带 `user_id` 声明的 token 记忆能力，终端访客继续拒绝。改动最小（只有 token 声明 + 运行时透传，无迁移），但满足不了「接入方访客也要有记忆」，且用户已明确选择 Client + 终端用户隔离。
- 选择 A 的理由：后台入口保住「管理台可见」，第三方入口拿到 Client 级隔离；两种主体共享同一套写入校验与索引语义，工具层只多一个「主体从哪来」的判断。

## 被否决的选项

- **纯 Client 级记忆（一个 Client 共用一份）**：同一 Client 下所有访客共享，甲问「我叫什么」会查出乙的姓名；隐私事故，否决。
- **只做 token 声明（方案 C）**：终端访客记不住，接入方要自己想办法存；否决。
- **多态主体列（方案 B）**：无外键、孤儿记忆无法清理；否决。
- **端用户记忆进管理台**：ADR 0013 已定「管理者只看条数与更新时间，内容只有本人可读」；端用户没有后台账号，做展示等于让平台管理员读第三方访客的隐私；本期不做。
- **给 Client 加 `allow_end_user_memory` 开关**：记忆工具是否可用已由 Agent 的 `builtin_tools` 配置决定，再叠一层开关会让「为什么记不住」更难排查；不加。
- **把记忆表按 Client 拆表 / 拆库**：迁移与查询双重复杂度，隔离靠索引条件已经够用；否决。
- **Embed 会话补填 `conversations.user_id`**：会话控制台按 `principal_type='end_user'` 展示是对的，改了反而把第三方访客标成后台用户；否决。

## 停点判断

- 架构边界变化：是——记忆主体从「后台用户」扩为「后台用户或终端用户」，工具与系统提示的语义随之变化。
- 数据模型变化：是——`user_memories` 加列、改唯一索引、加 CHECK 约束。
- API 契约变化：是——Embed token 新增可选 `user_id` 声明（线协议字段级可见）；工具入参不变。
- 鉴权或权限行为变化：是——受信任入口把后台身份带给端侧运行时，必须只在服务端签发路径设置，且被工具层按主体消费。
- 结论：A 档，`approval.required: true`，实现前需用户确认。

## 变更点

- `apps/backend/app/modules/memory/models.py`：`UserMemory.user_id` 改可空；新增 `client_id`（String(80)，指向 `platform_embed_clients.client_id`）与 `end_user_id`（FK `platform_end_users.id`，`ondelete=CASCADE`）；CHECK「主体恰好一种」；唯一索引拆为 `uq_user_memories_active_fact`（仅 `user_id` 非空的行）与 `uq_user_memories_active_end_user_fact`（仅 `end_user_id` 非空的行）。
- 新增 `apps/backend/migrations/versions/20261021_0046_end_user_memory.py`（`down_revision='20261021_0045'`）：加列、去 `user_id` 的 NOT NULL、重建两条部分唯一索引、加 CHECK；`downgrade` 反向并说明不可逆点。
- `apps/backend/app/modules/memory/principal.py`：新增 `MemoryPrincipal`（`user` / `end_user` 两个构造），承载 `platform_id`、`user_id`、`client_id`、`end_user_id`。
- `apps/backend/app/modules/memory/repositories.py`、`services.py`、`router.py`：读写与统计接口改收 `MemoryPrincipal`，REST 路由固定传 `MemoryPrincipal.user(...)`。
- `apps/backend/app/modules/tools/business/framework.py`：`BusinessToolContext` 增 `client_id: str | None = None`。
- `apps/backend/app/modules/tools/business/user_memory.py`：`_require_principal(ctx)` 返回 `MemoryPrincipal`——`ctx.user_id` 优先，其次 `ctx.client_id` + `ctx.platform_end_user_id`；都缺失时仍抛 `memory_principal_required`，无人值守仍拒绝。
- `apps/backend/app/modules/builtin_tool/services.py`：`invoke_builtin_tool` 增 `client_id` 参数并写入上下文。
- `apps/backend/app/modules/gateway/dispatcher.py`：`RuntimeToolDispatcher` 增 `user_id` / `client_id`，工具调用时透传。
- `apps/backend/app/modules/gateway/runtime.py`：新增 `resolve_embed_memory_principal` 与 `load_embed_memory_index`；`stream_embed_chat` 增 `client_id` / `user_id`，按主体拼 `memory_index` 传入 `build_system_prompt`（只含条数）。
- `apps/backend/app/modules/gateway/router.py`：Embed WS 从 token 声明取 `user_id` 与 `client_id`，传给 dispatcher 与 `stream_embed_chat`。
- `apps/backend/app/modules/embed/security.py`：`create_embed_token` 增可选 `user_id` 声明；`decode_embed_token` 校验其存在时必须是整数（否则 `invalid embed token`）。
- `apps/backend/app/modules/embed/services.py`、`router.py`：`issue_embed_token` / `issue_configured_agent_token` 增透传参数；仅 `GET /embed/agent-token` 传 `current_user.id`，公开 `POST /embed/tokens` 不传。
- `apps/backend/app/modules/memory/services.py`：新增 `load_memory_index_line_for_principal`，保留 `load_memory_index_line(platform_id, user_id)` 作为后台用户主体的薄包装——`conversation/services.py` 与 REST 对话代码不动，行为不变。
- 测试：`apps/backend/tests/memory/test_user_memory.py` 增主体校验、双 Client / 双访客隔离、端用户索引行、端用户免确认写入用例；`apps/backend/tests/embed/test_client_services.py` 增「受信任入口带 `user_id`、公开入口不带」与「坏 `user_id` 声明被拒」；新增 `apps/backend/tests/gateway/test_embed_memory_principal.py` 断言主体解析口径。
- 文档：`docs/adr/0016-end-user-memory.md`、`CONTEXT.md` 增「记忆主体 / 端用户记忆」、`docs/CHANGELOG.md`；验证脚本 `tools/harness/verify/2026-10-21-end-user-memory.sh`（静态断言 + pytest + 迁移真机升降级）。

## 验收标准

1. 后台入口（`GET /embed/agent-token`）签发的 token 带 `user_id` 声明；浮动助手说「我叫李一」后 `user_memories` 出现 `user_id=1` 的行，管理台 `/ai/my-memory` 可见。
2. 公开入口（`POST /embed/tokens`）签发的 token 不带 `user_id` 声明；同一 Client 下终端访客写记忆落 `(client_id, end_user_id)` 行。
3. 同一 `external_user_id` 在两个 Client 下的记忆互相查不到；同一 Client 下两个终端访客互相查不到。
4. 端用户会话的系统提示含「已有 N 条记忆」索引行且不含任何事实内容；无人值守运行仍返回 `memory_principal_required`。
5. 迁移 `upgrade → downgrade → upgrade` 通过；存量后台用户记忆在迁移后仍满足「同 key 一条有效事实」。
6. 现有 REST 记忆接口与 `/ai/my-memory` 页面行为不变（仍只读写后台用户主体）。
7. `pytest` 全绿，`alembic heads` 单头；AI-SDK 与管理台前端本次无需改代码。
