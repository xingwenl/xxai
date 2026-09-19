# 设计说明

## 目标

- 为平台增加「任务」能力：一条任务 = 一个 Agent + 一段指令 + 一个时间触发规则 + 一个落点。到点后由后端无人值守地跑完一轮 Agent 对话，并把这一轮的结果落成一条可追溯的执行记录。
- 目标用户与调用方：平台管理员（管理平台级任务）、终端用户（管理自己的任务）、智能体自身（通过内置工具创建任务）。
- 完成后应产生的可验证结果：
  - 管理员在 `/tasks` 页面创建一个任务后，不需要保持浏览器打开，后端也能在预定时间自动跑完一轮对话，并在任务详情里看到这条执行记录与它创建的会话。
  - 任务创建后可以手动「立即运行一次」，用于验证与排错。
  - 后端重启、任务上一次运行尚未结束时，任务的行为符合「跳过不补跑、同一任务串行」的约定。
  - 智能体在会话中调用内置工具创建的任务会出现在任务列表里，并可被用户暂停或删除。
- 引用 `research.md` 的关键结论：调度采用「独立调度容器 + 数据库行级锁抢占」而不是 Celery beat（beat 单点是官方文档明确指出的重复触发风险）；错过触发点跳过不补跑、同一任务串行（对齐 Kubernetes CronJob 的 deadline 与 `Forbid` 语义）；触发规则显式存 IANA 时区，夏令时跳变顺延（对齐 GitHub Actions schedule 的时区与 DST 规则）；无人值守下自动批准工具调用，但 `side_effect=financial` 的操作不自动批准；暂停/恢复是一等状态。

## 范围

### 后端：新增 `app/modules/tasks/` 模块

按仓库既有分层补齐 `models.py` / `schemas.py` / `repositories.py` / `services.py` / `router.py`，并新增两个非请求驱动的入口文件：

- `scheduler.py`：常驻调度进程入口（`python -m app.modules.tasks.scheduler`），负责抢占到期任务、推进 `next_run_at`、写执行记录、维护看门狗。
- `runner.py`：单次执行的编排（生成会话、发起一轮 Agent 运行、回写执行结果）。

### 数据模型（新增两张表）

`tasks`（任务定义）关键字段：

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `platform_id` | 所属平台，外键 `platforms.id`，级联删除 |
| `agent_id` | 任务使用的 Agent，外键 `agents.id` |
| `owner_user_id` | 任务归属用户；为空表示平台级任务（平台级只有平台管理员可管理） |
| `name` | 任务名称，用于列表展示 |
| `prompt` | 到点发给 Agent 的指令内容 |
| `model_id` | 可选，覆盖该 Agent 默认模型；为空则沿用 Agent 配置 |
| `trigger_type` | 触发类型：`cron`（周期）或 `once`（一次性） |
| `cron_expression` | 五段式 cron 表达式，`trigger_type=cron` 时必填 |
| `run_at` | 一次性执行时刻，`trigger_type=once` 时必填 |
| `timezone` | IANA 时区名（默认 `Asia/Shanghai`），用于解释 cron 与 `run_at` |
| `status` | 任务状态：`active`（启用）/ `paused`（暂停） |
| `next_run_at` | 下一次应触发时刻（UTC），调度抢占依据，建索引 |
| `last_run_at` | 最近一次实际触发时刻（UTC） |
| `created_by_type` | 创建者类型：`user` / `agent` / `integration` |
| `created_by_user_id` | 创建者用户（`created_by_type=user` 时） |
| `created_by_agent_id` | 创建者 Agent（`created_by_type=agent` 时） |
| `run_as_type` | 执行身份类型：`user` / `platform` |
| `run_as_user_id` | 以哪个用户身份执行（`run_as_type=user` 时） |
| `auto_approve` | 无人值守时是否自动批准需要确认的工具，默认开启 |
| `strict_approval` | 严格模式：只自动批准 `side_effect=navigation` 的工具，默认关闭 |
| `timeout_seconds` | 单次执行超时秒数，默认 600 |
| `created_at` / `updated_at` | 时间戳 |

