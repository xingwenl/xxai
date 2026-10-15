---
id: 2026-10-15-delegated-subagent-runtime
tier: A
risk: high
approval:
  required: true
  granted: false
  why: ["架构边界变化：新增「运行期由模型派生并发的子 Agent 运行」这一执行形态，agent_loop_runs 首次出现父子树", "数据模型变化：agent_loop_runs 新增父子列与父步骤列（新迁移）", "API 契约变化：内置工具目录新增 delegate_tasks 且其描述按平台注入可派清单；loop 读取投影新增 delegatedRuns", "鉴权权限行为变化：子运行的可执行工具范围被强制收缩为「平台内置/业务工具 + 技能脚本工具」，MCP 与宿主工具不可用"]
---

## 目标与范围

一句话：给 ai-base 的 Agent 增加**运行期动态委派**——把「派生一个子 Agent 运行」做成模型可调用的业务工具 `delegate_tasks`，父 Agent 在一次工具调用里按运行期数据决定派 1~8 个子任务给**本平台其他已发布 Agent**；每个子运行上下文完全隔离、并发受显式闸约束、深度恒为 1、工具范围被强制收缩；子运行各建独立会话与运行记录并挂在父运行下，父模型只拿回每个子任务的终态文本（带字节上限）。

给谁用：平台管理员通过既有「工具绑定」把 `delegate_tasks` 授权给指定 Agent；终端用户在 embed 会话里无感触发（是否委派由父 Agent 的模型自己决定）。

**做**：
- 新增内置业务工具 `delegate_tasks`（批量：1~8 个子任务，每个含 `agent`（slug）+ `task`（自包含指令））
- 子运行复用既有 `execute_unattended_chat`：新会话、独立模型轮次、独立落库
- 显式闸：单次任务数上限、运行期并发闸、子运行 `max_turns`、子运行超时，全部来自新增配置项
- 深度恒 1：子运行的运行时工具清单里不含 `delegate_tasks`
- 工具范围收缩：子运行剔除 MCP 工具（宿主工具本就不在无人值守路径）
- 父子落库：`agent_loop_runs.parent_loop_run_id`；同一次扇出的子运行句柄记在父工具步骤的 `step_metadata.delegatedRunIds`；读侧 `delegatedRuns`
- 级联取消；父运行工具步骤里记下本次扇出的子运行句柄
- 只读可见性：ai-sdk 的 loop 展示与任务详情页可展开子运行

**不做**：
- 深度 ≥2 的递归委派（子 Agent 再派子 Agent）
- 子运行内的 MCP 工具与宿主工具
- 「父历史打包/摘要传给子运行」（子运行只拿自包含的 `task` 文本）
- 子运行过程事件回流父会话事件流（既不进 SSE 也不进 WS；仅终态经父的工具结果返回）
- 运行中的实时子进度 UI（v1 只在运行结束后从读侧读回展开）
- 「可被派」白名单表与管理 UI（v1 取「同平台 + 已发布」）
- 子运行 token 并入父 `usage`；按运行次数计的新配额资源
- 向子运行下发附件（`task` 是纯文本）

## 来源与方案比较

本次调研（2026-10-15，官方文档/官方仓库 + 本机源码）：

| 来源 | 版本锚点 | 派生形态 | 隔离 | 并发/深度闸 | 结果回流 |
|---|---|---|---|---|---|
| 本机 Pi | HEAD 4e69b0c | 示例扩展 `subagent/index.ts` 起独立 pi 进程 | 完全隔离（`--no-session`） | 任务 8 / 并发 4 | 只取最后一段 assistant 文本，硬压 50KB |
| Claude Code | 官方文档 | Task 工具派生 subagent | 独立上下文 | 由宿主控制 | 终态文本回主 Agent |
| LangGraph | v1（JS 1.5.0） | 主 agent 把子 agent 当 `@tool`（`langgraph-supervisor` 已停止维护） | 子 agent 默认 stateless + clean context | 由调用方图控制 | 子图返回值 |
| Temporal | Server 1.33 | Child Workflow / Activity | 独立执行域 | in-flight 2000 / child 1000 | Promise/Future，默认 fail-fast |
| CrewAI | 官方文档 | 角色化 agent 团队 | 任务间不共享推理上下文 | 无强制闸 | 结果回灌 lead agent |

