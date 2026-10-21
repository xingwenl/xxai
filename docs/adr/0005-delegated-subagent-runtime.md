# 运行期动态委派子 Agent：批量业务工具 `delegate_tasks`、复用无人值守入口、并发池建在工具内部

## Status

accepted（2026-10-21 修订：`可被派` 范围与「不新增白名单表」两条结论已被 `docs/adr/0015-subagent-bindings.md` 取代，其余结论不变）

关联 Harness request：`2026-10-15-delegated-subagent-runtime`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-15-delegated-subagent-runtime/`）。

## Decision

**「派生一个子 Agent 运行」做成业务工具 `delegate_tasks`，由主 Agent 的模型自主调用。** 工具入参是一批 1~8 个子任务，每项 = `agent`（本平台某个已发布 Agent 的 slug）+ `task`（自包含指令），一次调用即一次扇出。做成业务工具而不是新端点，是为了沿用既有的「工具绑定」授权与参数校验链路：某个 Agent 能不能委派由 `agent_builtin_tools` 绑定决定（见下），不新增 Agent 字段、不新增 Agent 能力开关。参数级错误（任务数越界、slug 重复、slug 不是本平台已发布 Agent）整体拒绝且不创建任何子运行；运行级失败逐个回传，让模型自己决定重试或换人——「模型自主委派」这一层要的是部分失败可见，而不是编排层的 fail-fast。

**子运行复用既有 `execute_unattended_chat`，不新造执行器。** 它已经是「程序化跑一整轮 Agent、每轮新建会话、执行记录独立落库」的系统入口（工作流的 Agent 步骤就走它），子运行对它的全部要求正好命中。它新增 `allow_delegation` / `platform_tools_only` / `parent_loop_run_id` / `max_iterations` 四个关键字参数，父运行归属经 `build_loop_with_steps` 落库，子运行轮次上限经 `max_iterations` 一路透传到 `build_langchain_runtime(max_turns=...)`。

**并发池建在工具内部。** `delegate_tasks` 的 handler 用 `asyncio.Semaphore(settings.delegation_max_concurrency)` 限并发、每个子运行套 `asyncio.wait_for(..., timeout=settings.delegation_timeout_seconds)`。`AgentLoop` 与 `ToolRoundExecutor` 的串行语义一个字不改——勘察确认二者都是 `for call in ...` 逐个 await、全模块没有并发工具执行；把并发下沉到单个工具的 handler，既拿到并行收益，又不触碰五条入口共用的主循环。父侧照旧是「一次工具调用、一个 awaitable」。

**深度恒 1 与工具范围收缩都断在派生工具这一处。** handler 调子运行时固定传 `allow_delegation=False, platform_tools_only=True`：前者把 `delegate_tasks` 从子运行的工具清单里剔除（子 Agent 即使自己绑定了该工具也无法再派生），后者在 `load_runtime_context` 内直接把 `mcp_tools` 置空（宿主工具本就不在无人值守路径）。理由与阶段一 `workflows/runner.py` 的 `allow_orchestration=False` 同源：递归必须在这里断掉，而不是靠「用户别这么配」。两件事都必须由代码在唯一一处强制，否则会随入口漂移。

**父子关系落在 `agent_loop_runs.parent_loop_run_id` 上；「同一次扇出」的分组键记在父工具步骤的元数据里。** `parent_loop_run_id`（可空自引用 FK→`agent_loop_runs.id`、`ondelete=SET NULL`、index）指向派生它的父运行。**不另加指向步骤的外键**：父运行的工具步骤记录是整轮运行收尾时才从 `result.tool_events` 逐个补建的，而子运行在工具执行期间就已落库——那一刻父步骤行还不存在，`parent_step_id` 无法在创建时写入。分组键因此落在父工具步骤的 `step_metadata.delegatedRunIds`（子 loop id 字符串数组），由工具的 `ToolOutcome.metadata` 经 `tool_step_values` 落库，读侧据此在步骤下展开本次扇出的子运行。

**子运行上下文与父完全隔离，只给它自包含的 `task` 文本。** 不给父历史、不做摘要打包：子 Agent 自己绑定的工具与自己的系统提示词才是它的能力边界。回给父模型的是结构化数组 `{agent, status, output|error}`，每个 `output` 截断到 `settings.delegation_output_max_bytes`（默认 51200，对齐 Pi 的 50KB 上限）；父模型因此能分辨哪个子任务失败，而不是收到一坨拼接文本。

**可执行性由既有 `agent_builtin_tools` 绑定决定，不新增 Agent 字段。** 是否把 `delegate_tasks` 放进某个 Agent 的运行时工具清单，与其它业务工具走同一条绑定链路；`load_runtime_context` 新增的 `allow_delegation` 只表达「本次运行是否允许」，授权本身仍归绑定。

**子运行的 `max_turns` 用独立的 `delegation_max_iterations`（默认 8），不沿用全局 `agent_max_iterations`（默认 20）。** 父的一轮里一次派生就耗掉子运行整轮预算，而子运行 token 不并回父 `usage`（见 Consequences），沿用同一档等于量级失控。它连同 `delegation_max_tasks`(8)、`delegation_max_concurrency`(4)、`delegation_timeout_seconds`(300)、`delegation_output_max_bytes`(51200)、`delegation_max_agents_in_prompt`(50) 一起是新配置项，全部有默认值；超限一律报错，不做静默降级。

**子运行 token 本次不并入父 `usage`；运行中也不显示子进度。** 前者明确不做，是已知的统计低估；后者 v1 的可见性只有两条：落库（子运行各自是 `agent_loop_runs` 的一行、各带独立 `conversation_id`）+ 结束后的读侧 `delegatedRuns` 展开。运行期不做子事件回流，因为父会话的 SSE/WS 流是单层线性的（见 Considered Options）。

## Considered Options

- **嵌套 AgentLoop（父 loop 内直接递归跑子 loop，方案二）**：父 loop 的 `_await_with_cancel`、`max_turns` 计数、等待态短路都要求 `tool_invoker` 是单个 awaitable；在 loop 内递归起 loop 会把「父子等待」写进 loop 本身，而 loop 是五条入口共用的唯一主循环，改动面与回归面远超收益。
- **新增独立 `delegated_runs` 表（方案三）**：字段与 `agent_loop_runs` 几乎重合（会话、request_id、状态），却要再造一套读侧投影与前端类型；父子关系挂在运行表上比另起一张表更直接，查询也不必两表拼装。
- **保留 `side_effect` 作为子运行的工具过滤判据**：`builtin_tool/schemas.py` 的 `BuiltinToolCatalogRead` 与 `AgentBuiltinToolRead` 把内置工具的 `side_effect` 类型硬编码为 `Literal["none"]`，`builtin_tool/registry.py:31 _from_business` 在把业务工具并进注册表时直接丢弃其 `side_effect` ⇒ 该判据对平台工具恒真、只对 MCP/宿主工具生效，表达不了「允许哪一类工具」。
- **沿用全局 `agent_max_iterations`（默认 20）作子运行 `max_turns`**：父的一轮里一次派生就耗掉子运行整轮预算，而子 token 不并回父 `usage`，沿用同一档等于量级失控；独立配置项让「父一轮」与「子一轮」的预算各自可解释。
- **子运行继承父的工具清单**：`BusinessToolContext` 只带 `platform_id`/`agent_id`，父的 MCP 工具自带 `server_id` 与 `side_effect`，继承即权限放大；而子 Agent 自己绑定的工具才是它被授权的能力。
- **子运行内允许 MCP/宿主工具**：无人值守路径没有渠道把确认弹给人，二者默认 `side_effect="external"`（`mcp/models.py:56`、`host_tool/models.py:34`），只剩「静默批准」或「不可用」，而静默批准等于让模型一句话绕过平台权限边界。
- **为「可被派」新增白名单表 + 管理 UI**：v1 取「同平台 + 已发布」已把面收敛到「同平台内 + 子运行工具被收缩」，新增一张表 + 一套 CRUD + 前端分区的代价与收益不成比例。
- **子运行共用父的 `conversation_id`**：`Conversation` 有 `ck_conversations_exactly_one_principal`，且共用会话会让父子消息混进同一条历史，违反「每轮新建会话、执行记录可精确回溯」的既有口径。
- **子运行事件以层级标识复合进父 SSE/WS 流**：`gateway/replay.py` 是每会话单条 Redis Stream（`key=f"agent:events:{conversation_id}"`、TTL 900s、maxlen 1000），混流会挤掉父事件并让 `Recovered=False` 成为常态；`conversation/router.py` 的 `sequence` 还是每连接自增的局部变量。
- **子运行结果拼成一个字符串回父模型**：模型无法区分哪个子任务失败，也无法据 `status` 决定重试或换人；改为结构化数组，代价是父侧工具结果的形状多一层。
- **深度 ≥2 的递归委派**：需要收敛证明与不确定的 token 上界，与显式深度闸冲突；v1 靠「子运行工具清单不含 `delegate_tasks`」硬性排除，而不是靠约定。
- **子运行过程实时回灌 UI**：要复活一个没有生产实现的持久化通道（`AgentRunPersistence` 生产恒为 `NullAgentRunPersistence`），v1 用「结束后从读侧读回」替代。
- **复用 `agent_loop_steps.parent_step_id` 承载父子关系**：该列（`conversation/models.py:121`，comment 写「父步骤 ID，用于重试或派生步骤」）是自引用且全仓零写入，把跨运行的父子关系塞进它会让「一次扇出的多个子运行」失去天然分组键；父子关系落在运行上更直接，该列本次不动。
- **继续沿用 ADR 0002「先声明式后多 Agent」，把模型自主委派继续后置**：ADR 0002 否决「先做多 Agent」的两条理由本次被分别处理，因此这是**补充而非替代**。第一条「Pi 的 subagent 靠 `--no-session` 起独立进程，真实收益是上下文隔离，而『每步一个新会话』已拿到同样隔离」——隔离本身仍然成立，但本方案把子运行建在同进程的 `execute_unattended_chat` 上，隔离不再依赖独立进程，且收益从「只有隔离」扩为「隔离 + 并发 + 逐子任务成败」。第二条「自主委派不可预测、难排错、成本不可控，且解决不了固定流程要确定性执行」——前三点本次用批量上限、并发闸、超时、独立 `max_turns`、逐子任务状态与父子落库逐条对冲；最后一点本次不再由委派承担，因为阶段一已经把「固定流程要确定性执行」这条腿立住（DAG 定义、分层调度、定义快照、保存期静态校验），声明式编排仍是确定性执行的首选，委派只补「运行期按数据决定派谁」。
- **接受 ADR 0004 对阶段二的继续推迟**：ADR 0004 列了四个卡点，本次逐条处理，推迟不再成立。①`agent_loop_runs` 没有父子列 → 新增可空自引用外键 `parent_loop_run_id`，父子树直接挂在运行表上，「同一次扇出」的分组键落在父工具步骤的 `step_metadata.delegatedRunIds`；②事件流是单层线性的，父与子的事件无法在同一 `AgentEventType` 序列里区分归属 → 本次**不做混流**，父模型只经工具结果拿到每个子任务的终态文本；③`AgentRunPersistence` 没有生产实现，子运行落库链路不存在 → 不复用那条通道，「运行中不可见」作为 v1 明确代价接受；④审批 decider 无法安全继承（父 `UnattendedPolicy` 是可变实例，共享会给并行子运行带来竞态）→ 子运行的工具清单被强制收缩为平台内置/业务工具与技能脚本工具，`side_effect="external"` 的 MCP/宿主工具不在其中，没有渠道把确认弹给人类的调用，该竞态场景在本次范围内不成立。

## Consequences

- **`agent_loop_runs` 从此有父子树**：任何「按会话查运行」的既有读侧都要意识到子运行躺在同一张表里。子运行各自带独立 `conversation_id`，所以按父会话过滤不会误收；但按平台、按 Agent 或按时间窗口汇总运行数/耗时的读侧会把父子一并计入，需要显式决定要不要用 `parent_loop_run_id IS NULL` 只取父运行——判定依据是这一列，不是状态或时间。
- **v1 的「可被派」取「同平台 + 已发布」，没有白名单**：代价是同一平台内任意 Agent 可派任意已发布 Agent，爆炸半径靠子运行工具范围收缩与并发/任务数/超时闸限制，而不是靠授权名单。日后要收紧需新增白名单表与相应管理界面，届时 `delegate_tasks` 的参数级校验多一条查询。
- **子运行 token 不并回父 `usage`**：一次委派的真实成本会在父运行的 token 统计里被低估，`model_usage_records` 只能按各自 `agent_id` 分段看出子运行的花费。日后要么合并进父 `usage`、要么按委派单独计量，二者都需要先定义「一次扇出算几次调用」。
- **运行中不可见是 v1 明确的体验缺口**：补它需要复活一条目前没有生产实现的持久化/事件通道（`AgentRunPersistence` 生产恒为 `NullAgentRunPersistence`），并决定子事件如何与父事件分流；v1 的选择是「结束后从读侧读回」，代价是终端用户在扇出期间只能看到父运行停在工具步骤。
- **深度恒 1 是硬闸，三个上限是显式配置**：`delegation_max_tasks`、`delegation_max_concurrency`、`delegation_timeout_seconds` 必须有默认值且超限报错，不做静默降级——静默降级会让「模型以为派了 8 个、实际只跑了 1 个」这种不可复现的偏差进入生产。深度要放开到 ≥2 时，先要给出收敛证明与 token 上界，而不是把闸调大。
- **本次最弱的一环：子运行的 Session 隔离。** 每个子运行必须自开 Session（`async with get_session_factory()() as child_session:`），**绝不能复用 `ctx.session`**——流式运行时那是网关正在 flush/commit 的 `AsyncSession`，并发复用会撞 asyncpg 并发错误，且失败形态是间歇性的、难以归因。这是日后最容易被「顺手优化掉」的一处（复用父 Session 看起来只是省一次连接），同源先例是 `builtin_tool/services.py` 的 `get_runtime_info` 特例与 `workflows/runner.py` 的 `_run_agent_step` 自开两个 Session。看到「委派偶发数据库报错、单独跑却正常」时，先核对子运行拿的是不是自己的 Session。
