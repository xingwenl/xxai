# 实施计划

## 前置说明

本计划承接 `spec.md` 已确认的方案。进入实现前需要先说明两处**实现级事实修正**：这两点不改变 `spec.md` 的目标、范围与行为语义，但改变了落地位置，属于计划阶段的必要澄清，不是新的架构决策。

### 修正 1：无人值守的「自动批准」必须落在一个尚不存在的接缝上

`spec.md:104-107` 要求任务运行时对需要确认的工具做自动批准 / 跳过。实际代码情况（已逐处核实）：

- 确认等待**只存在于 WebSocket 连接层**：`gateway/dispatcher.py:294-332`（MCP）与 `:347-547`（宿主工具）都通过 `self.pending_mcp_confirmations` / `self.pending_host_results` 这两个**连接级 Future 字典**等待用户回传，其生命周期由 `gateway/router.py` 驱动。
- REST 路径**没有确认等待分支**：`conversation/router.py:80-136` 的 `invoke` 闭包依次分派 builtin / skill_script / skill_instruction / MCP，**没有宿主工具分支**；MCP 的确认请求只会作为 `confirmation_required` 结果落库（`conversation/services.py:806-840` 把 loop 收尾为 `waiting_confirmation`）。
- 没有任何后台进程能驱动上述 Future。

结论：任务运行如果只是「复用 `execute_chat`」，那么 `auto_approve` / `strict_approval` / `financial` 三条规则**无处生效**——不是行为不对，而是根本没有代码路径。

因此计划把「按任务策略决定批准/跳过」实现为一个**显式的无人值守分派层**，挂在系统执行入口共用的一份 `invoke` 闭包里，而不是改 `execute_chat`。`spec.md` 的抗辩边界（`financial` 不批准、严格模式只批准 `navigation`、跳过要留痕、自动批准计数）逐条落到这一层。

### 修正 2：`run_as_type=platform` 在现有链路里没有可用的 principal

`spec.md:46-47` 定义了 `run_as_type` 的 `user` / `platform` 两取值。实际代码情况：

- 会话表有硬约束 `ck_conversations_exactly_one_principal`：`user_id` 与 `platform_end_user_id` **恰有其一非空**（`conversation/models.py:11-39`）。
- 工具审计表同样有互斥约束 `ck_mcp_tool_call_audits_exactly_one_principal`（`mcp/models.py:77-86`），宿主工具审计同样按 `platform_end_user_id` 记账。
- `execute_chat` 的 `user_id` 会一路写进会话、消息与 `agent_loop_runs`；`platform_end_user_id` 是 Embed 终端用户维度，不是「平台主体」。

即在现有数据模型下**不存在一个「平台」执行身份**，只有后台用户与 Embed 终端用户两种。

因此计划把平台级任务的执行身份收敛为：**平台级任务以「创建该任务的管理员」作为执行身份**（`run_as_type=user` + `run_as_user_id=创建者/最近修改者`）。`run_as_type` 字段保留在数据模型中（`spec.md` 已确认的数据模型不缩水），但 v1 只落 `user` 一个取值，`platform` 取值在实现前显式拒绝并返回明确错误，等后续有平台主体身份时再启用。

> 这两点需要在 `plan` 确认时一并拍板；若你要求严格按 `spec.md` 原样实现，则需要先扩数据模型（新增平台 principal 概念），那会反过来构成一次新的数据模型变更。

---

## 变更文件

### 后端：新增 `apps/backend/app/modules/tasks/`

