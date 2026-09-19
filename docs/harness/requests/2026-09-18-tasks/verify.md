# 验证记录

验证时间：2026-09-19（第 2、3 次变更追加于同日）
验证环境：本机 monorepo 工作区；后端 `.venv`（Python 3.12.4）；PostgreSQL 17（容器 `ai-base-db-1`，pgvector 镜像）；前端 Node + pnpm。

## 第 3 次变更（fix：手动运行永不执行 + 执行过程不可见）验证

| 项目 | 结果 |
|---|---|
| 后端全量测试 | **761 passed / 1 skipped** |
| 新增回归测试 | 8 个（调度认领 3 + 详情接口/组装 5） |
| 反向验证（回退修复后新用例必须失败） | **通过**（2 个用例确实失败） |
| 真实路径端到端（接口入队 → 认领 → 执行） | **通过**（见 §13.2） |
| 用真实数据读出执行过程 | **通过**（见 §13.4） |
| 前端 build（含 tsc） | 通过 |
| Ruff（本次改动文件） | All checks passed |

### 13.1 缺陷复现与根因

用户反馈「立即运行一次」报 `执行超时：超过 600 秒仍未结束，由看门狗标记失败`。
真实数据（`task_runs`）显示该记录的 `conversation_id` 与 `agent_loop_run_id` **均为空**：

```
 id | trigger_kind | status | conversation_id | agent_loop_run_id |              err
  8 | manual       | failed |                 |                   | 执行超时：超过 600 秒仍未结束，由看门狗标记失败
```

对照实验（修复前）：

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/diag.py
```

- 修复前实际结果：`scheduler tick dispatched run ids: []`——手动 run **不被派发**，
  `status` 停留 `running`，最终只能被看门狗判超时。
- 对照（`scheduled` 路径修复前即正常）：`scheduled path dispatched: [12]`。

根因：调度器只派发自己在本 tick 内创建的记录（`pending.append(run.id)`），
而 `enqueue_manual_run` 只写记录不派发，导致该记录无人认领。

### 13.2 修复后的真实路径端到端

按线上真实顺序调用（接口入队 → 调度器 tick 认领 → 执行），不绕过任何一步：

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/e2e_manual_real.py
```

- 预期：手动 run 被认领并真正执行，产生会话与 `completed` 记录。
- 实际：

```
[1] 接口入队: run=14 started=True started_at=None
[2] 调度器认领: [14]
[3] 执行结果: run=14 status=completed
[4] 终态: status=completed conv=349 loop=488 err=None
      [user] 请只回复四个字：巡检完成。不要调用任何工具。
      [assistant] 巡检完成。

RESULT: PASS 手动运行真正被执行
```

### 13.3 回归测试的有效性（反向验证）

为避免写出「恒真」的测试，临时回退修复后确认新用例确实失败：

```
已临时回退修复
FAILED tests/tasks/test_scheduler.py::test_manual_run_is_claimed_and_dispatched
FAILED tests/tasks/test_scheduler.py::test_queued_run_from_restart_is_claimed
2 failed, 7 deselected
```

恢复修复后：`tests/tasks` → `64 passed`。

### 13.4 执行过程可读（用真实数据）

用户那次任务创建的执行过程完整存在于 `agent_loop_steps`，通过
`task_runs.agent_loop_run_id` 关联即可读出：

```
loop 487 status: completed | steps: 7
  # 1 knowledge_retrieval  succeeded  tool=-              out=未命中知识库引用
  # 2 skill_instruction    succeeded  tool=-              out=技能元数据已加载，可调用脚本工具
  # 5 skill_instruction    succeeded  tool=-              out=技能元数据已加载
  # 7 builtin_tool         succeeded  tool=create_task    out=工具执行完成：{"kind":"create_task","task":{"id":
  # 8 model_generation     succeeded  tool=-              out=生成 348 字符
```

