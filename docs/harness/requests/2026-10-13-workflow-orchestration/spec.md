---
id: 2026-10-13-workflow-orchestration
tier: A
risk: medium
approval:
  required: true
  granted: false
  why: ["架构边界变化：新增 app/modules/workflows/ 模块", "数据模型变化：新增 3 张表并改动 tasks 表", "API 契约变化：新增 /workflows 系列路由", "权限行为变化：新增工作流执行身份与跨租户 Agent 覆盖校验"]
---

## 目标与范围

一句话：给平台加一条**无画布的多步编排**能力——在后台用有序表单定义一串步骤（Agent 步骤 / 工具步骤），手动或定时触发，按序执行并把每步结果落库，解决「固定流程要确定性、可审计地重跑」这类需求（日报、巡检、数据同步）。

- 使用者：平台管理员与后台用户，归属与可见性沿用 `tasks` 的既有口径。
- 复用既有执行入口 `apps/backend/app/modules/conversation/services.py:911` 的 `execute_unattended_chat`——它每次调用新建会话（`conversation_id=None`），于是**每步天然一个独立上下文**，这正是「多步」相对「一条长提示词」的核心收益。
- 复用既有调度器与看门狗（`app/modules/tasks/scheduler.py`）与既有审批策略（`app/modules/tasks/unattended.py` 的 `UnattendedPolicy`）。

**不做**（非目标）：

- 不做画布、拖拽、DAG 编辑器；不做条件分支、循环、并行——步骤恒为线性。
- 不做定义的版本对比、回滚、按版本重跑；不做 DSL 文件导入导出。
- 不做步骤级人工审批（不实现跨进程等待—唤醒链路）。
- 不做「从失败步骤续跑」；v1 只支持整条重跑。
- 不给 Agent 加 `run_workflow` 工具（模型自主触发工作流不在本轮）。

## 来源与方案比较

调研结论与逐条官方出处见 `docs/design/agent-workflow-orchestration-research.md`（调研日期 2026-10-13，全部来自官方文档 / 官方 `llms.txt` / 官方仓库源码）。

| 案例 | 定义形态 | 失败与重试 | 运行记录 | 版本化 |
|---|---|---|---|---|
| Dify（app DSL `0.7.0`） | YAML `graph.nodes[]` + `graph.edges[]`；变量引用 `value_selector: [nodeId, key]` | 节点属性 `error_strategy`（`none`/`failBranch`/`defaultValue`）；`WorkflowRetryConfig` | run 级摘要 + `total_steps`，**节点级日志不经 Service API 暴露** | 定义表带版本与 `status`，旧版本可删；历史 run 靠自带快照解释 |
| n8n | JSON，连接以**节点名**为键 | 节点属性 `onError`（`continueErrorOutput`/`continueRegularOutput`/`stopWorkflow`）；`maxTries` | execution 内含节点明细（按节点名） | execution 记 `workflowVersionId` + `workflowData` |
| GHA / Temporal | YAML `jobs`/`steps`；Temporal 定义即代码 | step 级 `continue-on-error`；Temporal `RetryPolicy`（默认初始间隔 1s、系数 2.0） | 每次 attempt 独立记录 | GHA 记 `head_sha`；Temporal pin revision |

**采纳**：显式且稳定的节点/边 id + **数组式选择器**（结构化数据可被 schema 静态校验，字符串模板难校验）；run + step 两级记录；run 上存 `definition_version_id` + 定义快照；失败策略与重试一律做在**步骤属性**上。

**未采纳**：画布字段、类型化输入输出 schema（Dify 的 `value_type` 本就可选，整体后置）、n8n 用节点名做连接键、独立版本表与 draft/published 三态。

**调研未改变方案的部分**：run + step 两级记录、复用工具确认机制而不新建审批节点、步骤输出双通道、触发与执行图解耦——四项均获调研证据支持，故保持原判。

## 被否决的选项

