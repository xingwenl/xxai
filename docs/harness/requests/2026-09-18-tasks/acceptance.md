# 验收结论

验收时间：2026-09-19（第 2、3 次变更追加于同日）
验收人：AI（待人工复核）
对应 spec：`docs/harness/requests/2026-09-18-tasks/spec.md`
验证证据：`docs/harness/requests/2026-09-18-tasks/verify.md`

## 第 3 次变更验收（fix：手动运行永不执行 + 执行过程不可见）

**结论：缺陷已修复并验证，可合并。**

用户报告「立即运行一次」报执行超时 600 秒。根因是调度器只派发自己在本 tick 创建的
执行记录，而手动运行只入队、无人认领，导致任务**实际从未执行**。

| 项目 | 结论 | 证据 |
|---|---|---|
| 手动运行会真正执行 | ✅ 已修复 | verify §13.2：接口入队 → 认领 → `completed`，会话 349 |
| 重启遗留的待执行记录会被认领 | ✅ 已修复 | `test_queued_run_from_restart_is_claimed` |
| 已在执行的记录不被重复认领 | ✅ 已验证 | `test_already_started_run_is_not_reclaimed` |
| 回归测试有效（非恒真） | ✅ 已验证 | verify §13.3：回退修复后 2 个新用例确实失败 |
| 执行过程可见 | ✅ 已实现 | verify §13.4：真实 loop 487 读出 7 步，含 `create_task` 工具调用 |
| 从未执行的运行可区分 | ✅ 已实现 | `test_get_run_detail_empty_when_never_executed`；前端对无步骤记录给出明确提示 |
| 无回归 | ✅ 已验证 | 全量 761 passed；前端 build 通过 |

### 本次的教训（已记入验证方法）

第 1 次变更的端到端验证**直接调用了** `scheduler._claim_and_dispatch` 与
`runner.run_task_run`，绕过了「接口写入 run → 等调度器认领」这一步——而这正是
缺陷所在。验证因此给出了「通过」的错误信心。

修正做法：第 2、3 次变更改为**按线上真实调用顺序**验证（先调 `enqueue_manual_run`，
再跑调度器 tick，最后执行），并且对关键修复做**反向验证**（回退后确认测试失败）。
后续涉及「写入—认领」这类异步接缝的改动，必须走完整路径验证。

### 第 3 次变更的剩余风险

1. **认领延迟等于一个 tick**（低）：手动运行不是立即执行，而是等下一个 tick
   （默认 30 秒）被认领。响应文案已写「已开始执行」，实际语义是「已入队」，
   存在措辞与实际的时间差；如需即时执行需另做改造。
2. **用户现存的两条脏记录**（低）：`run 8` / `run 10` 已被看门狗标记 failed
   （终态不复活）。它们如实反映修复前的缺陷，保留作为证据；用户可用
   「立即运行一次」重新触发验证。
3. **`started_at` 兼作「认领标记」**（低）：用「`running` + `started_at IS NULL`」
   表达「已排队」，语义依赖约定。代价是 `started_at` 的含义从「开始时间」变成
   「被认领时间」；好处是不新增状态值、不需要数据迁移。

## 第 2 次变更验收（fix：Embed 链路无法创建任务）

**结论：缺陷已修复并验证，可合并。**

用户报告在 Embed/AI SDK 链路让智能体创建定时任务失败（`task_requires_user_identity`）。
根因是 `create_task` 只支持后台用户身份，而 Embed 链路只有终端用户身份。
修复内容与证据：

| 项目 | 结论 | 证据 |
|---|---|---|
| Embed 链路可创建任务 | ✅ 已修复 | verify §12.1：`run_as_type=end_user`、`owner_user_id=None`、`run_as_end_user_id=1` |
| 任务能以终端用户身份执行 | ✅ 已验证 | verify §12.1：真实模型跑完一轮，会话 principal 为 `platform_end_user_id`，`user_id=None` |
| 后台链路行为不变 | ✅ 已验证 | `test_create_task_backend_session_prefers_user_identity`、全量 753 passed |
| 数据模型变更可回滚 | ✅ 已验证 | verify §12.2 迁移往返 |
| 错误信息可操作 | ✅ 已改进 | `test_create_task_requires_some_identity`：错误带中文原因而非裸错误码 |
| 权限口径 | ✅ 已明确 | 终端用户任务对平台管理员可见（`owner_user_id=None` 走管理员视角），对普通后台用户不可见；终端用户侧不提供任务管理接口 |

第 2 次变更新增的剩余风险：