该 loop 归属会话 348（`platform_end_user_id=2`），标题即用户当时的请求
「帮我创建个定时任务 ，每天6点 为我收集头条新闻前十条」——即第 2 次变更修复后的
Embed 链路创建任务确实执行成功，且全过程可追溯。

新增接口 `GET /tasks/{task_id}/runs/{run_id}/detail` 组装结果（真实数据验证）：

```
loop_id: 488 | status: completed | steps: 3
  #1 knowledge_retrieval  succeeded  tool=- out=未命中知识库引用
  #2 skill_instruction    succeeded  tool=- out=技能元数据已加载
  #3 model_generation     succeeded  tool=- out=生成 5 字符

RESULT: PASS 执行过程可读
```

### 13.5 新增测试

| 文件 | 新增用例 |
|---|---|
| `tests/tasks/test_scheduler.py` | `test_manual_run_is_claimed_and_dispatched`、`test_queued_run_from_restart_is_claimed`、`test_already_started_run_is_not_reclaimed` |
| `tests/tasks/test_task_routes.py` | `test_run_detail_endpoint_is_registered`、`test_run_detail_schema_exposes_steps` |
| `tests/tasks/test_task_services.py` | `test_get_run_detail_returns_steps`、`test_get_run_detail_empty_when_never_executed`、`test_get_run_detail_rejects_other_task_run` |

后端全量由 753 增至 **761 passed**。

### 13.6 关于用户已存在的脏数据

`run 8` / `run 10`（均 `manual`）在修复前已被看门狗标记为 `failed`，属终态。
修复后的自动认领只对「仍为 `running` 且 `started_at IS NULL`」的记录生效，
因此不会复活这些终态记录（终态不复活是预期行为）。这两条记录如实反映了
修复前的缺陷，保留作为证据。

## 第 2 次变更（fix：Embed 链路无法创建任务）验证

| 项目 | 结果 |
|---|---|
| 后端全量测试 | **753 passed / 1 skipped** |
| 迁移 `20260919_0035` 升级/回滚往返 | 通过，head = `20260919_0035` |
| 新列与注释落库 | 通过（`run_as_end_user_id` 及两列注释已更新） |
| Embed 链路端到端创建 + 执行 | **通过**（见 §12） |
| Ruff（本次改动文件） | All checks passed |

### 12.1 复现与修复确认

用户报告：在 Embed/AI SDK 链路让智能体创建定时任务，工具返回 `task_requires_user_identity`。

根因确认：`gateway/dispatcher.py:145-155` 调用 `invoke_builtin_tool` 时只传 `platform_end_user_id`，从不传后台 `user_id`；而原 `create_task` 实现要求 `ctx.user_id` 非空，因此在 Embed 链路必然失败。

修复后用真实 Postgres 端到端验证（模拟 Embed 上下文的 `BusinessToolContext`，`user_id=None`、`platform_end_user_id=1`）：

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/e2e_embed_task.py
```

- 预期：任务创建成功、以终端用户身份执行、跑完一轮并回写 `completed`。
- 实际：

```
end_user: 1 platform: 1
created: 9 | owner: None | run_as_type: end_user | run_as_user: None | run_as_end_user: 1
claimed: [9]
runner status: completed
run: completed | conv: 347 | loop: 486 | err: None
conversation principal -> user_id: None platform_end_user_id: 1
  [user] 请只回复四个字：巡检完成。不要调用任何工具。
  [assistant] 巡检完成
cleanup done
```

结论：终端用户任务落库为 `run_as_type=end_user`、`owner_user_id` 为空、`run_as_end_user_id` 指向终端用户；执行时新建的会话 principal 为 `platform_end_user_id`（`user_id` 为 `None`），与 `conversations` 表的「恰有一个 principal」约束一致。

### 12.2 迁移往返

```bash
cd apps/backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

- 预期：`tasks` 表新增列可正常增删，不影响存量数据。
- 实际：升级后 `run_as_end_user_id` 列存在（`information_schema` 计数 1）；回滚后为 0；再升级恢复为 1。

