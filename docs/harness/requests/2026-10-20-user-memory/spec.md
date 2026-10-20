---
id: 2026-10-20-user-memory
tier: A
risk: medium
approval:
  required: true
  granted: true
  why: ["新建模块目录：记忆的新表与模块边界", "数据模型变化：新增 user_memories 表与「同 key 仅一条有效事实」的约束", "系统提示契约变化：每次请求注入不含内容的记忆索引并新增记忆使用规则", "工具副作用语义变化：新增「本人范围写入」直通审批闸口的白名单"]
---

## 目标与范围

- 做成什么：用户说「我叫李一，记一下」或直接说「我搬到上海了」，模型把这条信息写进**用户记忆**；之后任意会话（任意窗口、任意 Agent）、任何一台设备上问「我叫什么」，模型先查记忆再回答。
- 记忆分两类：**事实**（会变，有有效期，更新时旧值关闭而非抹掉）与**经历**（只追加，带发生时间）。用户的资料文件（简历、合同）不属于记忆，仍归个人知识库。
- **记忆内容不注入上下文**（用户明确要求）：每次请求只注入一行「已有 N 条记忆（事实 x / 经历 y）」与使用规则，不含任何事实值；需要时由模型调用 `memory_search` 取。
- 写入两个入口：用户明确要求（`mode=explicit`，任意 key 任意内容）与模型自动判定（`mode=inferred`，仅限事实类 + 白名单 key + 非敏感类别）。经历类**只能显式写入**。
- 不做：终端用户记忆；从对话后台批量抽取候选；记忆的语义检索（向量）；记忆共享给其他用户；记忆加密；跨平台迁移。

## 来源与方案比较

- **PostgreSQL 18.6 手册 11.8 部分索引**（https://www.postgresql.org/docs/current/indexes-partial.html ，2026-10-20 取用）：带 `WHERE` 子句的唯一索引可以对「行的子集」强制唯一。本设计用它表达「同一用户同一 key 同时只能有一条有效事实」（`WHERE kind='fact' AND valid_until IS NULL`），把覆盖语义交给数据库而不是应用层自觉。
- **方案 A（选中）**：单表 `user_memories`，`kind` 区分事实与经历；注入一行索引；工具按需读取/写入/遗忘。
- **方案 B**：每次请求把全部记忆注入系统提示（我最初的推荐）。实现最简、模型无须判断是否要查，但记忆一旦增长就持续吃 token，且用户明确否决。
- **方案 C**：记忆仍做成知识库的一个特殊库，走 embedding 检索。复用现有管线，但短事实的语义检索命中率不稳定，且改一条事实要重建索引；用户已判断「个人信息不该做成知识库」。
- 选择 A 的理由：在一次请求的 token 成本与「模型知道有记忆可用」之间取折中——只注入元信息，不注入内容；同时保留结构化覆盖语义。

## 被否决的选项

- **全量注入记忆内容**：用户否决；且随条数增长线性吃上下文，与「内容不多」这一前提被打破时最先崩。
- **纯自由文本档案（模型维护一段 Markdown）**：「忘掉我住在哪」无法精确删除，只能让模型重写整段，重写会顺手改掉别的条目；否决。
- **事实与经历分两张表**：查询要两个工具调用，模型更容易漏查；差异只体现在「写入时是否按 key 关闭旧行」，一张表加 `kind` 足够。
- **自动抽取（每轮后台抽取候选，标 pending 等用户确认）**：本期不做。误记是记忆系统的主要伤害来源，自动抽取必须配审核 UI，范围翻倍；且经历类一旦抽错会在时间线上留下假事件。
- **给记忆做向量检索**：几十到两百条的量级下，「全量返回 + 关键词过滤」更确定，也不引入 embedding 维度配置与「检索没命中」这类新失败模式。
- **写入弹工具确认卡**：每句「记一下」都弹一次，体验不可用；改用「本人范围写入」白名单直通，代价靠四件事补偿——写入回显、可删除、可回滚（旧值关闭）、自动写入受白名单与敏感类别约束。
- **`forget` 做软删**：「忘记」若只是打标记，隐私语义上不诚实；删除一律物理删除，只记 id 与时间到日志。
- **无人值守运行写入记忆**：没有在场主体，写进去的是任务配置者的猜测；拒绝。
- **记忆跨用户共享 / 管理员可读内容**：管理者只看条数与更新时间；内容只有本人可读。

## 停点判断

- 架构边界变化：是——新增「用户记忆」这一持久化边界，并改变系统提示的组成（新增索引段与使用规则）。
- 数据模型变化：是——新增 `user_memories` 表与部分唯一索引。
- API 契约变化：是——新增 `/platforms/{pid}/me/memories` 与三个工具的输入契约。
- 鉴权或权限行为变化：是——记忆按本人隔离，管理员只能看元信息，不能读内容。
- 结论：A 档，`approval.required: true`，实现前需用户确认。