| 文件 | 职责 |
|---|---|
| `__init__.py` | 模块包声明 |
| `models.py` | `Task` / `TaskRun` 两张表的 ORM 定义（每字段中文 `comment`），沿用 `BaseModel + TimeModel` 与 `wechat_bot/models.py:26-62` 的写法 |
| `schemas.py` | `TaskCreate` / `TaskUpdate` / `TaskRead` / `TaskListData` / `TaskRunRead` / `TaskRunListData`，分页字段用 `page_no/page_size/items/total/pages` |
| `repositories.py` | `TaskRepository` / `TaskRunRepository`（继承 `BaseRepository`）；含抢占查询、可见性过滤、串行判定 |
| `triggers.py` | cron / once 的下一次触发时间计算与「最小间隔 1 分钟」校验（基于 `croniter`），时区与夏令时顺延规则集中在此 | 
| `services.py` | 任务 CRUD 的业务规则、状态流转（暂停/恢复）、运行记录查询、执行入口调用 |
| `runner.py` | 单次执行编排：建会话 → 发起一轮 Agent 运行 → 回写执行结果 |
| `unattended.py` | **无人值守分派层**（修正 1）：包装 `invoke` 闭包，实现 `auto_approve` / `strict_approval` / `financial` 三条规则与跳过留痕、自动批准计数 |
| `scheduler.py` | 常驻调度进程入口（`python -m app.modules.tasks.scheduler`）：tick 抢占、推进 `next_run_at`、写 `skip_reason=overlapped`、看门狗 |
| `router.py` | `/api/v1/platforms/{platform_id}/tasks` 接口族 |

### 后端：修改既有文件

| 文件 | 改动 |
|---|---|
| `app/modules/conversation/services.py` | 新增系统执行入口 `execute_chat_unattended`：复用现有 `execute_chat` 链路（不复制其编排逻辑），差别仅在 `invoke_tool_fn` 由调用方注入，并把 `request_id` / 执行身份显式化 |
| `app/modules/conversation/router.py` | 从 `_prepare` 的 `invoke` 闭包中抽出**可复用的工具分派构造函数**（优先做法：把闭包体提取为 `build_tool_invoker(...)`），REST 与任务两侧共用同一份分派；这是为了让修正 1 的分派层有唯一落点，避免两份分派逻辑漂移 |
| `app/modules/tools/business/registry.py` | 追加 `create_task` 模块 import 行 |
| `apps/backend/migrations/env.py` | 追加 `from app.modules.tasks import models as tasks_models  # noqa: F401` |
| `app/core/config.py` | 新增 `Settings` 字段：tick 间隔、默认超时、单平台任务数上限、调度启用开关 |
| `app/__init__.py` | `include_router(tasks_router, prefix=settings.api_v1_prefix)` |
| `apps/backend/pyproject.toml` | 新增依赖 `croniter`；同步 `poetry.lock` |

### 后端：新增文件（工具与迁移）

| 文件 | 职责 |
|---|---|
| `app/modules/tools/business/create_task.py` | `create_task` 内置业务工具（装饰器 + handler），让 Agent 创建自己的任务 |
| `apps/backend/migrations/versions/20260919_0034_tasks.py` | 建 `tasks` 与 `task_runs` 两表；`down_revision = "20260903_0033"` |

### 后端：测试

| 文件 | 覆盖 |
|---|---|
| `tests/tasks/test_triggers.py` | cron 求下一次触发、最小间隔拒绝、时区、夏令时顺延、once |
| `tests/tasks/test_task_repository.py` | 可见性过滤、串行判定、抢占语义 |
| `tests/tasks/test_task_routes.py` | 路由注册与 Bearer 鉴权（沿用 `app.openapi()` 断言范式） |
| `tests/tasks/test_unattended.py` | `auto_approve` / `strict_approval` / `financial` 三条规则、跳过留痕、计数 |
| `tests/tasks/test_runner.py` | 每轮新建会话、执行身份、失败回写 |

### 前端

| 文件 | 改动 |
|---|---|
| `apps/front/src/routes/_authenticated/tasks/index.tsx` | 重写为真实列表页（现为 shadcn 示例页，23 行） |
| `apps/front/src/routes/_authenticated/tasks/$taskId.tsx` | 新增详情页（Tab：概览 / 执行历史） |
| `apps/front/src/api/task.ts` | 新增；按 `src/api/skills.ts` 范式归一后端 `page_no/page_size/pages` |
| `apps/front/src/features/tasks/` | **删除现有 14 个示例文件**，重建为：列表、表单 Dialog（react-hook-form + zod）、详情 Tab 组件 |
| `apps/front/src/components/layout/data/sidebar-data.ts` | 「AI 管理」分组追加「任务」，指向 `/tasks` |
| `apps/front/src/routeTree.gen.ts` | 由 `pnpm dev` / `pnpm build` 自动重生成，不手改 |

