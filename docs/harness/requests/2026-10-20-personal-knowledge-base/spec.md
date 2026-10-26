---
id: 2026-10-20-personal-knowledge-base
tier: A
risk: medium
status: cancelled
approval:
  required: true
  granted: false
  why: ["数据模型变化：knowledge_bases 增属主列与 embedding 模型引用", "鉴权或权限行为变化：检索边界从「Agent 绑定」扩展为「Agent 绑定 ∪ 会话主体本人」", "API 契约变化：新增个人库管理入口与管理员读取入口"]
---

> **状态：已取消（2026-10-26）**——方案评审完成但未获批准（`approval.granted: false`）也未实施，本文件与 `docs/adr/0012-personal-knowledge-base.md` 仅作为设计记录保留。`tools/harness/audit.py` 对 `status: cancelled` 的 request 跳过产物校验。

  required: true
  granted: false
  why: ["数据模型变化：knowledge_bases 增属主列与 embedding 模型引用", "鉴权或权限行为变化：检索边界从「Agent 绑定」扩展为「Agent 绑定 ∪ 会话主体本人」", "API 契约变化：新增个人库管理入口与管理员读取入口"]
---

## 目标与范围

- 做成什么：后台登录用户可以在「我的知识库」里建库、上传文档（复用既有 txt/md/pdf/docx 入库管线），该库**不绑定 Agent**，只在该用户作为会话主体的对话中自动参与检索；平台公共知识库的行为一字不改。
- 给谁用：后台登录用户（`sys_users`，当前就是 `platform_admins` 成员）。
- **本期隔离的真实边界**：现在能登录后台并对话的人本身就是平台管理员，所以本期个人库隔离的是「同一平台内不同成员」，不是「平台运营方看不到用户内容」——后者要等终端用户（`platform_end_users`）侧接入，本期只留扩展点。
- 不做：终端用户的个人库；个人库内容加密；通用审计表；从对话自动抽取长期记忆；个人库跨平台共享；检索结果里区分「公共/个人」来源的展示；修改公共库的任何语义。

## 来源与方案比较

- **PostgreSQL 18.6 手册 5.9 行级安全策略**（https://www.postgresql.org/docs/current/ddl-rowsecurity.html ，2026-10-20 取用）：两条可直接借鉴的性质——可见性必须表达成「查询条件本身」，以及「未声明策略即默认拒绝」。本设计把后者落实为：调用方漏传会话主体时，检索退化为「只有公共库」，而不是「全部库」。
- **方案 A（选中）**：`knowledge_bases` 单表加 `owner_type`/`owner_user_id`，取库收敛成一个仓储方法，由 SQL 选出「Agent 绑定的公共库 + 主体本人的个人库」。收益：文档、分块、入库任务、引用构造全部零改动。
- **方案 B**：个人库另立表族（`personal_knowledge_bases` + `_documents` + `_chunks`）。隔离最直观、查询无需过滤，但入库与检索管线要复制一套并长期双写；本平台个人库量级只有「每平台几十成员 × 每人几库」，收益抵不上维护成本。
- **方案 C**：不建库，把个人信息做成「用户档案」一段文本注入系统提示。零基础设施，但只能承载几百字、无法上传文件、无法追溯引用来源。
- 选择 A 的理由：复用成本最低且失败安全方向正确；`owner_type` 枚举同时为将来的 `end_user` 留了同一扩展点。

## 被否决的选项

- **个人库仍按普通库绑定到 Agent、靠约定不绑公共 Agent**：一次误配就是「跟这个 Agent 说话的所有人都能检索到我的资料」，且不会报错；否决。
- **为个人库另立表族（方案 B 的实现）**：见「来源与方案比较」；否决。
- **属主复用 `platform_end_users`（一步到位支持终端用户）**：需要同时新建 embed 侧管理接口与鉴权，范围翻倍，本期又没有终端用户要管理知识库；否决，仅保留 `owner_type` 扩展点。
- **每人自填 embedding 的 model/base_url/api_key**：成员被迫各自持有模型密钥，密钥散落且维度靠手填；改为引用 `platform_models` 里 `model_type='embedding'` 的条目，建库时后端探测一次维度落库。
- **检索时先取全部库、再在应用层按属主过滤**：漏改一处调用点就泄漏，且无法用 SQL 保证；否决，过滤下压到仓储层。
- **个人库内容加密存储**：在「平台管理员可读全部内容」的产品前提下，加密不带来隐私收益；否决。
- **无人值守运行（任务/工作流）注入发起人的个人库**：无人值守没有「在场的人」，注入某人的资料等于把私人内容交给定时任务；一律只检索公共库。
- **本轮顺带做长期记忆（自动抽取事实入库）**：会与「用户主动放的资料」抢同一个库，且需要抽取/去重/遗忘策略；另立请求。

## 停点判断

