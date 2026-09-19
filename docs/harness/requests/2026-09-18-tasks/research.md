# 业界调研记录

## 调研问题

- 本次要解决的问题：为多租户 Agent 平台增加「任务」能力——按时间触发、无人值守地跑一轮 Agent 对话，并把结果落成一次可追溯的执行记录。
- 调研结果将影响的范围：调度器形态（独立进程还是复用队列）、时间触发语义（错过是否需要补跑、时区与夏令时）、并发策略、无人值守时「需要人工确认的工具」如何处理、数据模型与 API 契约。
- 目标用户与调用方：平台管理员、终端用户，以及智能体自身（通过内置工具创建任务）。

## 功能复杂度

- 级别：核心功能。
- 选择理由：新增独立模块与数据表、新增常驻调度进程、无人值守发起 Agent 运行（触及会话与 Session 生命周期约束）、涉及权限判定与无人值守下的工具审批边界。
- 最低调研要求：除官方文档与成熟案例外，额外覆盖可靠性与安全（无人值守审批边界、多副本重复触发风险）。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Kubernetes 官方文档《CronJob》
- 链接：https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
- 版本或发布日期：Stable since v1.21；页面标注 Last modified May 13, 2026
- 调研日期：2026-09-18
- 核心做法：
  - `concurrencyPolicy` 三选一：`Allow`（默认，允许并发）/ `Forbid`（上一次未结束则跳过本次）/ `Replace`（替换正在运行的那次）。
  - `startingDeadlineSeconds` 定义「允许晚多久启动」，超过 deadline 的实例被跳过（后续触发点照常），且被视为失败。
  - 控制器每 10 秒检查一次，因此 deadline 小于 10 秒可能失效；错过的调度点超过 100 次时不再启动并记录错误。
  - 未设置 `startingDeadlineSeconds` 时，错过就没有 deadline。
- 对本项目的启发：这套字段是「错过怎么办」的规范语义来源。我们不需要三档并发策略，但需要明确选定一档并写进 spec；「错过即跳过、不补跑」等价于配置了 deadline 的行为，是业内被广泛接受的默认。

### 来源 2

- 类型：官方文档
- 名称：GitHub Docs《Events that trigger workflows》中 `schedule` 一节
- 链接：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- 版本或发布日期：文档版本 free-pro-team@latest（页面未标注更新日期）
- 调研日期：2026-09-18
- 核心做法：
  - 使用 POSIX 五段式 cron；默认时区 UTC，可显式指定 IANA 时区。
  - 最短间隔为 5 分钟；高负载时（尤其整点）会延迟，负载过高时排队任务可能被丢弃。
  - 夏令时「春季跳变」时被跳过的时刻顺延到下一个有效时间。
  - 公共仓库 60 天无活动会自动禁用定时工作流。
  - 定时工作流只在默认分支的最新提交上运行。
- 对本项目的启发：① 「定时」不是硬实时，系统必须能表达并接受延迟与丢弃；② 时区必须显式存储，不能依赖服务端本地时区；③ 夏令时要有确定规则（顺延）；④ 「暂停/禁用」是这类功能的一等状态，不是附加功能。

### 来源 3

- 类型：官方文档
- 名称：Celery 官方文档《Periodic Tasks》
- 链接：https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html
- 版本或发布日期：Celery 5.x stable 文档
- 调研日期：2026-09-18
- 核心做法：`celery beat` 是集中式调度器，文档明确要求「同一时刻只能有一个 scheduler 在运行，否则会产生重复任务」；默认 UTC，可配置时区；支持 `crontab` 表达式与自定义 scheduler 类（含把 schedule 存进数据库）。
- 对本项目的启发：这正是「不选 beat」的直接依据——beat 是单点，多副本会重复触发，而重复触发在本项目里意味着重复消耗模型调用并产生重复会话。相比之下，把到期时间落库后由进程抢占（数据库行级锁）可以让调度天然支持多副本与重启恢复。

### 来源 4