## 变更点

- `apps/backend/migrations/versions/20261020_0043_user_memories.py`：建表（`platform_id`/`user_id`/`kind`/`key`/`content`/`occurred_at`/`valid_until`/`source`/`source_conversation_id`）+ `(platform_id, user_id)` 普通索引 + 部分唯一索引 `uq_user_memories_active_fact (platform_id, user_id, key) WHERE kind='fact' AND valid_until IS NULL`；`down_revision='20261019_0042'`。
- 新模块 `apps/backend/app/modules/memory/`：`models.py`（`UserMemory(BaseModel, TimeModel)`，字段全中文 comment）、`schemas.py`、`repositories.py`（`list_active`、`find_active_fact`、`close_fact`、`insert`、`delete`、`count_by_kind`）、`services.py`（写入判定、敏感类别与白名单校验、覆盖逻辑）、`router.py`。
- `apps/backend/app/modules/tools/business/user_memory.py`：三个业务工具——`remember_user_memory`（`side_effect="write"`）、`forget_user_memory`（`side_effect="write"`）、`memory_search`（`side_effect="none"`）；工具描述写明触发时机、`mode` 语义与「不要编造记忆」。
- `apps/backend/app/modules/tools/business/registry.py`：导入注册。
- `apps/backend/app/modules/builtin_tool/services.py`：新增 `SELF_SCOPED_WRITE_TOOLS = frozenset({"remember_user_memory", "forget_user_memory"})`，在审批闸口前直通；附注释说明为什么这类写入不需要确认，并由单测锁定集合内容。
- `apps/backend/app/modules/conversation/runtime.py`：`build_system_prompt` 增 `memory_index: str | None = None` 参数，在 `caller_system_prompt` 之后插入索引段与记忆使用规则；规则写明「涉及用户个人信息、偏好、过往经历时先查记忆」「记忆里没有就说没有记录，不得编造」。
- `apps/backend/app/modules/conversation/services.py`：新增 `build_memory_index_line(...)`（一次 `COUNT ... GROUP BY kind`），在两处 `build_system_prompt` 调用点传入；无人值守路径传 `None`。
- `apps/backend/app/modules/conversation/approval.py`：不需要改；白名单在上游闸口生效，确认裁决器行为不变。
- `apps/backend/app/modules/gateway/router.py`、`apps/backend/app/modules/workflows/*`：`build_system_prompt` 调用点同步新参数（无人值守传 `None`）。
- 前端：`apps/front/src/api/memory.ts`；`apps/front/src/features/my-memory/index.tsx`（列表 + 经历时间线 + 新增/编辑/删除 + 「彻底清空」）；路由 `/ai/my-memory`；侧栏入口。
- 测试：`apps/backend/tests/modules/memory/test_user_memory.py`（覆盖语义、部分唯一索引、敏感拒绝、无人值守拒绝、索引行不含内容）。
- 文档：`docs/adr/0013-user-memory.md`、`CONTEXT.md` 增「用户记忆 / 记忆事实 / 记忆经历」、`docs/CHANGELOG.md`。
- 验证：`tools/harness/verify/2026-10-20-user-memory.sh`。

## 验收标准

1. `alembic upgrade head` 与 `downgrade -1` 均退出 0；同 `(platform_id, user_id, key)` 插入第二条 `valid_until IS NULL` 的事实时报唯一约束冲突。
2. 显式写入闭环：会话 A 里说「我叫李一，记一下」→ 工具以 `mode=explicit` 落库 → 新会话 B 里 `memory_search("姓名")` 返回该事实；`GET /platforms/{pid}/me/memories` 可见。
3. 自动写入闭环：「我搬到上海了」在未说「记住」时以 `mode=inferred` 写入 `城市`，原 `城市=北京` 行 `valid_until` 被置为当前时间，工具返回值回显「已记住：城市 = 上海（原值：北京）」。
4. 敏感拦截：`mode=inferred` 写入健康/财务/证件类内容返回错误码 `memory_sensitive_requires_explicit`，库中无新增行；`mode=explicit` 允许。
5. 无人值守拒绝：无 `user_id` 的运行中调用 `remember_user_memory` 返回 `memory_principal_required`，不落库。
6. 「不注入内容」可测：构造系统提示词，断言其中包含记忆条数且**不包含**任何事实值（用唯一串测试）。
7. `forget_user_memory` 物理删除对应行；`memory_search(include_history=true)` 能返回被覆盖的旧事实及时间区间。
8. 前端 `pnpm --dir apps/front build` 退出 0；记忆页可增删改查；`python3 tools/harness/audit.py` 退出 0。