已核实可安全删除：全仓仅 `routes/_authenticated/tasks/index.tsx:3-4` 引用 `@/features/tasks`，无外部引用；`src/components/data-table/*` 由 `features/users` 共用，**保留**。

### 文档

| 文件 | 改动 |
|---|---|
| `CONTEXT.md` | 已建立（commit `de1ed82`），本次按实现结果校对术语 |
| `docs/adr/0001-task-scheduling-and-unattended-execution.md` | 已建立（commit `de1ed82`），本次把修正 1（无人值守分派层的落点）补进 `Consequences` |
| `docker-compose.yml` | 新增 `task-scheduler` 服务（与 `wechat-bot-worker` 同构） |
| `docs/CHANGELOG.md` | 按仓库约定记录本次文档与功能改动 |

---

## 数据流说明

### 触发链路（调度侧）

```
scheduler.py 每 30s tick
  └─ TaskRepository.claim_due_tasks()        BEGIN
       SELECT ... WHERE status='active' AND next_run_at <= now()
       ORDER BY next_run_at FOR UPDATE SKIP LOCKED
       ├─ 该任务存在 running 记录 → INSERT task_runs(status=skipped, skip_reason=overlapped)
       └─ 否则                    → INSERT task_runs(status=running, planned_at, trigger_kind=scheduled)
       推进 tasks.next_run_at / last_run_at
     COMMIT                                   ← 抢占与推进在同一事务内
  └─ asyncio.create_task(runner.run_task_run(task_run_id))
```

### 执行链路（单次运行）

```
runner.run_task_run(task_run_id)
  ├─ 解析任务与执行身份（修正 2：取 run_as_user_id）
  ├─ load_runtime_context(agent_id, platform_id)          ← 复用 conversation/runtime.py:1145
  ├─ build_chat_model(context.version, ...)               ← 复用 agent/services.py:252
  ├─ build_tool_invoker(..., unattended=UnattendedPolicy(...))   ← 修正 1 的落点
  ├─ execute_chat_unattended(..., conversation_id=None)   ← 复用 services.py:451 链路，每轮新建会话
  ├─ asyncio.wait_for(..., timeout=task.timeout_seconds)
  └─ 回写 task_runs：status / finished_at / conversation_id / agent_loop_run_id
                     error_message / auto_approved_count
```

### 事务边界

- **抢占事务**：`claim_due_tasks` 的 `SELECT ... FOR UPDATE SKIP LOCKED` 与两条写入（`task_runs` INSERT、`tasks.next_run_at` UPDATE）必须在**同一个事务**内提交，否则多副本会重复触发。
- **执行事务**：执行期间**不持有**任何行锁；`task_runs.status=running` 是串行判定的唯一依据，避免长事务。
- **回写事务**：执行结果一次性回写，不与前置事务合并。
- **看门狗事务**：`status=running` 且 `started_at + timeout_seconds < now()` 的记录批量标记 `failed`，与抢占在同一个 tick 内先后执行，使用独立事务。

### 会话与 Session 约束

沿用 `docs/harness/requests/2026-09-18-agent-session-concurrency/research.md:24` 的硬约束：一个 `AsyncSession` 同一时刻只能属于一个 Task。调度进程内：

- 调度 tick 与 runner 各自持有**独立** session，不跨 Task 复用。
- 工具执行使用独立 `tool_session`（对齐 `conversation/router.py:72-78` 的既有做法）。
- 内层模型 Task 在 session 关闭前必须确定性 join，复用 `agent_runtime/runtime.py:26-39` 的 `cancel_and_join_tasks`。

---

## 实施步骤