- 类型：官方资料（本机内置）
- 名称：Codex 自身 automations / heartbeat 语义（`~/.codex/skills/.system/openai-docs/references/codex-self-knowledge.md:58` 与 `automation_update` 工具 schema）
- 链接：本机文件（无公网链接；`developers.openai.com` 对应页面在本环境返回 Forbidden，无法引用）
- 版本或发布日期：随本机 Codex 版本
- 调研日期：2026-09-18
- 核心做法：automation 区分为 heartbeat（依附当前线程）与 cron（独立任务、绑定 project）；字段包含 `rrule`、`status: ACTIVE | PAUSED`、`notificationPolicy`（可收敛为 `failed_runs_only`）。
- 对本项目的启发：「暂停/恢复」与「通知策略」应该是一等字段；默认通知策略应当收敛，只报失败，避免定时任务变成噪音源。

### 来源 5

- 类型：成熟开源项目源码（本机）
- 名称：Pi 的会话后端 writer lease
- 链接：/Users/lixingwen/xw/git/pi `packages/session-backends/sqlite-node/src/sqlite/repo.ts`、`packages/session-backends/sqlite-node/test/writer-leases.test.ts`
- 版本或发布日期：本机当前版本
- 调研日期：2026-09-18
- 核心做法：用「单写者租约」保证同一份数据的写入者唯一；Pi 本身没有调度/自动化子系统（搜索 `cron|heartbeat|schedul` 仅命中会话空闲释放与压缩重试）。
- 对本项目的启发：多副本抢同一任务时，用「抢占 + 租约」而不是共享状态协调；这与本仓库 2026-09-18 会话并发修复的「写入者唯一」原则一致，方案形态上可以互相印证。

### 来源 6

- 类型：本仓库既有实现（一手事实）
- 名称：微信机器人常驻 worker 与内部 REST 调用范式
- 链接：`apps/backend/app/modules/wechat_bot/worker.py`、`apps/backend/app/modules/wechat_bot/chat_client.py:39`、`docs/harness/requests/2026-08-23-wechat-bot-managed/`
- 版本或发布日期：仓库当前版本
- 调研日期：2026-09-18
- 核心做法：独立容器常驻，`asyncio` 循环按固定周期对账数据库变更，遇到需要人工介入的场景返回兜底文案；通过内部 REST `POST /api/v1/agents/{agent_id}/chat`（`stream=false`）以绑定用户身份同步跑完一轮对话并拿到最终结果。
- 对本项目的启发：「无人值守发起一轮 Agent 运行」在本仓库已有可复用范式与已验证的调用面（`conversation_id` 为空时自动新建会话）；本功能不应另造执行链路。

## 方案比较

### 调度器形态

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. 独立调度容器 + 数据库 `next_run_at` 抢占（`FOR UPDATE SKIP LOCKED`） | 多副本安全；重启可恢复；已有 `wechat-bot-worker` 容器先例可复用；不引入新的中间件 | 多一个容器与一个常驻进程；触发精度受 tick 间隔限制 | 高：满足多副本与重启恢复要求，且与既有 worker 范式一致 |
| B. Celery beat + Celery worker | 复用已有 broker 与 worker 容器 | beat 是单点，官方明确要求同一时刻只能有一个 scheduler，否则重复触发；现有 Celery 只服务知识库，混入调度会让职责发散 | 低：重复触发在本项目代价高（重复模型消耗 + 重复会话） |
| C. 在 FastAPI 进程内起 asyncio 定时循环 | 改动最小 | 与 API 进程同生命周期；多副本必然重复触发；API 重启即中断调度 | 低：不可靠，且把调度与请求处理耦合 |
| D. 复用微信机器人式的纯内存轮询 | 复用现成代码 | 触发时间无持久化，重启丢失；无法表达「错过」语义 | 低：不满足可靠性与可追溯要求 |