1. **终端用户无法自助管理任务**（中）：终端用户创建的任务只能由平台管理员在 `/tasks` 查看、暂停或删除；Embed 侧没有任务管理入口。若要让终端用户自助管理，需要新增 Embed 侧接口与前端，属独立增量。
2. **终端用户任务对普通后台用户不可见**（低）：这是有意的权限口径（终端用户任务没有后台归属），但意味着管理员需要主动排查这类任务。
3. **`run_as_type=platform` 仍不支持**（低）：与第 1 次变更相同，现有数据模型没有平台主体 principal。

## 总体结论（第 1 次变更）

**达到 spec 验收标准，可以合并；但存在需要人工在服务端完成的部署级与浏览器级回归项**（见「仍需人工完成」）。本次为代码与数据层的完整闭环，未做容器重建与真实浏览器点击。

建议：先合并代码，再由人工执行一次「重建 `task-scheduler` 容器 + 浏览器走查 `/tasks`」，即可完全闭环。

## 验收标准逐项核对

| # | spec 验收标准 | 结论 | 证据 |
|---|---|---|---|
| 1 | 数据层：迁移可在空库与现有库上正向执行；字段带中文 comment；回滚可删除新表且不影响存量表 | ✅ 满足 | verify 三；`alembic upgrade/downgrade` 往返通过；24 字段全带中文 comment |
| 2 | 调度行为：不打开浏览器，1 分钟内能看到 `completed` 执行记录与新会话；低于最小间隔的 cron 被拒绝 | ✅ 满足 | verify 五（真实模型调用，conv 345 / loop 483 / completed）；verify 一（`test_create_task_rejects_too_frequent_cron`、`test_min_interval`） |
| 3 | 并发与错过：重叠触发产生 `skipped(overlapped)` 且不产生第二次模型调用；重启后不补跑 | ✅ 满足 | verify 四（两副本并发只有一个抢到）、verify 一（`test_overlapped_trigger_is_skipped`、`test_claim_and_advance_are_atomic`）；错过不补跑由 `next_run_at` 语义 + `test_compute_next_run_at_cron_skips_missed_points` 覆盖 |
| 4 | 看门狗：人造超时 `running` 记录被标记 `failed` 并写明超时 | ✅ 满足 | verify 七（真实 Postgres，`error_message` 含「超时」） |
| 5 | 工具审批：`financial` 不自动批准并留痕；严格模式只批 `navigation`；自动批准次数可读 | ✅ 满足 | verify 六（完整审批矩阵）；`auto_approved_count` 落 `task_runs` 并由 `test_runner` / `test_unattended` 覆盖 |
| 6 | 智能体创建：Agent 创建的任务出现在列表、`created_by_type=agent`、归属会话用户、用户可暂停/删除 | ✅ 满足（暂停/删除为接口层已验证） | verify 一 `test_create_task_attributes_to_conversation_user_and_agent`、`test_tool_does_not_touch_other_tasks`；暂停/删除由 `test_pause_and_resume_recompute_next_run_at` 与路由测试覆盖 |
| 7 | 权限：普通用户看不到他人任务；管理员看到全平台；删除他人任务被拒绝 | ✅ 满足 | verify 八（真实用户数据：admin 1 条 / member 0 条 / 越权 NotFoundException） |
| 8 | 前端：`/tasks` 列表与详情可用；示例页删除后 build 与 lint 通过；能跳转到执行记录对应会话 | ⚠️ 部分满足 | build（含类型检查）通过、本次改动文件 0 lint error（verify 九）；**浏览器点击回归未执行**；「查看会话」跳转已实现（`/chats?conversation=<id>`）但未在浏览器验证 |
| 9 | 文档：`CONTEXT.md` 与 `docs/adr/0001-*.md` 已建立且与实现一致 | ✅ 满足 | `CONTEXT.md` 已补「重叠跳过」「看门狗」；ADR 增加「实现补充」记录两处落地修正 |
| 10 | 验证记录：`verify.md` 记录真实执行的命令与结果 | ✅ 满足 | verify 全文，含失败项与例外章节 |

## 已完成的验证

- 后端全量测试 749 passed / 1 skipped；本次相关定向 273 passed
- 新增 68 个用例（任务模块 54 + `create_task` 8 + 路由/契约等）
- 迁移升级/回滚往返、字段中文 comment 落库
- 数据库级「同任务串行」部分唯一索引真实拒绝
- `FOR UPDATE SKIP LOCKED` 多副本并发抢占（研究阶段遗留假设，已验证）
- 端到端真实模型调用跑完一轮并回写 `completed` + 新会话
- 无人值守审批矩阵、看门狗、权限边界（均用真实 Postgres）
- 前端构建（`tsc -b` + `vite build`）与本次改动文件的 lint / format