- **扩展 `tasks` 表（`task.kind='agent'|'workflow'`）**：会让 `prompt`/`model_id`/`timeout_seconds`/`cron_expression` 变成「仅当 kind=agent 才有意义」的表内二义性，且每加一个工作流字段都要回头改任务模块；独立模块能让现有任务行为零回归。
- **工作流自带触发器、不与 tasks 发生关系**：等于把 `scheduler.py` 的抢占逻辑与看门狗重写一遍，而那套已由 `docs/adr/0001-task-scheduling-and-unattended-execution.md` 定案。
- **条件分支进 v1**：代价不在「判断」本身，而在于一旦有分支就必须同时定死变量作用域、汇合语义、失败传播——v1 信息不足。仅预留边上的 `source_handle`（v1 恒为 `default`）。
- **字符串模板引用 `{{步骤名.output}}`**：静态校验「只能引用前面的步骤」需要自写解析器，且语法演化会变成兼容负担；数组选择器 `[step_id, path]` 在同一目标下是纯数据比对。仅在**提示词渲染层**保留 `{{...}}` 写法。
- **`continue-on-error` 忽略失败继续跑**：会让「工作流成功」这个状态失去意义。改为步骤属性 `on_error`，v1 只实现 `abort` / `continue_with_default`，预留 `fail_branch` 枚举值（它依赖边的出口，而 v1 不做分支）。
- **独立版本表 + draft/published 三态 + 回滚 + 按版本重跑**：需要一套「谁能跑草稿」的权限语义；而 Dify 允许删除旧版本、历史 run 靠**自带快照**解释，恰好说明快照是必需项、版本表是可选项。改用 `workflows.version` 整数 + run 快照。
- **步骤输出只存一个字段**：要么把全量输出灌进下一步污染模型上下文，要么丢掉审计所需的完整内容。取 Pi 的 `content`/`details` 双通道，截断只施加在模型可见通道上（上限 50 KB）。
- **从失败步骤续跑**：前序工具步骤可能已产生真实副作用，续跑等于「假装它们没发生」，而整条重跑又会重复副作用；在每步副作用幂等性没有方案之前，只会制造更隐蔽的错误。
- **步骤级人工审批做成一等节点**：需要跨进程挂起/恢复 + 超时 + 通知，工作量超过 v1 本身；现有 `UnattendedPolicy` 已覆盖「某个工具调用要不要批」这个真实需求。
- **为工作流单独建一套事件流 / 可观测链路**：会立刻产生「两套 trace 如何对齐」的问题，而 v1 无此需求；step 记 `agent_loop_run_id` 指针即可回溯模型调用与工具调用。
- **每步指定独立执行身份**：定义里存死身份会让同一份工作流无法被不同身份复用，并造出「定义里的身份 vs 触发者身份」不一致该听谁的越权面；且 `tasks/runner.py:99` 明确要求「恰有一个」principal。

## 停点判断

- 是否涉及架构边界变化：**是**（新增 `apps/backend/app/modules/workflows/` 模块与执行边界）。
- 是否涉及数据模型变化：**是**（新增 3 张表，并在 `tasks` 表增加一个可空外键列）。
- 是否涉及 API 契约变化：**是**（新增 `/workflows`、`/workflows/{id}/runs` 系列路由）。
- 是否涉及鉴权或权限行为变化：**是**（执行身份由触发源决定；新增「步骤覆盖的 Agent 必须与工作流同平台」校验）。
- 核心功能是否缺少关键资料：**否**（三份官方来源已覆盖定义形态、失败语义、运行记录、版本化四个维度）。

四项命中，`approval.required: true`，进入实现前必须获得人工确认。ADR 见 `docs/adr/0002-workflow-orchestration-module-boundary.md`。

## 变更点

**新增模块 `apps/backend/app/modules/workflows/`**（`models.py` / `schemas.py` / `router.py` / `repositories.py` / `services.py` / `runner.py` / `validators.py`）：