### 12.3 新增列与注释

```bash
docker exec -i ai-base-db-1 psql -U root -d ai_db -t -c \
  "SELECT a.attname, col_description(a.attrelid,a.attnum) FROM pg_attribute a \
   WHERE a.attrelid='tasks'::regclass AND a.attname IN ('run_as_type','run_as_user_id','run_as_end_user_id') ORDER BY a.attnum;"
```

- 实际：

```
 run_as_type        | 执行身份类型：user 后台用户 / end_user 终端用户 / platform 预留（v1 不支持）
 run_as_user_id     | 以哪个后台用户身份执行（run_as_type=user 时必填）
 run_as_end_user_id | 以哪个终端用户身份执行（run_as_type=end_user 时必填，Embed 链路创建的任务用）
```

### 12.4 新增测试

| 文件 | 新增用例 |
|---|---|
| `tests/tools/test_create_task.py` | `test_create_task_requires_some_identity`（错误信息可操作）、`test_create_task_for_end_user_in_embed_session`（核心修复）、`test_create_task_backend_session_prefers_user_identity`（既有行为不变）、`test_tool_description_mentions_end_user` |
| `tests/tasks/test_runner.py` | `test_runner_executes_end_user_task_with_end_user_identity`（按 `run_as_type` 正确分派，不误用后台身份） |

新增 4 个用例（另有既有用例随接口调整而更新），后端全量由 749 增至 753 passed。

### 12.5 回归影响

`_resolve_conversation` 改为通过 `get_for_principal` / `create_for_principal` 解析会话，
`execute_chat` 的 `user_id` 放宽为可选并新增 `end_user_id`。因此更新了两处既有测试的替身实现：

- `tests/conversation/test_rest_parity.py`：`FakeConversationRepository` 补 `get_for_principal` / `create_for_principal`。
- `tests/tasks/test_runner.py`：无执行身份的用例显式指定 `run_as_type="user"`。

`tests/conversation`（80 passed）与全量回归（753 passed）均无退化；REST 聊天链路行为不变。

## 验证结论摘要（第 1 次变更）

| 项目 | 结果 |
|---|---|
| 后端全量测试 | 749 passed / 1 skipped（`--import-mode=importlib`） |
| 本次相关定向测试 | 273 passed / 1 skipped |
| 新增任务模块测试 | 54 passed |
| Ruff（本次改动文件） | All checks passed |
| 迁移升级/回滚往返 | 通过，head = `20260919_0034` |
| 数据库级「同任务串行」约束 | 通过（部分唯一索引真实拒绝第二条 running） |
| `FOR UPDATE SKIP LOCKED` 多副本抢占 | 通过（两副本并发只有一个抢到） |
| 端到端真实跑一轮 Agent | 通过（真实模型调用 + 新会话 + completed 执行记录） |
| 无人值守审批矩阵 | 通过（financial 一律不批；严格模式只批 navigation） |
| 看门狗超时清理 | 通过（真实超时记录被标记 failed） |
| 权限边界 | 通过（普通用户看不到他人任务；越权 404） |
| 前端构建（含 tsc 类型检查） | 通过 |
| 前端 lint | 本次改动文件 0 error |
| 前端 format:check | 本次改动文件全部已格式化 |

## 一、后端测试

### 1.1 全量回归

```bash
cd apps/backend && .venv/bin/pytest -q --import-mode=importlib
```

- 预期：全部通过。
- 实际：`749 passed, 1 skipped, 2 warnings in 11.12s`。

### 1.2 本次相关模块

```bash
cd apps/backend && .venv/bin/pytest tests/tasks tests/tools tests/conversation tests/gateway -q
```

- 预期：任务模块与既有对话/工具链路全部通过。
- 实际：`273 passed, 1 skipped, 1 warning in 6.35s`。