`task_runs`（执行记录）关键字段：

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `task_id` | 所属任务，外键 `tasks.id`，级联删除 |
| `status` | 执行状态：`running` / `completed` / `failed` / `skipped` |
| `trigger_kind` | 触发方式：`scheduled`（到点）/ `manual`（手动立即运行） |
| `planned_at` | 计划触发时刻（UTC），用于对齐「这次运行对应哪个触发点」 |
| `started_at` / `finished_at` | 实际开始与结束时刻 |
| `conversation_id` | 本轮自动创建的会话，外键 `conversations.id` |
| `agent_loop_run_id` | 对应的 Agent 运行记录，外键 `agent_loop_runs.id` |
| `error_message` | 失败原因（超时、模型错误等） |
| `skip_reason` | 跳过原因：`overlapped`（上一次未结束）/ `task_paused` / `deadline_missed` |
| `auto_approved_count` | 本轮自动批准的工具调用次数 |
| `created_at` / `updated_at` | 时间戳 |

表名采用 `tasks` / `task_runs`，与仓库 skill 中「`<module>_<resources>` 前缀」约定存在偏差，理由与待确认点见文末「待确认项」。

对应迁移文件按既有约定新增，并在 `apps/backend/migrations/env.py` 的显式 import 列表中加入新模块 `models`。

### 后端：API 契约（新增）

沿用平台作用域资源的既有前缀风格（参照 `apps/backend/app/modules/wechat_bot/router.py:26`），全部挂在 `/api/v1/platforms/{platform_id}/tasks` 下：

| 方法与路径 | 用途 |
|---|---|
| `GET /tasks` | 列表（分页）；平台管理员返回该平台全部任务，普通用户只返回自己名下的任务 |
| `POST /tasks` | 创建任务 |
| `GET /tasks/{task_id}` | 任务详情 |
| `PATCH /tasks/{task_id}` | 更新任务（含暂停 `status=paused` / 恢复 `status=active`） |
| `DELETE /tasks/{task_id}` | 删除任务；可选参数控制是否连带删除它创建过的会话（默认保留） |
| `POST /tasks/{task_id}/run` | 立即运行一次（不受最小间隔限制，仍受串行约束） |
| `GET /tasks/{task_id}/runs` | 执行记录列表（分页） |

响应结构、分页格式与错误语义沿用现有 `app/shared/` 基类，不新造格式。

### 后端：调度与执行

- 调度器形态：新增独立容器 `task-scheduler`（`docker-compose.yml`，与 `wechat-bot-worker` 同构），单进程内 `asyncio` 循环，每 30 秒一个 tick。
- 抢占方式：`SELECT ... FROM tasks WHERE status='active' AND next_run_at <= now() ORDER BY next_run_at FOR UPDATE SKIP LOCKED`，同一次事务内写入执行记录并推进 `next_run_at`，保证多副本安全。
- 触发精度：最小间隔下限 1 分钟（创建/更新时把 cron 解析成下一次触发时间，低于下限直接拒绝并返回明确错误）；因为 tick 为 30 秒，实际触发时刻允许有秒级到十秒级延迟，这一点写入任务详情页的说明文案。
- 错过语义：系统停机或调度进程不在时错过的触发点不补跑；恢复后从「当前时间之后的下一个触发点」继续。任务恢复（`paused → active`）时同样不补跑历史。
- 并发语义：同一任务串行。若触发时该任务仍有 `running` 的执行记录，则新增一条 `status=skipped`、`skip_reason=overlapped` 的记录，不发起新的运行。
- 时区与夏令时：`timezone` 存 IANA 时区名，计算触发点用该时区；存储统一 UTC；夏令时「春季跳变」导致某时刻不存在时顺延到下一个有效时刻。
- 超时与看门狗：每次执行最多 `timeout_seconds`；调度进程在启动时与每个 tick 都会把 `status=running` 且超过超时的执行记录标记为 `failed`（`error_message` 写明超时），避免进程被杀后留下永久 `running`。
- 失败处理：不自动重试；失败可在任务详情页手动「立即运行一次」重跑。
- 执行链路：每轮执行**新建会话**（不传 `conversation_id` 即自动新建），执行身份由 `run_as_type` / `run_as_user_id` 决定，执行入口为 conversation 模块内的系统调用入口（进程内调用，不经过 HTTP，也不引入新的机器身份 token）。

### 后端：无人值守下的工具审批边界

- 需要确认的工具（MCP `side_effect != none`、宿主工具 `side_effect != none` 且 `confirmation_policy=always`）在任务运行时按任务策略处理：
  - `auto_approve=true`（默认）且非 `financial`：自动批准，并在会话里留下「本次由任务自动批准」的痕迹；执行记录累加 `auto_approved_count`。
  - `strict_approval=true`：只有 `side_effect=navigation` 的工具自动批准，其余跳过并记录。
  - `side_effect=financial`：一律不自动批准，跳过并记录（工具返回明确的「自动运行不批准该操作」结果，让 Agent 据此调整）。