1. **依赖与配置**：在 `pyproject.toml` 增加 `croniter`，`poetry lock`；`app/core/config.py` 增加调度相关 `Settings` 字段（tick 间隔、默认超时、任务数上限、启用开关）。
2. **触发器**：实现 `triggers.py`（`next_run_at` 计算 + 最小间隔校验 + 时区/DST 顺延），先写 `tests/tasks/test_triggers.py` 并跑通。
3. **数据模型与迁移**：实现 `models.py`（全字段中文 `comment`），生成 `20260919_0034_tasks.py`，在 `migrations/env.py` 登记，确认 `alembic heads` 指向新 revision，并做一次 upgrade/downgrade 往返。
4. **仓储层**：实现 `TaskRepository` / `TaskRunRepository`，重点写 `claim_due_tasks`（含 `FOR UPDATE SKIP LOCKED`）与可见性过滤，跑 `test_task_repository.py`。
5. **接口契约**：实现 `schemas.py` 与 `router.py`（列表/创建/详情/更新/删除/立即运行/执行记录列表），跑 `test_task_routes.py` 确认路由注册与鉴权。
6. **工具分派抽出**（修正 1 的前置）：把 `conversation/router.py:80-136` 的 `invoke` 闭包提取为可复用构造函数，确保 REST 行为**零变化**；先跑现有 conversation 相关测试作为回归基线。
7. **无人值守分派层**：实现 `unattended.py`，实现三条批准规则与跳过留痕，跑 `test_unattended.py`。
8. **系统执行入口**：在 `conversation/services.py` 新增 `execute_chat_unattended`，复用既有链路；跑现有对话回归测试。
9. **执行编排**：实现 `runner.py`（会话新建、超时、结果回写），跑 `test_runner.py`。
10. **调度器**：实现 `scheduler.py`（tick、抢占、看门狗、优雅退出），加 `docker-compose.yml` 的 `task-scheduler` 服务。
11. **智能体创建任务**：实现 `tools/business/create_task.py`，在 `business/registry.py` 登记，确认 `builtin_tool/registry.py` 自动派生生效，并跑 `tests/tools` 回归。
12. **前端**：删除示例页 → 新建 `src/api/task.ts` → 列表页 → 详情页（Tab）→ 侧边栏入口 → 构建触发 `routeTree.gen.ts` 重生成。
13. **文档收口**：校对 `CONTEXT.md`、把修正 1 补进 ADR、更新 `docs/CHANGELOG.md`。
14. **验证记录**：按 `spec.md` 验收标准逐项执行并写入 `verify.md`，再产出 `acceptance.md`。

---

## 第 3 次变更的实施步骤（fix：手动运行永不执行 + 执行过程不可见）

背景与根因见 `spec.md` 的「2026-09-19 第 3 次变更」。

1. **统一执行记录口径**：在 `TaskRunRepository` 中约定
   `status='running' AND started_at IS NULL` = 已排队待执行。
2. **修正入队行为**：`services.enqueue_manual_run` 不再写 `started_at`。
3. **调度器认领**：新增 `TaskRunRepository.claim_queued_runs`（`FOR UPDATE SKIP LOCKED`），
   `_claim_and_dispatch` 拆成两步（抢占到点任务 / 认领已排队 run），两步各自独立事务。
4. **并发上限**：`_supervise` 按「并发余量」限制每轮认领数量，避免排队期间被误判超时。
5. **执行过程接口**：新增 `TaskRunStepRead` / `TaskRunDetail` schema、
   `services.get_run_detail`（复用 `build_loop_payload`）、
   `GET /tasks/{task_id}/runs/{run_id}/detail` 路由。
6. **前端展开**：`src/api/task.ts` 增加 `getTaskRunDetail`；
   任务详情页新增 `RunRows` / `RunSteps`，执行历史可展开查看每一步。
7. **回归测试**：新增「手动 run 被认领」「重启遗留 run 被认领」「已在执行的 run 不被重复认领」
   「详情接口注册与鉴权」「详情组装步骤」「从未执行返回空步骤」「跨任务 run 被拒」等用例。
8. **验证**：真实 Postgres 上走完整路径（接口入队 → 调度器认领 → 真实执行）验证；
   更新 `verify.md`、`acceptance.md`、`meta.json`、`docs/CHANGELOG.md`。

第 3 次变更的测试步骤：

- `apps/backend/.venv/bin/pytest tests/tasks -q`：新增与既有用例全部通过。
- **反向验证**：临时回退修复（让 `_claim_and_dispatch` 不认领排队 run、并恢复
  `enqueue_manual_run` 写 `started_at`），确认新用例 `test_manual_run_is_claimed_and_dispatched`
  与 `test_queued_run_from_restart_is_claimed` **确实失败**——证明它们是有效的回归测试
  而不是恒真断言。