### 错过触发点的语义

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 跳过不补跑 | 行为可预期；不会在系统恢复后突然爆发大量运行；与 K8s 设置 deadline 后跳过的语义一致 | 停机期间的任务确实不会执行 | 高：符合「跑通优先、语义简单」的目标 |
| 补跑全部错过点 | 理论上不丢任务 | 停机越久爆得越狠；同一任务串行时补跑会排队；成本不可控 | 低 |
| 只补跑最近一次 | 兼顾不漏与不过载 | 语义更复杂，需要额外状态与说明 | 中：可作为后续增量 |

### 无人值守下「需要人工确认的工具」

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 一律自动批准 | 行为最简单，任务不会被卡住 | 支付类等不可逆操作会在无人监督下执行 | 低：不可逆操作没有回退路径 |
| 自动批准，但 `financial` 类工具不自动批准（跳过并记录） | 任务可用性高；不可逆操作仍由人把关；已有 `side_effect` 分级可直接复用 | 依赖 `side_effect` 标注的准确性 | 高：与仓库现有分级天然对齐 |
| 一律等待人工确认 | 最安全 | `waiting_confirmation` 等待上限 600 秒，无人值守等同每轮空转到超时 | 低 |

## 最终决策

- 选择方案：调度采用方案 A（独立调度容器 + `tasks.next_run_at` + 行级锁抢占）；错过触发点采用「跳过不补跑」；并发采用「同一任务串行，重叠触发记为跳过」（等价于 K8s 的 `Forbid`）；无人值守工具确认采用「自动批准 + `financial` 类不自动批准」。
- 选择原因：
  - 独立调度容器复用了仓库已有的常驻 worker 范式，且数据库抢占让调度支持多副本与重启恢复，避免了 beat 单点与 API 进程内定时循环的重复触发问题（来源 3、来源 5、来源 6）。
  - 「跳过不补跑」+「串行」+「不自动重试」三条组合起来，让「一次任务的运行次数与模型消耗」完全可预期，符合本次「先跑通」的目标（来源 1、来源 2）。
  - 复用 `side_effect` 分级而不是新造风险体系，是因为它已经在 MCP 与宿主工具上生效，新增概念会带来两套判断标准（来源 6 与本次事实核查）。
- 不选择其他方案的原因：celery beat 单点且重复触发代价高；API 进程内定时循环不可靠；纯内存轮询无法表达错过语义；补跑在串行约束下会形成不可控堆积；一律自动批准会放开不可逆操作。
- 对后续 spec、plan 或人工确认的影响：本次触发数据模型、API 契约、新增常驻进程与无人值守执行入口四类变更，按仓库规则均属需人工确认项，spec 完成后必须先确认再进入实现。

## 剩余风险

- 资料时效性：Kubernetes 与 GitHub Actions 文档为当前版本；Celery 文档为 stable 分支，未锁定具体小版本。
- 未获取的官方资料：`developers.openai.com` 上 Codex automations 页面在本环境返回 Forbidden，网络亦被沙箱限制；来源 4 改用本机内置官方资料替代。若后续需要正式引用 Codex automations 行为，应补一次可访问的官方页面核对。
- 与本项目上下文的差异：K8s 与 GitHub Actions 都是「调度与执行分离」的基础设施，本项目要在同一进程内完成「调度 + 发起 Agent 运行 + 写回执行记录」，因此看门狗与超时控制必须自己实现（本仓库当前没有任何兜底的运行超时清理逻辑）。
- 尚未验证的假设：
  - `FOR UPDATE SKIP LOCKED` 在本仓库使用的 PostgreSQL 版本上的实际并发行为，需要真实并发验证。
  - cron 表达式解析需要新增后端依赖（当前后端无任何 cron 解析库），依赖选择与是否可接受需在方案确认时一并拍板。
  - `side_effect` 是否被完整标注：已确认内置工具当前不透传 `side_effect`（`apps/backend/app/modules/builtin_tool/registry.py:33-40`），即内置工具恒为 `none`；这会让「自动批准边界」对内置工具暂时不生效，属于既有缺口，本 request 只记录不修复。