### 1.3 新增测试清单

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/tasks/test_triggers.py` | 14 | cron 求下一次触发、最小间隔、六段式拒绝、时区、夏令时跳变顺延、一次性任务语义 |
| `tests/tasks/test_task_repository.py` | 7 | 可见性过滤、抢占到期、串行判定、看门狗、数据库级串行兜底 |
| `tests/tasks/test_task_routes.py` | 6 | 路由注册、Bearer 鉴权、请求/响应契约字段 |
| `tests/tasks/test_task_services.py` | 11 | 最小间隔拒绝、数量上限、暂停/恢复、一次性耗尽、权限、手动串行 |
| `tests/tasks/test_unattended.py` | 10 | 审批三条规则、计数、留痕、拒绝原因 |
| `tests/tasks/test_runner.py` | 6 | 新建会话、超时、异常兜底、暂停跳过、无执行身份、终态不重跑 |
| `tests/tasks/test_scheduler.py` | 6 | 抢占派发、重叠跳过、暂停/未到点不抢、一次性不再排、看门狗、事务原子性 |
| `tests/tools/test_create_task.py` | 8 | 归属/创建者/执行身份、最小间隔、一次性未来时刻、错误码、上限、不改他人任务 |
| 合计 | 68 | — |

`tests/tasks/` 前缀用例合计 54 个（不含 `create_task` 的 8 个与前端），全部通过。

## 二、代码质量

```bash
cd apps/backend && .venv/bin/ruff check app/modules/tasks/ app/modules/conversation/tool_dispatch.py \
  app/modules/tools/business/create_task.py tests/tasks/ tests/tools/test_create_task.py
```

- 预期：无问题。
- 实际：`All checks passed!`

```bash
cd apps/backend && .venv/bin/python -m compileall -q app/modules/tasks app/modules/conversation/tool_dispatch.py \
  main.py migrations/versions/20260919_0034_tasks.py
```

- 实际：编译通过。

## 三、数据库迁移

### 3.1 迁移链

```bash
cd apps/backend && .venv/bin/alembic heads
```

- 预期：新迁移成为唯一 head。
- 实际：`20260919_0034 (head)`

```bash
cd apps/backend && .venv/bin/alembic current
```

- 实际：`20260919_0034 (head)`

### 3.2 升级 / 回滚往返

```bash
cd apps/backend && .venv/bin/alembic downgrade -1   # 回滚到 20260903_0033
docker exec ai-base-db-1 psql -U root -d ai_db -t -c "SELECT to_regclass('public.tasks'), to_regclass('public.task_runs');"
cd apps/backend && .venv/bin/alembic upgrade head
docker exec ai-base-db-1 psql -U root -d ai_db -t -c "SELECT to_regclass('public.tasks'), to_regclass('public.task_runs');"
```

- 预期：回滚后两表不存在且不影响存量表；再升级后两表恢复。
- 实际：回滚后查询返回空（两表已删除）；再升级后返回 `tasks | task_runs`。存量表未受影响。

### 3.3 字段中文 comment 落库

```bash
docker exec ai-base-db-1 psql -U root -d ai_db -t -c \
  "SELECT a.attname, col_description(a.attrelid,a.attnum) FROM pg_attribute a \
   WHERE a.attrelid='tasks'::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum;"