- `apps/backend/.venv/bin/pytest -q --import-mode=importlib`：全量回归无退化。
- 真实 Postgres 端到端（不绕过接口路径）：接口入队 → 调度器认领 → 执行 → `completed`。
- `pnpm --dir apps/front build`：前端类型检查与构建通过。

第 3 次变更的回滚说明：

- 代码回滚：还原 `scheduler._claim_and_dispatch`、`services.enqueue_manual_run`
  与前端展开组件；新增的只读详情接口可直接保留（不影响既有行为）。
- 无数据库变更，无需迁移回滚。
- 注意：回滚后「立即运行一次」会重新退回「永不执行、最终判超时」的行为。

---



背景见 `spec.md` 的「2026-09-19 第 2 次变更」。根因是 `create_task` 只支持后台用户身份，
而 Embed 链路只有终端用户身份。以下步骤在第 1 次变更已实现并通过验收的基础上增量追加。

1. **数据模型**：`tasks` 表新增 `run_as_end_user_id` 列（外键 `platform_end_users.id`，
   `ondelete="SET NULL"`，带中文 comment）；`run_as_type` 的注释更新为
   `user` / `end_user` / `platform`（`platform` 仍为预留）。
2. **迁移**：新增 `migrations/versions/20260919_0035_task_end_user_identity.py`，
   `down_revision = "20260919_0034"`，用 `op.add_column` 追加列；`downgrade` 删除该列。
3. **仓储与 schema**：`TaskRepository.list_tasks` 的可见性口径不变（`owner_user_id` 为 `None`
   表示管理员视角，已覆盖「终端用户任务对管理员可见」）；`TaskRead` 暴露 `run_as_end_user_id`；
   `TaskCreate` 仍不接受归属与执行身份字段（由服务层按调用者身份决定）。
4. **服务层**：`create_task` 支持显式传入执行身份（`run_as_type` + 对应 id）；
   新增 `run_as_end_user_id` 参数，`owner_user_id` 保持为「后台归属」，终端用户任务传 `None`。
5. **执行链路**：`conversation/services.py` 的 `execute_unattended_chat` 增加
   `end_user_id` 参数，复用既有 `create_for_principal` / `get_for_principal` 机制
   新建终端用户会话；`runner.py` 按 `run_as_type` 分派到 `user` 或 `end_user` 身份，
   并在两者都缺失时给出明确失败原因。
6. **工具分支**：`create_task` 依 `ctx` 判定身份——有 `user_id` 走后台分支
   （`run_as_type=user`），只有 `platform_end_user_id` 走终端用户分支
   （`run_as_type=end_user`，归属留空）；两者都没有时返回可操作的中文说明。
7. **测试**：新增 `create_task` 的 Embed 链路用例、runner 的 `end_user` 身份用例、
   `execute_unattended_chat` 的终端用户会话用例；跑全量回归确认既有行为不变。
8. **验证与文档**：在真实 Postgres 上验证迁移往返与 Embed 链路端到端创建；
   更新 `verify.md`、`acceptance.md`、`meta.json`、`docs/CHANGELOG.md`。

第 2 次变更的补充测试步骤：

- `apps/backend/.venv/bin/pytest tests/tasks tests/tools -q`：新增用例与既有用例全部通过。
- `apps/backend/.venv/bin/pytest -q --import-mode=importlib`：全量回归无退化。
- `apps/backend/.venv/bin/alembic upgrade head && alembic downgrade -1 && alembic upgrade head`：
  迁移往返通过，`tasks` 表新增列可正常增删。
- 真实 Postgres 端到端：以终端用户上下文的 `BusinessToolContext` 调用 `create_task`，
  确认任务落库为 `run_as_type=end_user`、`owner_user_id` 为空，且跑完一轮后
  执行记录带上终端用户会话 id。

第 2 次变更的回滚说明：

- 代码回滚：还原 `create_task` 的身份分支、`runner` 的身份分派与
  `execute_unattended_chat` 的 `end_user_id` 参数即可回到仅支持后台用户的版本。