链接：[Pi subagent 示例](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/examples/extensions/subagent/index.ts)｜[Claude Code subagents](https://docs.claude.com/en/docs/claude-code/sub-agents)｜[LangGraph subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)｜[Temporal child workflows](https://docs.temporal.io/encyclopedia/child-workflows)｜[CrewAI crews](https://docs.crewai.com/concepts/crews)

横向结论（用来定本方案口径）：
1. 成熟实现一律**隔离默认、共享显式**：Pi 干脆不给父历史；LangGraph 的 subagents 官方称比 Skills 少 67% token——隔离是收益本身，不是妥协。
2. 结果回流一律**只有终态文本 + 显式上限**：Pi 只取最后一段并硬压 50KB；没有任何实现把子运行全过程回灌父上下文。
3. 并发与深度**一律显式配置**（Pi 4/8、Temporal 1000/2000），没有一个是自适应。
4. **默认 fail-fast 只出现在「编排/工作流」层**（Temporal `Promise.all`、GHA `fail-fast: true`）；「模型自主委派」这一层要的是**部分失败可见**——Pi 让每个子任务各自成败，模型据此决定重试或换人。本方案取舍：**参数级错误整体拒绝，运行级失败逐个回传**。
5. 权限边界必须显式收缩：Pi 的子进程**不继承父工具白名单**（未写 `tools` 时落到默认全集），这是它文档自曝的缺陷；本方案反过来，由代码强制收缩子运行工具范围。

方案比较：
- **方案一（采纳）**：一个批量业务工具 `delegate_tasks` + 复用 `execute_unattended_chat` 作子运行入口 + `agent_loop_runs` 加两个可空外键。并发池建在**工具内部**，`AgentLoop` 保持串行不变。
- 方案二（否决）：把子运行做成 `AgentLoop` 的嵌套调用（父 loop 内直接递归跑子 loop）。
- 方案三（否决）：新增独立的 `delegated_runs` 表存子运行，不复用 `agent_loop_runs`。

选方案一的理由：`execute_unattended_chat`（`conversation/services.py:1049`）已经是「程序化跑一整轮 Agent、每轮新建会话」的系统入口，工作流的 agent 步骤就走它，子运行不需要新执行器；`agent_loop_runs` 已有 `conversation_id` 指向子会话，只缺两个可空外键；把并发池放在工具内部既拿到并行收益，又不改 `AgentLoop`/`ToolRoundExecutor` 的串行语义（勘察确认二者都是 `for call in ...` 逐个 await，全模块无并发工具执行）。

## 被否决的选项

- **嵌套 AgentLoop（方案二）**：父 loop 的 `_await_with_cancel`、`max_turns` 计数、等待态短路都要求 `tool_invoker` 是单个 awaitable；在 loop 内递归起 loop 会把「父子等待」写进 loop 本身，而 loop 是五条入口共用的唯一主循环，改动面与回归面远超收益。
- **新表 `delegated_runs`（方案三）**：字段与 `agent_loop_runs` 几乎重合（会话、request_id、状态），却要再造一套读侧投影与前端类型。
- **保留 `side_effect` 作为子运行的工具过滤判据**：`builtin_tool/schemas.py:8-12`/`:15` 把内置工具的 `side_effect` 硬编码为 `"none"`，`registry.py:31 _from_business` 直接丢弃业务工具的 `side_effect` ⇒ 该判据对平台工具恒真、只对 MCP/宿主工具生效，表达不了「允许哪一类工具」。
- **沿用全局 `agent_max_iterations`（默认 20）作子运行 `max_turns`**：父的一轮里一次派生就耗掉子运行整轮预算，而子 token 不并回父 `usage`（勘察确认 HEAD 无此路径），沿用同一档等于量级失控。
- **子运行继承父的工具清单**：`BusinessToolContext` 只带 `platform_id`/`agent_id`，父的 MCP 工具自带 `server_id` 与 `side_effect`，继承即权限放大；而子 Agent 自己绑定的工具才是它被授权的能力。
- **子运行内允许 MCP/宿主工具**：无人值守路径没有渠道把确认弹给人，二者默认 `side_effect="external"`（`mcp/models.py:56`、`host_tool/models.py:34`），只剩「静默批准」或「不可用」，而静默批准等于让模型一句话绕过平台权限边界。
- **为「可被派」新增白名单表 + 管理 UI**：v1 取「同平台 + 已发布」已把面收敛到「同平台内 + 子运行工具被收缩」，新增一张表 + 一套 CRUD + 前端分区的代价与收益不成比例。
- **子运行共用父的 `conversation_id`**：`Conversation` 有 `ck_conversations_exactly_one_principal`，且共用会话会让父子消息混进同一条历史，违反「每轮新建会话、执行记录可精确回溯」的既有口径。
- **子运行事件以层级标识复合进父 SSE/WS 流**：`gateway/replay.py` 是每会话单条 Redis Stream（`key=f"agent:events:{conversation_id}"`、TTL 900s、maxlen 1000），混流会挤掉父事件并让 `Recovered=False` 成为常态；`conversation/router.py` 的 `sequence` 还是每连接自增的局部变量。
- **子运行结果拼成一个字符串回父模型**：模型无法区分哪个子任务失败，也无法据 `status` 决定重试或换人；改为结构化数组。
- **深度 ≥2 的递归委派**：需要收敛证明与不确定的 token 上界，与显式深度闸冲突；v1 靠「子运行工具清单不含 `delegate_tasks`」硬性排除。
- **子运行过程实时回灌 UI**：要复活一个无生产实现的持久化通道（`AgentRunPersistence` 生产恒为 `NullAgentRunPersistence`），v1 用「结束后从读侧读回」替代。
- **复用 `agent_loop_steps.parent_step_id` 承载父子关系**：该列（`conversation/models.py:115-117`，comment 写「用于重试或派生步骤」）是自引用且全仓零写入，把跨运行的父子关系塞进它会让「一次扇出的多个子运行」失去天然分组键；父子关系落在运行上更直接。该列本次不动。

## 停点判断

- 架构边界变化：**是**——新增「运行期由模型派生并发子运行」这一执行形态；`agent_loop_runs` 首次出现父子树；在 `agent_runtime` 之外新增一个自建并发池。
- 数据模型变化：**是**——`agent_loop_runs` 新增 `parent_loop_run_id` 一个可空自引用外键（新迁移）。
- API 契约变化：**是**——内置工具目录新增 `delegate_tasks`（描述按平台注入可派清单）；loop 读取投影新增 `delegatedRuns`。
- 鉴权与权限行为变化：**是**——子运行的工具范围被强制收缩；`delegate_tasks` 的可用性由 `agent_builtin_tools` 绑定决定。
- 缺少关键资料无法比较方案：**否**——本机 Pi 的示例扩展给出派生/隔离/上限/回流的完整口径，另有 4 个成熟实现的横向对照。

→ `approval.required: true`

## 变更点

**数据模型与迁移**
1. 新增迁移 `apps/backend/migrations/versions/20261015_0038_agent_delegated_runs.py`（`revision="20261015_0038"`、`down_revision="20261014_0037"`），`upgrade()` 写中文 docstring：给 `agent_loop_runs` 加一列 `parent_loop_run_id`（可空自引用 FK→`agent_loop_runs.id`、`ondelete="SET NULL"`、index、中文 comment「父运行 ID：非空表示这是一次被派生的子运行」）。**「同一次扇出」的分组键不另加列**，改记在父工具步骤的 `step_metadata.delegatedRunIds`（见变更点 9 的实现偏差）。`downgrade()` 逆序删列与索引。
2. `apps/backend/app/modules/conversation/models.py`：`AgentLoopRun` 加同名 `mapped_column`（中文 comment）；不新增表，`agent_loop_steps` 不动。

**新增工具**
3. `apps/backend/app/modules/tools/business/delegate_tasks.py`（新）：`@business_tool(name="delegate_tasks", ...)`，`input_schema` 为 `tasks` 数组（1~8 项，每项 `agent`(slug)+`task`，`additionalProperties: false`）。**参数级校验**（任务数区间、slug 去重、slug 必须是本平台已发布 Agent）不通过 → 整体抛 `BusinessToolError`（`tools/business/framework.py:14`）且不创建任何子运行；**运行级**每子任务独立成败 → 返回 `{"tasks":[{"agent","status","output"|"error"}],"succeeded","failed"}`。并发用 `asyncio.Semaphore(settings.delegation_max_concurrency)`，每个子运行套 `asyncio.wait_for(..., timeout=settings.delegation_timeout_seconds)`。**每个子运行独立 Session**（`async with get_session_factory()() as child_session:`）——绝不能复用 `ctx.session`（流式运行时它是网关正在 flush/commit 的 AsyncSession，并发复用会撞 asyncpg 并发错误；先例见 `builtin_tool/services.py` 的 `get_runtime_info` 特例与 `workflows/runner.py:647 _run_agent_step` 自开两个 Session）。
4. `apps/backend/app/modules/tools/business/registry.py`：import 新模块（导入即注册；`builtin_tool/registry.py:103-107` 会自动并入 `BUILTIN_TOOL_REGISTRY`，无需改目录代码）。
5. `apps/backend/app/modules/tools/business/framework.py`（**不是 `builtin_tool/framework.py`**）的 `BusinessToolContext` 新增 `loop_run_id: int | None = None`；`conversation/tool_dispatch.py:53 build_tool_invoker` 新增 `loop_run_id_provider: Callable[[], int | None] | None = None`（**沿用既有 `conversation_id_provider` 的 provider 模式**——loop 行在 `build_tool_invoker` 之后才创建，只能延迟取值），由 `builtin_tool/services.py` 的 `invoke_builtin_tool` 透传。

**子运行入口**
6. `apps/backend/app/modules/conversation/services.py` 的 `execute_unattended_chat` 新增关键字参数 `allow_delegation: bool = True`、`platform_tools_only: bool = False`、`parent_loop_run_id: int | None = None`、`max_iterations: int | None = None`（**实现期去掉了 `parent_step_id`**，见变更点 1）。`parent_loop_run_id` 经 `build_loop_with_steps`（`create_loop` 走 `**values`）落库；`max_iterations` 一路透传到 `build_langchain_runtime(max_turns=...)`（`_run_execute_chat_model_round`，默认为 `settings.agent_max_iterations`）。`allow_delegation=False` 时**剔除 `delegate_tasks`**、`platform_tools_only=True` 时**剔除 MCP 工具**（实际落点见变更点 7）。`delegate_tasks` 的 handler 调子运行时固定传 `allow_delegation=False, platform_tools_only=True`——**深度恒 1 与工具范围收缩都在这一处断掉**（理由同 `workflows/runner.py` 的 `allow_orchestration=False`：「递归必须在这里断掉，而不是靠『用户别这么配』」）。
7. `apps/backend/app/modules/conversation/runtime.py` 的 `load_runtime_context` 新增 `allow_delegation: bool = True` 与 `platform_tools_only: bool = False`：前者决定是否把 `delegate_tasks` 放进 `context.builtin_tools`；后者**在本函数内直接把 `mcp_tools = []`**（实现偏差：原本计划由调用方剔除 `context.mcp_tools`，改成在这里断掉，REST/WS/无人值守三条路径天然一致，`build_runtime_tool_list` 一个字不用改）。为 `delegate_tasks` **替换一份带平台可派清单的定义**（静态 `@business_tool` 描述无法按平台变化）：查本平台已发布 Agent 的 `(name, slug)`（按 slug 排序、上限 `settings.delegation_max_agents_in_prompt`）拼进工具描述；清单查询失败只记 warning 并退化成空清单（清单只是提示，不该让整轮对话失败）。

**父侧接线**
8. 三个装配点把 `loop_run_id` 交给内置工具的 `BusinessToolContext`：REST 非流式与流式共用 `conversation/router.py:_prepare`（一处覆盖两条路径）、Embed WS 走 `gateway/dispatcher.py` 的 `RuntimeToolDispatcher` builtin 分支（**Embed 链路不经 `build_tool_invoker`**）。实现偏差：provider 读的是 `RuntimeContext.loop_run_id` 这个 cell（沿用既有 `context.conversation_id` 的「运行记录创建后回填上下文」口径），各装配点只多一行 lambda，无需把 sink/cell 穿进 router/execute_chat/stream_chat 的签名；未回填时返回 `None`（行为与改造前一致）。
9. `delegate_tasks` 通过内置工具结果的保留键 `_metadata` 把 `{"delegatedRunIds": ["<子 loop id>", …]}` 交给 `ToolOutcome.metadata`（`agent_runtime/contracts.py`；`builtin_tool/services.py:_outcome_from_result` 摘出该键，回给模型的 result 里不含它），再由 `conversation/runtime.py:tool_step_values` 落进**父工具步骤**的 `step_metadata`（实现偏差：原计划写成 `delegated_runs: [{…}]` 对象数组，实际是 `delegatedRunIds` 字符串数组，且只在非空时写入，保证未使用该通道的工具落库形状逐字不变）。回给父模型的文本仍是 `{agent,status,output|error}` 数组，且每个 `output` 截断到 `settings.delegation_output_max_bytes`（默认 51200，对齐 Pi 的 `PER_TASK_OUTPUT_CAP`）。

**配置**
10. `apps/backend/app/core/config.py` 的 `Settings` 新增 6 项（均带默认值、走环境变量）：`delegation_max_iterations`(8)、`delegation_max_tasks`(8)、`delegation_max_concurrency`(4)、`delegation_timeout_seconds`(300)、`delegation_output_max_bytes`(51200)、`delegation_max_agents_in_prompt`(50)。`delegation_max_iterations` 作为子运行的 `max_turns` 传进 `build_langchain_runtime`（**不沿用 `agent_max_iterations`**）。

**读侧与前端**
11. 两份 `build_loop_payload` 都新增委派字段（它们是**不同**的投影，不能互相替换）：`apps/backend/app/modules/conversation/serializers.py`（多带 `inputSummary`，供 embed 快照/后台会话记录）与 `apps/backend/app/modules/conversation/services.py:92`（多带 `skillVersion`，供 REST 非流式响应与任务详情）。共用 `serializers.py` 的公开辅助 `delegated_run_ids(step)` 与 `load_delegated_runs(repo, loop_run_id)`（`repo.list_child_loops(parent_loop_run_id)` → `{id, agentSlug, agentName, status, summary, conversationId}`），`delegatedRuns`/`delegatedRunIds` 非空才出现。任务侧另加映射：`apps/backend/app/modules/tasks/schemas.py` 的 `TaskRunDelegatedRun`（camelCase）与 `TaskRunStepRead.delegatedRunIds`，`tasks/services.py:get_run_detail` 从同一投影取（无子运行时为 `NULL` → 前端静默不渲染）。
12. `apps/ai-sdk/src/core/types.ts` 与 `apps/ai-sdk/src/history/types.ts` 加 `delegatedRuns` 类型；`apps/ai-sdk/src/ui/components/AgentLoopStepCard.vue`（含 `AgentLoopPanel.vue`）在工具步骤下做**只读展开**；`apps/front/src/api/task.ts` 与 `apps/front/src/features/tasks/task-detail-page.tsx` 同步类型与展示（`delegatedRunIds`/`delegatedRuns` 允许 `null`）。运行中不显示子进度。

**测试与验证**
13. `apps/backend/tests/conversation/test_delegated_runs.py`（新）：父子落库与回溯、深度恒 1（断言子运行工具清单无 `delegate_tasks`）、工具范围收缩（MCP 工具不可用）、参数级整体拒绝 vs 运行级逐个回传、并发闸与任务数上限、超时、级联取消、输出截断、`agent_builtin_tools` 未绑定即不可见。
14. `apps/backend/tests/agent_runtime/test_loop.py` 补用例：父 loop 仍串行执行工具；`delegate_tasks` 失败不影响同一消息内其它工具。
15. `tools/harness/verify/2026-10-15-delegated-subagent-runtime.sh`：含迁移 up/down、外键动作（`SET NULL`）、真实并发时间窗、并发/深度/任务数超限报错、SSE 契约零改动回归。

**文档**
16. `docs/adr/0005-delegated-subagent-runtime.md`（新 ADR，逐条回应 ADR 0002「先声明式后多 Agent」与 ADR 0004 的推迟理由）、`CONTEXT.md` 新增术语（委派工具 / 子运行 / 委派深度 / 可派智能体）、`docs/CHANGELOG.md`。

（注：`migrations/env.py` 无需改动——`conversation` 已在 import 列表中。）

## 验收标准

1. `poetry run pytest tests/conversation tests/agent_runtime tests/workflows tests/tasks -q` 全绿；`poetry run ruff check .` 与 `poetry run black --check .` 通过。
2. 迁移可逆：`alembic upgrade head` → `downgrade -1` → `upgrade head` 均成功；`agent_loop_runs.parent_loop_run_id` 在两种方言下都建出正确外键动作（`SET NULL`）。
3. 动态扇出：父 Agent 一次 `delegate_tasks` 派 3 个子任务 → 库里出现 3 条 `parent_loop_run_id` 相同的子运行，各带独立 `conversation_id`，且三条会话的 `agent_id` 分别是三个子 Agent。（实现期修正：原稿要求 `model_usage_records.agent_id` 分别是三个子 Agent，但用量行只在 Embed 网关链路写入——`app/modules/gateway/runtime.py:509` 是仓里唯一调用 `record_model_usage` 的地方，无人值守/委派链路本就不写，故该判据改由 `conversations.agent_id` 承担。）
4. 真并发：3 个子运行的时间窗重叠（并发闸为 4）；把并发闸配成 1 后窗口不重叠。
5. 深度恒 1：断言子运行的运行时工具清单里**没有** `delegate_tasks`（子 Agent 即使绑定了该工具也无法再派生）。
6. 工具范围收缩：子运行里 MCP 工具不可用（`tool_not_available`），平台内置/业务工具与技能脚本工具可用。
7. 失败语义：任务数超上限 / slug 不存在 / slug 非本平台已发布 → 该次调用整体返回参数错误且**不产生任何子运行**；单个子运行失败不中止其余，父模型收到该任务的 `status="failed"` 与稳定错误码。
8. 取消与超时：父请求取消 → 子运行被中断并落为终态（非 `running`）；单个子运行超过 `delegation_timeout_seconds` → 该子任务返回超时失败且其余不受影响。
9. 可见性与回归：未绑定 `delegate_tasks` 的 Agent 与改造前**逐字一致**（工具清单、SSE 事件序列、`agent_loop_runs` 行数不变）；绑定后读侧能读回 `delegatedRuns`，`apps/front` 构建与 `apps/ai-sdk` 类型检查通过。