- 架构边界变化：是——知识库管理面从「纯平台级」变为「平台级 + 个人级」，检索边界引入会话主体维度。
- 数据模型变化：是——`knowledge_bases` 增 3 列与 1 条 CHECK 约束。
- API 契约变化：是——新增个人库 CRUD 与管理端读取接口。
- 鉴权或权限行为变化：是——检索与文档访问都要按属主判定。
- 结论：A 档，`approval.required: true`，实现前需用户确认。

## 变更点

- `apps/backend/app/modules/knowledge/models.py`：`KnowledgeBase` 增 `owner_type`（`platform`/`user`）、`owner_user_id`（FK `sys_users.id`，SET NULL）、`embedding_model_id`（FK `platform_models.id`，SET NULL）与 CHECK 约束（`owner_type='user'` 等价于 `owner_user_id IS NOT NULL`）；三个字段都写中文 comment。
- `apps/backend/migrations/versions/20261020_0043_personal_knowledge_bases.py`：加列 + 存量行回填 `owner_type='platform'` + 索引与 CHECK；`down_revision='20261019_0042'`。
- `apps/backend/app/modules/knowledge/repositories.py`：新增 `list_effective_for_agent_and_owner(agent_id, platform_id, *, owner_user_id)` 作为唯一取库入口、`list_owned_by(platform_id, user_id)`；`get_base` 增属主校验分支；`list_bases` 强制 `owner_type='platform'`。
- `apps/backend/app/modules/knowledge/runtime.py`：`build_embedding_model` 支持从 `embedding_model_id` 解析 `platform_models`（模型名/地址/解密密钥），未引用时回落现有内联字段。
- `apps/backend/app/modules/knowledge/services.py`：新增 `probe_embedding_dimension(model)`，建库时调用一次 embedding 取向量长度。
- `apps/backend/app/modules/knowledge/router.py`：新增 `/platforms/{pid}/me/knowledge-bases` 的 GET/POST/PATCH/DELETE（属主强制取 `current_user.id`）；文档子资源复用现有端点，由 `get_base` 按属主校验（非属主 404）；新增管理员只读入口 `/platforms/{pid}/knowledge-bases/owned-by-users`。
- `apps/backend/app/modules/knowledge/schemas.py`：`KnowledgeBaseRead` 增 `owner_type`/`owner_user_id`；`KnowledgeBaseCreate` 增 `embedding_model_id`（个人库必填，公共库可选）。
- `apps/backend/app/modules/conversation/runtime.py`：`load_runtime_context` 增关键字参数 `owner_user_id`，改用 `list_effective_for_agent_and_owner`；6 处调用点按会话行填 `conversations.user_id`，无人值守路径传 `None`。
- `apps/backend/app/modules/conversation/services.py`：`retrieve_citations` 的 query embedding 按 `(embedding_model_id, embedding_model, embedding_base_url)` 分组复用，去掉逐库重复调用。
- `apps/backend/app/modules/tools/business/knowledge_search.py`：改用同一取库方法，主体取 `ctx.user_id`（`BusinessToolContext` 已有该字段）。
- `apps/backend/app/modules/gateway/router.py`：`load_runtime_context` 调用处传入会话主体。
- 前端：`apps/front/src/api/knowledge.ts` 增个人库接口与类型；`apps/front/src/features/knowledge/` 抽出可复用的列表/新建/上传组件；新增 `apps/front/src/features/my-knowledge/index.tsx`、路由 `/ai/my-knowledge` 与侧栏入口；`agent-knowledge-tab.tsx` 只列公共库。
- 文档：`CONTEXT.md` 增「知识库 / 公共知识库 / 个人知识库 / 会话主体」四个术语；新增 `docs/adr/0012-personal-knowledge-base.md`；更新 `docs/CHANGELOG.md`。
- 验证：`tools/harness/verify/2026-10-20-personal-knowledge-base.sh`。

## 验收标准

1. `alembic upgrade head` 与 `downgrade -1` 均退出 0；升级后存量库 `owner_type='platform'` 且 `owner_user_id IS NULL`，CHECK 约束在库中存在。
2. 个人库无法绑定：对个人库调用 `PUT /platforms/{pid}/knowledge-bases/{id}/agents/{agent_id}` 返回 400，`agent_knowledge_bases` 不新增行。
3. 检索隔离（pytest + 真实输出）：成员 A 的个人库里有含唯一串的文档，成员 B 与同一 Agent 的会话检索结果不含该串，A 的会话检索结果含该串。
4. 无人值守路径（`owner_user_id=None`）只返回公共库；该断言以单元测试覆盖。
5. `GET /platforms/{pid}/knowledge-bases` 不返回任何个人库；管理员只读入口能列出并读取他人个人库的文档内容。
6. 前端 `pnpm --dir apps/front build` 退出 0；`/ai/my-knowledge` 可新建库、上传 txt 文档、删除库；`python3 tools/harness/audit.py` 退出 0。
7. 公共库回归：`apps/backend/tests` 中知识库与会话相关用例全绿（记录用例数与耗时）。