- 数据库回滚：`alembic downgrade -1` 删除 `run_as_end_user_id` 列。
  **注意**：此时已创建的终端用户任务会失去执行身份，恢复代码后它们将无法运行，
  需要管理员手动暂停或删除，回滚前应确认这类任务的数量。


---

## 测试步骤

后端（在 `apps/backend` 下，环境为 `.venv`）：

- `apps/backend/.venv/bin/pytest apps/backend/tests/tasks -q`
  - 预期：触发器、仓储、路由、无人值守、编排五组用例全部通过。
- `apps/backend/.venv/bin/pytest apps/backend/tests/conversation apps/backend/tests/gateway apps/backend/tests/tools -q`
  - 预期：抽出 `invoke` 闭包与新增系统入口后，既有对话/网关/工具链路**零回归**。
- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 预期：全量通过。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 预期：无新增问题。
- `apps/backend/.venv/bin/alembic heads`
  - 预期：head 为 `20260919_0034`；并执行一次 `upgrade head` → `downgrade -1` → `upgrade head` 往返。
- 并发与看门狗（真实 Postgres，需人工在服务端执行）：
  - 起两个调度进程指向同一库，确认同一触发点只产生一条 `running` 记录（验证 `SKIP LOCKED`）。
  - 人为把一条 `running` 记录的 `started_at` 改到超时之前，确认下一 tick 被标记 `failed`。

前端（在仓库根）：

- `pnpm --dir apps/front lint`
- `pnpm --dir apps/front build`（含 `tsc -b` 类型检查）
- `pnpm --dir apps/front format:check`
- 预期：三条全部通过；构建后 `routeTree.gen.ts` 已包含 `/tasks/` 与 `/tasks/$taskId`。

端到端（需人工在服务端执行，写入 `verify.md`）：

- 创建一条间隔 1 分钟的任务，关闭浏览器，1 分钟后确认产生 `completed` 执行记录与一个新会话。
- 低于最小间隔的 cron 被拒绝且返回明确错误。

---

## 回滚说明

- **代码回滚**：
  - 删除 `app/modules/tasks/` 与 `app/modules/tools/business/create_task.py`；
  - 撤销 `app/__init__.py`、`tools/business/registry.py`、`config.py` 的登记行；
  - 还原 `conversation/router.py` 的 `invoke` 闭包与 `conversation/services.py` 的系统入口。
- **数据库回滚**：`alembic downgrade -1` 删除 `tasks` 与 `task_runs`。**注意**：任务创建的会话与会话内的聊天记录**不会被回滚**（`task_runs.conversation_id` 是 `SET NULL` 语义，会话本身独立存在），这是有意的——避免回滚代码顺带删掉用户数据。
- **前端回滚**：还原 `features/tasks/` 与 `routes/_authenticated/tasks/`，重新构建生成 `routeTree.gen.ts`。
- **部署回滚**：停掉 `task-scheduler` 容器即可让调度停止；已创建的 `task_runs` 记录保持可读。
- **需要特别关注**：`conversation/router.py` 的 `invoke` 抽取是本次**唯一触及既有聊天链路**的改动，回滚时优先确认 REST chat 行为与抽取前一致。

---

## 人工确认点

- **已完成**：`spec.md` 方案要点已确认（架构边界、数据模型、API 契约、鉴权/权限四项），允许进入 `plan`。
- **本次需要你拍板（两处实现级修正）**：
  1. 无人值守自动批准的落点改为「抽出 REST 工具分派 + 新增无人值守分派层」，而不是改 `execute_chat`。
  2. `run_as_type=platform` 在 v1 收敛为「以创建任务的管理员身份执行」，字段保留但拒绝 `platform` 取值。
- **仍需确认**：`croniter` 依赖已确认引入（构建环境可联网安装，且需在 `poetry.lock` 与镜像中同步）。
- **实现不得扩展**：不做事件触发、不做多步动作、不做结果推送通知、不对第三方开放 token、不做补跑与自动重试、不修复内置工具 `side_effect` 未透传的既有缺口（`builtin_tool/registry.py:33-40`）。