- `models.py` 三张表，每个字段按仓库约定带中文 `comment`：
  - `workflows`：`platform_id`、`name`、`description`、`agent_id`（工作流级默认 Agent）、`owner_user_id`、`created_by_*`、`status`（`active`/`paused`）、`version`（每次保存 +1）、`max_steps`（默认 50，对齐 Dify 单路径节点上限）、`definition`（JSON：`nodes[]` + `edges[]`，节点与边都带稳定字符串 id）、`timeout_seconds`、`auto_approve`、`strict_approval`。
  - `workflow_runs`：`workflow_id`、`definition_version_id`（存 `version` 值）、`definition_snapshot`（JSON，冻结本次运行用的定义）、`status`、`trigger_kind`（`manual`/`scheduled`）、`run_as_type`/`run_as_user_id`/`run_as_end_user_id`、`planned_at`/`started_at`/`finished_at`、`error_message`、`skip_reason`（`overlapped`/`workflow_paused`/`deadline_missed`）、`auto_approved_count`、`watchdog_checked_at`。
  - `workflow_step_runs`：`run_id`、`step_id`（稳定字符串，非自增）、`seq`、`node_type`（`agent`/`tool`）、`status`、`model_visible_output`（截断至 50 KB 并打标）、`raw_output`（全量）、`retry_count`、`on_error_applied`、`conversation_id`、`agent_loop_run_id`、`error_message`、`started_at`/`finished_at`。
  - 约束照 `task_runs`：`workflow_runs` 上加「同一工作流最多一条 running」的部分唯一索引（方言 `postgresql_where` 与 `sqlite_where` 都写），并加 `(status, started_at)` 复合索引供看门狗扫描。
- `validators.py`：保存时静态校验——`value_selector` 只能指向排在前面的 `step_id`；`step_id` 唯一且非空；步骤数 ≤ `max_steps`；边两端的 `step_id` 必须存在；步骤若声明工具，其 `side_effect` 不得落在 `app/modules/tasks/unattended.py` 的 `NEVER_AUTO_APPROVE_SIDE_EFFECTS`；步骤覆盖的 `agent_id` 必须与 `workflows.platform_id` 同平台。
- `runner.py`：按 `seq` 遍历步骤。Agent 步骤调 `execute_unattended_chat`（每步各开一个 `session` 与 `tool_session`，与 `apps/backend/app/modules/tasks/runner.py:206-208` 同一模式），传 `confirmation_decider=build_confirmation_decider(policy)`。工具步骤复用统一分派入口 `app/modules/conversation/tool_dispatch.py:53` 的 `build_tool_invoker`——它按 `tool.kind` 分派到内置工具（`invoke_builtin_tool`）、MCP（`_invoke_mcp_tool`）与技能脚本，因此工具步骤**不引入新的工具类型**，且天然复用同一个 `confirmation_decider`。变量渲染在调用前完成：提示词层把 `{{step_id.path}}` 替换为前序 `model_visible_output`。
- `router.py` / `schemas.py`：工作流 CRUD、手动运行、运行与步骤结果查询；一个工作流运行一份运行记录，步骤明细按 run 分页。
- `repositories.py` / `services.py`：归属可见性与 `tasks` 对齐；调度侧派发在 `workflows/scheduler.py::_claim_and_dispatch_workflows()`，执行在 `workflows/runner.py::run_workflow_run()`，两条派发路径共用 `tasks/scheduler.py` 的同一并发上限。

**改动既有文件**：

- `apps/backend/app/modules/tasks/models.py`：`Task` 增加可空 `workflow_id` 外键（为空时行为与今天完全一致）；`Task` 命中工作流时不再用自身 `prompt` 执行。
- `apps/backend/app/modules/tasks/scheduler.py`：`_supervise` 每 tick 额外跑工作流看门狗与 `workflows.scheduler._claim_and_dispatch_workflows()`，抢到的工作流运行交 `workflows.runner.run_workflow_run()`，共用同一 semaphore 与 `MAX_CONCURRENT_RUNS`。
- `apps/backend/app/main.py`（或模块注册处）：挂载新路由。
- 前端 `apps/front/src/routes/_authenticated/`：新增工作流列表/详情/运行记录页，步骤用表单式有序列表编辑（无画布）；`workflows` 请求与类型入 `apps/front/src/api/`。
- `CONTEXT.md`：新增术语「工作流」「工作流步骤」「工作流运行」「步骤运行」「定义快照」，并写明与「任务」「任务运行」的边界。
- `docs/adr/0002-workflow-orchestration-module-boundary.md`：本 request 的架构决策。
- `docs/CHANGELOG.md`：同步记录。

**第二轮改动（真机验证后收口，同一 request）**：