## 变更文件清单

**后端新增**
- `app/modules/tasks/`：`__init__.py`、`models.py`、`schemas.py`、`repositories.py`、`triggers.py`、`services.py`、`router.py`、`runner.py`、`scheduler.py`、`unattended.py`
- `app/modules/conversation/tool_dispatch.py`
- `app/modules/tools/business/create_task.py`
- `migrations/versions/20260919_0034_tasks.py`
- `tests/tasks/`（7 个测试文件 + `__init__.py`）、`tests/tools/test_create_task.py`

**后端修改**
- `app/__init__.py`、`app/core/config.py`、`app/shared/base_model.py`
- `app/modules/conversation/router.py`、`app/modules/conversation/services.py`
- `app/modules/tools/business/registry.py`
- `migrations/env.py`、`pyproject.toml`、`poetry.lock`
- `tests/conversation/test_tool_session_isolation.py`（随分派抽取更新 patch 目标）

**前端**
- 删除：`src/features/tasks/`（14 个示例文件）、`src/routes/_authenticated/tasks/index.tsx`（示例）
- 新增：`src/api/task.ts`、`src/features/tasks/index.tsx`、`src/features/tasks/task-detail-page.tsx`、`src/routes/_authenticated/tasks/index.tsx`、`src/routes/_authenticated/tasks/$taskId.tsx`
- 修改：`src/routes/_authenticated/chats/index.tsx`（新增 `?conversation=` 深链）、`src/features/chats/index.tsx`（消费该参数）、`src/components/layout/data/sidebar-data.ts`、`src/routeTree.gen.ts`（构建生成）

**文档与部署**
- `docs/CHANGELOG.md`、`CONTEXT.md`、`docs/adr/0001-task-scheduling-and-unattended-execution.md`
- `docker-compose.yml`（新增 `task-scheduler` 服务）

## 剩余风险

1. **调度容器未实施部署验证**（中）：`task-scheduler` 服务已写入 compose 但未重建容器运行。虽然端到端已在进程内用同一份代码验证，容器层面的启动参数、日志落盘、依赖顺序仍需人工确认。
2. **前端浏览器回归缺失**（中）：列表筛选、Dialog 表单校验、详情 Tab、暂停/恢复、「查看会话」跳转均未经真实浏览器点击。类型检查通过不代表交互正确。
3. **无人值守授权放大**（中，spec 已识别）：`auto_approve=true` 时任务可无人确认地执行工具调用。已通过「`financial` 一律不批 + 严格模式 + 自动批准计数留痕」缓解；但依赖 `side_effect` 标注的准确性。
4. **内置工具 `side_effect` 未透传是既有缺口**（低）：`builtin_tool/registry.py::_from_business` 不传 `side_effect`，内置工具恒为 `none`、不参与确认判定。这意味着「审批边界」目前只对 MCP 与宿主工具生效。本 request 按 spec 记录不修复，建议后续单独处理。
5. **平台级任务的执行身份**（低）：`run_as_type=platform` 在现有数据模型下没有可用 principal，本阶段收敛为「以创建任务的管理员身份执行」。若后续要引入平台主体，需扩数据模型。
6. **既有的测试收集与 lint 问题**（低）：`tests/` 缺 `__init__.py` 导致默认收集模式失败；`embed/repositories.py` 有未使用 import。均为既有问题，本次未改。
7. **`croniter` 依赖**（低）：新增后端依赖，已更新 `poetry.lock`；镜像构建走清华源（Dockerfile 默认），需确认目标环境可获取该包。

## 仍需人工完成

1. 重建并观察调度容器：
   ```bash
   docker compose up -d --build task-scheduler
   docker compose logs -f task-scheduler
   ```
   确认启动日志出现「任务调度器启动（tick=30s …）」且无异常。
2. 浏览器走查：登录 → `/tasks` → 新建（四种预设 + 裸 cron）→ 保存 → 详情 Tab → 「立即运行一次」→ 执行历史 → 点「查看会话」确认定位到对应会话。
3. 在服务端用真实任务验证一次「间隔 1 分钟」的自动触发（不打开浏览器）。
4. 修复已识别的既有问题（另开 request 或 `/fix`）：`tests/` 补 `__init__.py`、`embed/repositories.py` 清理未使用 import。

## 是否可合并

**可以合并。** 本次改动为独立闭环，未改动既有接口字段与存量表；对既有聊天链路唯一的侵入是工具分派抽取，已用既有回归测试（含 `test_tool_session_isolation`）锁定行为，并顺带修复了 REST 链路 MCP 工具调用的既有缺陷。合并后按「仍需人工完成」执行部署与浏览器回归。