```

- 预期：每个字段都有中文备注。
- 实际：24 个字段全部带中文 comment（含 `created_at`/`updated_at`；为此给共享 `TimeModel` 补了 comment 元数据）。

### 3.4 数据库级「同一任务串行」兜底

在同一事务内为同一任务插入两条 `status='running'` 记录：

```sql
INSERT INTO task_runs (task_id, status, ...) VALUES (<task>, 'running', ...);  -- 成功
INSERT INTO task_runs (task_id, status, ...) VALUES (<task>, 'running', ...);  -- 必须失败
```

- 预期：第二条被部分唯一索引拒绝；`skipped` 记录不受限制。
- 实际：
  - `ERROR: duplicate key value violates unique constraint "uq_task_runs_one_running_per_task"`
  - `DETAIL: Key (task_id)=(2) already exists.`
  - 随后 `skipped` 记录插入成功，最终统计 `running=1, skipped=1`。

> 实现细节：该索引在 SQLAlchemy 中同时声明了 `postgresql_where` 与 `sqlite_where`。只写前者时 sqlite 会退化成「task_id 全表唯一」，导致 `skipped` 记录也插不进去（该问题在开发中实测到并已修复）。

## 四、调度并发（研究阶段标记的未验证假设）

`research.md` 曾标记「`FOR UPDATE SKIP LOCKED` 在本仓库 PostgreSQL 版本上的实际并发行为」尚未验证。本次用真实 Postgres 验证：

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/concurrent_claim.py
```

两个并发事务同时抢占同一条到期任务（其中一个持锁 0.4 秒以制造重叠窗口）：

- 预期：只有一个副本抢到该任务。
- 实际：

```
replica A claimed task ids: [4]
replica B claimed task ids: []
task_runs rows: 0 | next_run_at advanced: True
RESULT: PASS 只有一个副本抢到
```

结论：多副本安全成立，重复触发不会发生。该假设已验证，`research.md` 的剩余风险可相应收敛。

## 五、端到端真实运行（核心验收项）

不打开浏览器、由调度器抢占并真实调用模型跑完一轮：

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  E2E_AGENT_ID=1 .venv/bin/python /tmp/e2e_run.py
```

步骤：建一条已到点的 `cron` 任务 → `scheduler._claim_and_dispatch` 抢占 → `runner.run_task_run` 执行 → 回写结果。

- 预期：产生一条 `completed` 执行记录与一个新会话。
- 实际：

```
claimed: [6]
runner status: completed
run: completed | conv: 345 | loop: 483 | auto_approved: 0 | err: None
  [user] 请只回复四个字：巡检完成。不要调用任何工具。
  [assistant] 巡检完成
cleanup done
```

结论：**每轮新建会话**（conv 345 为新会话）、执行记录写回 `completed`、`agent_loop_run_id` 与 `conversation_id` 均可回溯。

## 六、无人值守审批矩阵

```bash
cd apps/backend && .venv/bin/python /tmp/verify_unattended_e2e.py
```

- 预期：`financial` 在任何配置下都不批准；严格模式只批 `navigation`。
- 实际：

```
strict=False effect=navigation -> approved=True  count=1
strict=False effect=write      -> approved=True  count=1
strict=False effect=financial  -> approved=False count=0
strict=False effect=external   -> approved=True  count=1
---
strict=True  effect=navigation -> approved=True  count=1
strict=True  effect=write      -> approved=False count=0
strict=True  effect=financial  -> approved=False count=0
strict=True  effect=external   -> approved=False count=0
```

结论：与 spec 的三条规则完全一致；拒绝时返回带原因的 `rejected` 结果，模型据此可调整。

## 七、看门狗

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/verify_watchdog.py
```

制造一条 `timeout_seconds=30`、`started_at` 在 2 小时前的 `running` 记录：

- 预期：被标记 `failed` 并写明超时。
- 实际：

```
Task watchdog marked 1 stale run(s) as failed
watchdog expired count: 1
run status: failed
error_message: 执行超时：超过 30 秒仍未结束，由看门狗标记失败
watchdog_checked_at set: True
RESULT: PASS
```

## 八、权限边界

```bash
cd apps/backend && DATABASE_URL="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db" \
  .venv/bin/python /tmp/verify_perms.py
```

- 预期：管理员看到全平台；普通用户看不到他人任务；越权管理被拒。
- 实际：

```
platform: 1 admin: 7 other users: [6]
admin sees tasks: 1
member sees tasks: 0 []
member blocked from managing admin task: NotFoundException
admin can manage: True
platform-admin path allowed: True
```