- 需要用户在场的挂起（如让用户回答问题的工具）在任务运行中**立即返回明确失败**，不进入 600 秒等待，避免每轮空转到超时。
- 任务运行创建的执行记录与自动批准行为必须可追溯：能从一次自动批准回溯到是哪条任务、哪次执行发起的。

### 后端：让智能体能创建任务

- 新增一个内置业务工具（`app/modules/tools/business/`，命名建议 `create_task`），让 Agent 在会话中创建任务；工具需要在 Agent 的内置工具绑定中启用后可用（沿用 `agent_builtin_tools` 机制，不做全局默认开启）。
- Agent 创建的任务：`created_by_type=agent`，归属为当前会话所属用户，`run_as_type=user`，`status=active`（创建即启用）。
- 约束：Agent 只能创建自己的任务，不能修改或删除非它创建的任务；创建同样受最小间隔下限与平台任务数上限约束。

### 前端

- 删除 shadcn 示例页：`apps/front/src/routes/_authenticated/tasks/index.tsx` 与 `apps/front/src/features/tasks/`（14 个文件）；`src/routeTree.gen.ts` 由构建自动重生成，不手改；`src/components/data-table/*` 被用户管理页共用，保留。
- 新增：`src/routes/_authenticated/tasks/index.tsx`（列表）、`src/routes/_authenticated/tasks/$taskId.tsx`（详情，Tab：概览 / 执行历史）、`src/api/task.ts`、`src/features/tasks/`（列表、表单 Dialog、zod 校验），沿用 `features/skills/index.tsx` 的列表 + Dialog 表单范式。
- 侧边栏：在 `src/components/layout/data/sidebar-data.ts` 的 AI 相关分组追加一项「任务」，指向 `/tasks`。
- 触发规则输入：提供「间隔 / 每天 / 每周 / 工作日」四种预设，同时允许直接填裸 cron；「下次运行时间」由后端返回并展示，前端不引入 cron 解析库。
- 交互路径：列表（平台选择 + 状态筛选 + 新建按钮）→ 新建/编辑 Dialog（选 Agent、填指令、选触发、选时区）→ 保存后回到列表 → 点进详情查看执行历史 → 点执行记录跳转到对应会话。

### 文档

- 根目录首次建立 `CONTEXT.md`（术语表）：任务、任务运行、触发计划、无人值守运行、自动批准、任务归属、执行身份、创建者、调度器、跳过。
- `docs/adr/0001-task-scheduling-and-unattended-execution.md`：记录调度器形态与无人值守执行入口的架构选择。

## 非目标

- 不做事件触发（webhook、文件变化、消息到达等）与「触发器 + 动作」的通用编排；本次只做时间触发 + 跑一轮 Agent。
- 不做多步动作、脚本动作或步骤间传参；任务的动作固定为「跑一轮 Agent 对话」。
- 不做结果推送通知（站内信、桌面通知、微信机器人），执行结果先只落在执行记录与会话里；通知作为后续增量。
- 不对第三方接入方开放 API token；本次只对平台管理员与登录用户的 JWT 开放，接入方能力随后续 request 处理。
- 不做错过触发点的补跑，也不做失败自动重试。
- 不实现执行历史与自动创建的会话的自动清理策略；删除任务时默认保留会话。
- 不修复既有缺口：内置工具未透传 `side_effect`（`apps/backend/app/modules/builtin_tool/registry.py:33-40`），只在风险中记录。
- 不引入 Celery beat，不改造现有知识库 Celery 链路。

## 风险

- 无人值守执行的授权放大：任务启用后，Agent 可以在没有人当场确认的情况下执行工具调用。缓解：`financial` 类一律不自动批准；提供严格模式；所有自动批准可追溯到任务与执行记录。
- 新增常驻容器：调度进程与数据库的连接占用、时区计算错误、tick 卡死都会影响任务触发。缓解：看门狗兜底、错过的触发点按跳过语义处理不堆积、最小间隔下限防止任务写爆。
- 会话与 Session 生命周期：无人值守地在后台起一轮 Agent 运行会触碰既有硬约束（一个 `AsyncSession` 同一时刻只能属于一个 Task，内层 Task 必须确定性 join）。缓解：复用 conversation 模块既有的非流式执行链路与 `persistence_factory` 隔离方式，不新造并发结构，并在验证阶段跑并发用例。
- 回归风险：删除示例页会重写 `routeTree.gen.ts`，需要构建通过；conversation 模块新增系统执行入口可能影响既有聊天路径，需要跑通现有对话相关用例；调度进程若与 API 共用同一批表，需确认读写不冲突。
- 兼容性风险：本次新增接口族与数据表，不改动既有接口字段；`tasks` / `task_runs` 表名为新表，不影响存量表。
- 数据风险：任务是新增表，无存量数据迁移；删除任务时若用户选择连带删除会话，会移除用户聊天记录，需要在前端二次确认。
- 依赖风险：后端需要新增 cron 解析依赖（当前后端无任何 cron 解析库），依赖选择待确认，见文末待确认项。