- 补做拷问 Q6 已批准、第一版漏实现的「每步可选最大重试次数」：`WorkflowStepInput.max_retries`（0–5）、`validators.MAX_STEP_RETRIES`、`runner._execute_steps` 的重试循环（同一份输入重试，用尽后 `on_error` 才生效），`retry_count` 记实际尝试次数。
- 保存期收紧选择器路径：新增 `validators.OUTPUT_PATH = "output"`，`{{step.other}}` 与非 `output` 的 `input_bindings` 在保存时即被拒（此前只在运行期拒绝）；`runner.py` 复用同一常量，避免两处口径漂移。
- 运行详情新增两个**计算**字段（不落库）：`raw_output_size`（`raw_output` 的 UTF-8 字节数）与 `output_truncated`（`model_visible_output` 是否带截断标记）。
- 前端契约对齐（真机验证暴露 4 处「手写类型与真实 payload 不一致」的缺陷）：`toWorkflow`/`nodeToStep` 从 `definition.nodes` 还原 `steps`（后端 `WorkflowRead` 不返回 `steps`）；重试徽标改为「尝试 N 次」且仅 `retry_count > 1` 时显示；`Workflow`/`WorkflowRun` 类型删掉后端不返回的 `created_at`/`updated_at`，列表「最近运行」改用 `finished_at ?? started_at ?? planned_at`；表单新增「失败重试次数」下拉，输出路径只读且提示只支持 `output`。
- 验证补强：verify 脚本新增「保存期拒绝非 `output` 路径」与「运行详情返回 `raw_output_size`/`output_truncated`」两阶段；另由人工用 Playwright 对真实前端 + 真实后端做了四屏 14 项断言（结论与未覆盖项见 `verify.md`）。

**验证方式**：`tools/harness/verify/2026-10-13-workflow-orchestration.sh` 逐条执行——`alembic upgrade head` + `downgrade`（确认三张表可建可拆）、`pytest tests/workflows -q`（静态校验用例、失败中止语义、`continue_with_default` 语义、快照冻结行为）、`ruff check`、以及一条端到端脚本：建两步骤工作流 → 手动运行 → 断言两步 `succeeded` 且第二步提示词里已替换第一步输出。前端用 `cd apps/front && pnpm exec tsc -b` 与 `pnpm lint`（仓库根没有 workspace，`pnpm --filter front` 不会匹配任何项目）。

## 验收标准

1. `alembic upgrade head` 后存在 `workflows`、`workflow_runs`、`workflow_step_runs` 三张表，且 `workflow_runs` 上的「同一工作流仅一条 running」部分唯一索引在 PostgreSQL 与 SQLite 两种方言下都生效（用插入两条 running 断言第二条失败）。
2. 保存一个引用**后面**步骤的 `value_selector` 时接口返回校验失败，且不写库；`step_id` 重复、步骤数超过 `max_steps`、边指向不存在的 `step_id` 同样被拒。
3. 声明 `side_effect` 落在 `NEVER_AUTO_APPROVE_SIDE_EFFECTS` 的工具步骤在**保存时**被拒，而不是运行到一半才失败。
4. 覆盖 `agent_id` 为其它平台的 Agent 时保存被拒。
5. 两步骤工作流手动运行后，`workflow_runs` 一条 `completed`、`workflow_step_runs` 两条 `succeeded`；第二步提示词中 `{{第一步.id.path}}` 已被第一步输出替换；`model_visible_output` 超过 50 KB 时被截断并带标记，而 `raw_output` 保留全量。
6. 第一步失败且 `on_error=abort` 时，第二步不执行且在 `workflow_step_runs` 中没有记录，run 状态为 `failed`；`on_error=continue_with_default` 时第二步执行且 run 记录能指出哪一步用了兜底值。
7. 改动 `workflows.definition` 后重新运行，旧 run 的 `definition_snapshot` 仍能完整解释该次运行（快照未被覆盖）。
8. 定时触发的工作流被调度器抢占后，`workflow_runs.skip_reason` 能出现 `overlapped`/`workflow_paused`/`deadline_missed`，且被强杀后 `running` 记录能被看门狗收敛。
9. 现有任务功能零回归：`pytest tests/tasks -q` 全部通过。