结论：普通用户对他人任务得到 404（不泄露存在性），与 spec 的「删除他人的任务被拒绝」一致。

## 九、前端

### 9.1 构建（含类型检查）

```bash
pnpm --dir apps/front build
```

- 预期：`tsc -b` 与 `vite build` 均通过。
- 实际：通过（`✓ built in 659ms`；仅有既有的 chunk 体积提示）。

> 注意：首次构建因 `routeTree.gen.ts` 未重生成而报类型错误；用 `npx vite build` 触发 TanStack Router 插件重生成后即通过。该文件由构建生成、不手改。

### 9.2 lint

```bash
pnpm --dir apps/front lint
```

- 基线（stash 本次改动后）：`10 problems (4 errors, 6 warnings)`。
- 本次改动后：`11 problems (4 errors, 7 warnings)`。
- 差异：新增 1 个 warning（`features/tasks/index.tsx` 的 React Compiler 跳过提示，与既有 `agent-version-form.tsx:87` 属同类），**未新增任何 error**。
- 4 个 error 全部位于既有文件 `src/lib/http.ts` 与 `src/lib/auth.ts`，与本次改动无关。

### 9.3 格式检查

```bash
pnpm --dir apps/front format:check
```

- 差异比对（stash 前后）：本次改动**未新增**任何未格式化文件。
- 本次新建/修改的前端文件已全部执行 `prettier --write`。
- 剩余 13 个未格式化文件均为既有文件。

## 十、失败项与例外

| 项目 | 状态 | 说明 |
|---|---|---|
| `pytest` 默认收集模式 | ⚠️ 既有问题 | `apps/backend/tests/` 下多个目录缺 `__init__.py`，同名测试文件（`test_models.py` / `test_services.py` / `test_routes.py`）互相冲突，默认收集报 5 个 import file mismatch error。**已用 stash 验证该问题在本次改动前即存在**。全量验证使用 `--import-mode=importlib` 绕过。本次新增 `tests/tasks/__init__.py`，新模块不受影响。 |
| Ruff 全仓 | ⚠️ 既有问题 | `app/modules/embed/repositories.py:10` 未使用 import `BaseRepository`。该文件本次未改动，未顺手修复以免混入无关变更。 |
| 前端 lint 4 个 error | ⚠️ 既有问题 | 位于 `src/lib/http.ts`、`src/lib/auth.ts`，与本次改动无关。 |
| 前端 13 个文件未格式化 | ⚠️ 既有问题 | 与本次改动无关；本次改动文件已全部格式化。 |
| 真实调度容器部署 | 未执行 | `docker-compose.yml` 已新增 `task-scheduler` 服务但未实际重建容器；端到端验证在进程内调用同一份 `scheduler` / `runner` 代码完成。需要人工在服务端执行一次容器级验证。 |
| 浏览器交互回归 | 未执行 | 前端仅完成类型检查与构建；`/tasks` 列表、详情 Tab、Dialog 表单与「查看会话」跳转未做真实浏览器点击回归，需人工执行。 |
| 宿主工具在无人值守下的行为 | 未做端到端 | 分派层对宿主工具返回明确失败（`host_tool_unavailable_in_unattended_run`），有单元级覆盖，但未在真实 Embed 连接场景验证。 |
| 内置工具 `side_effect` 未透传 | 既有缺口 | `builtin_tool/registry.py::_from_business` 不传 `side_effect`，故内置工具恒为 `none`、不参与确认判定。本 request 按 spec 记录不修复。 |

## 十一、验证脚本位置

上述端到端脚本为一次性验证产物，按仓库约定不纳入 request 工作区，位于 `/tmp`：`smoke_sched.py`、`concurrent_claim.py`、`e2e_run.py`、`verify_unattended_e2e.py`、`verify_watchdog.py`、`verify_perms.py`。结论已完整摘录于本文档。