## 停点判断

- 是否涉及架构边界变化：是。新增常驻调度进程与无人值守执行入口，新增 `app/modules/tasks/` 模块，并在 conversation 模块新增一个非请求驱动的执行入口。
- 是否涉及数据模型变化：是。新增 `tasks` 与 `task_runs` 两张表及对应迁移。
- 是否涉及 API 契约变化：是。新增 `/api/v1/platforms/{platform_id}/tasks` 接口族。
- 是否涉及鉴权或权限行为变化：是。任务列表按「平台管理员可见全平台 / 普通用户仅见自己」过滤；无人值守运行时以任务配置的执行身份发起调用，不引入新的机器身份 token。
- 结论：四项全部为「是」，**进入实现前需人工确认**。确认前不写实现代码、不生成迁移。

## 待确认项

以下四点在本 spec 中已给出推荐做法，但需要一并确认后才进入 `plan`：

1. 表名 `tasks` / `task_runs` 偏离仓库 skill 的「`<module>_<resources>` 前缀」约定（例如 `task_tasks`）。推荐保持 `tasks` / `task_runs`，理由是模块名本身即资源名，且仓库已有 `agents`、`skills`、`conversations` 等同类先例。
2. 新增后端依赖用于计算 cron 的下一次触发时间（候选 `croniter`）。推荐只加后端依赖，前端不引库，展示所需信息由后端返回。
3. 调度 tick 间隔默认 30 秒（最小间隔下限为 1 分钟），以及 conversation 模块新增「系统执行入口」。
4. Agent 创建任务的单平台任务数上限，推荐默认 100 条。

## 验收标准

- 数据层：迁移可在空库与现有库上正向执行；`tasks`、`task_runs` 字段带中文 `comment`；回滚（downgrade）可删除新表且不影响存量表。
- 调度行为：创建一条间隔为 1 分钟的任务，不打开浏览器，能在 1 分钟内看到一条 `completed` 的执行记录与一个新会话；cron 表达式低于最小间隔下限时创建被拒绝并返回明确错误。
- 并发与错过：任务上一次运行未结束时到达下一个触发点，会产生一条 `skip_reason=overlapped` 的 `skipped` 记录，且不产生第二次模型调用；调度进程重启后不补跑错过点。
- 看门狗：人为制造一条超过 `timeout_seconds` 的 `running` 记录后，调度进程能将其标记为 `failed` 并写明超时。
- 工具审批：任务运行中遇到 `side_effect=financial` 的确认请求时不自动批准，执行记录与会话中能看到跳过痕迹；开启严格模式后只有 `navigation` 类自动批准；自动批准次数能在执行记录上读到。
- 智能体创建：Agent 在会话中通过内置工具创建的任务出现在任务列表中，`created_by_type` 为 `agent`，归属为会话用户，且用户可暂停或删除它。
- 权限：普通用户看不到他人任务；平台管理员能看到该平台全部任务；删除他人的任务被拒绝。
- 前端：`/tasks` 列表与详情可用，示例页删除后 `pnpm --dir apps/front build`（含类型检查）与 lint 通过；任务详情能跳转到执行记录对应的会话。
- 文档：`CONTEXT.md` 与 `docs/adr/0001-*.md` 已建立且与实现一致。
- 验证记录：`verify.md` 记录真实执行的命令与结果（迁移、并发抢占、看门狗、接口权限、前端构建）。

## 变更记录

### 初始版本

- 时间：2026-09-18
- 变更原因：首次创建 request，承接「任务（定时自动化）」功能的方案拷问结论
- 变更内容：建立初始设计说明，覆盖数据模型、API 契约、调度语义、无人值守审批边界、智能体创建路径与前端落点
- 影响章节：全部
- 是否触发人工确认：是（架构边界 + 数据模型 + API 契约 + 鉴权/权限共四项）
