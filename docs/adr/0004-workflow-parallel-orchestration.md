# 工作流定义升级为 DAG（扇出/汇聚 + 每步异构 Agent），Agent 绑定编排接管会话，模型自主委派继续后置

## Status

accepted

关联 Harness request：`2026-10-14-multi-agent-orchestration`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-14-multi-agent-orchestration/`）。

## Decision

**定义升级为 DAG，边由依赖编译。** `workflow.definition.nodes[]` 每个步骤新增 `depends_on`（步骤 id 数组）；`edges[]` 不再是独立事实，而是 `validators.compile_definition` 由 `depends_on` 编译出的产物，运行期只读 `steps`。兼容规则是整个改动的地基：`depends_on` **缺省 = 依赖序列中的前一个步骤**，存量线性定义因此零改动；显式 `[]` = 起点（并行分支的第二条及之后靠它声明）。运行前的 `validate_definition` → `_validate_edge_consistency` 再校验一次库内定义：`edges[]` 必须与 `depends_on` 推导出的边集一致，避免「画布上一张图、跑起来按另一个图」。

**分层调度：同层并发、跨层串行。** `validators.execution_layers()` 按「尽早开始」分层（一个步骤出现在它全部依赖都完成的第一层），`runner.execute_steps()` 对每层 `asyncio.gather`、层间等待。`outputs` 从「逐步就地写同一个 dict」改为「主协程收各步返回值后合并」，且传给同层步骤的是浅拷贝——保存期已保证引用只能指向祖先（必在更早的层），浅拷贝把「只读」从约定变成结构保证。

**失败默认 fail-fast，但先等同层已启动的分支收尾。** `gather(..., return_exceptions=True)` 收齐本层全部终态、再判定并抛 `StepFailedError`。不直接取消的理由是：同层分支要么已经产生工具副作用、要么正在产生，取消会让副作用停在不确定状态，也会让步骤记录永远停在 `running`——「收齐再抛」才让运行记录可复现。「出错即停」也是主流默认（Dify 的 `none`、GHA 的 `strategy.fail-fast: true`，见 `docs/design/agent-workflow-orchestration-research.md`）；本次与它们的差别只在收尾方式——先等同层已启动的分支收尾再抛。`continue_with_default` 仍逐分支生效（落 `on_error_applied=True`）。

**每步独立会话，不新增隔离机制。** Agent 步骤照旧调 `conversation/services.py::execute_unattended_chat`，它以 `conversation_id=None` 每次新建会话，每步天然上下文隔离。这既是 ADR 0002 说过的「多步相对一条长提示词的核心收益」，也是本次不为并行分支另造隔离的原因；分支异构（每步自带 `agent_id`）复用同一能力，无需新机制。

**两级并发闸，与运行级闸正交。** 保存期 `validators.MAX_PARALLEL_BRANCHES = 8` 限单层最大宽度；运行期 `runner.MAX_PARALLEL_STEPS = 4`（`asyncio.Semaphore`）限一条 run 内同时执行的步骤数。二者与 `tasks/scheduler.py::MAX_CONCURRENT_RUNS = 5` 正交：那个限「同时几条 run」，这两个限「一条 run 内几步并发」。没有闸时 N 条 run × M 个分支会瞬间打出 N×M 个模型请求。

**单步超时本次接上。** `timeout_seconds` 此前已写进 node 却从未被 runner 读取，现在包在 `_run_agent_step` / `_run_tool_step` 外层 `asyncio.wait_for`；整条 run 的 `asyncio.wait_for` 与 `fail_running_steps` 收尾语义不变。

**Agent 绑定放 Agent 侧。** `agents.orchestration_workflow_id`（可空 FK→`workflows.id`，`ondelete=SET NULL`，迁移 `20261014_0037_agent_orchestration_binding.py`）。放 Agent 侧而非 Workflow 侧，是因为 `Workflow.agent_id` 是 Workflow→Agent 方向的 **NOT NULL** 外键（「这条工作流默认用哪个 Agent 执行」），反向绑定在 Workflow 行上无处安放；而仓库里不存在「已发布工作流」这个概念，也就没有「只有已发布才能被绑定」这类过滤可写。绑定语义 = 该 Agent 的每一轮用户消息都由这条工作流接管，汇聚步骤（`runner.terminal_step_id()`：没有任何步骤依赖它的终态步骤；多个汇合点时取定义位次最大者）的输出即当轮 assistant 回复。`SET NULL` 让工作流被删时 Agent 退回普通单 Agent 对话，而不是整个 Agent 不可用。

**接管必须显式切断递归。** `execute_unattended_chat` / `execute_chat` / `stream_chat` 与 `gateway/runtime.py::stream_embed_chat` 新增 `allow_orchestration: bool`，工作流的 Agent 步骤与任务链路一律传 `False`。否则「工作流的 Agent 步骤 → execute_unattended_chat → execute_chat → 再次接管」会无限套娃。用显式参数而不是「靠调用栈判断」：编排入口本身就要从会话层进入，隐式判断在 REST/SSE 与 embed WS 两条装配点上必然漂移。

**会话内触发强制 `UnattendedPolicy(auto_approve=False, strict_approval=False)`，忽略工作流自身的两个开关。** 一条 `trigger_kind="conversation"` 的 run 由终端用户的一条消息直接触发且每轮都跑；若沿用工作流上为定时批量任务配置的 `auto_approve`，终端用户就能借一次对话拿到本该人工确认的副作用。只读能力不受影响：`side_effect="none"` 的工具本就不走 decider。

**「同一工作流最多一条 running」的部分唯一索引放宽谓词**为 `status='running' AND trigger_kind <> 'conversation'`（PostgreSQL 与 SQLite 两方言都写 `where`，否则 sqlite 退化为全表唯一）。原约束保护的是「定时/手动触发不重叠」；会话接管是每轮消息一次的高频触发，多个会话同时对话是常态，若也串行，后来的会话会被改写成 `skipped`——用户的消息直接蒸发。

**编排产出复用同一套 `AgentEvent` 事件流。** `workflows/orchestration.py` 只把一轮消息翻译成一条 `trigger_kind="conversation"` 的 run（先落 `running` 再执行，终端用户因此能看到「卡在哪一步」），对外产出与模型流式同形的 `AgentEvent`：整段 `message_delta` + `completed`，失败转 `error` 事件而不抛出（SSE 入口把异常当连接错误，而这里的失败是一条正常结果）。下游 `stream_runtime_as_conversation`、SSE 序列化与 assistant 落库零改动。模块边界沿用 ADR 0002：`orchestration.py` 不 import `conversation`，会话侧的反向调用点用函数内延迟导入，避免 `conversation` ↔ `workflows` 成环。

## Considered Options

- **先做多 Agent（模型自主委派），工作流后置**（ADR 0002 的否决项）：本次**部分打开**。开门的是「声明式并行编排」——扇出/汇聚、每步可指定不同 `agent_id`，执行图与并发度在定义里、可静态校验、可复现；仍然关闭的是「模型自主委派」：让模型在运行期决定派生哪些子 Agent、生成多少分支，仍是不可预测、难排错、成本不可控，且解决不了「固定流程要确定性执行」。因此阶段二不与本次合并，另开 request。
- **把并行写在模型提示词里让它自然循环**：被对照的六个实现（Temporal / LangGraph / n8n / Dify / Airflow / GHA，证据表见 spec）没有一个把并行交给自然语言——要么在定义里声明依赖（Dify / n8n / GHA / Airflow），要么写成代码（LangGraph / Temporal），都是静态可读、可校验的结构；且并发上限在它们那里**一律是显式配置项**（Dify 10 / Airflow 32+16 / Temporal 2000 / GHA 256）。本机 Pi 的 subagent 扩展也只是「起独立进程、只回传子进程最后一段 assistant 文本」，收益是上下文隔离而非可编排的并行能力。交给模型等于没有静态校验、没有并发上限、失败无法归因（Pi 连过程都丢），画布也无法回显。
- **用 `input_bindings` / 字符串模板隐式推导依赖**：画布无法稳定往返（改一次引用就悄悄改了拓扑），静态校验失去唯一事实源；「引用只能指向前面的步骤」若用模板实现还得自写解析器，语法一演化即成兼容负担（ADR 0002 已记同一理由）。
- **fork/join 容器节点**：表达能力与 `depends_on` 等价（fork = 多条同源边，join = 多条入边），代价是新增节点类型 + 嵌套作用域 + 汇合规则，validators / runner / 前端全线重写。
- **把绑定放 Workflow 侧，或塞进 `AgentVersion.capabilities`**：Workflow 侧无处安放（`Workflow.agent_id` 是 NOT NULL 的反向外键）；`capabilities` 已被附件能力独占且无校验，用它表达「指向一条工作流」等于用无约束 JSON 承载一条需要 FK 与同平台校验的关系。
- **每次会话只跑一次编排 / 只有首轮接管**：多轮语义不一致——第二轮起同一 Agent 突然变回普通单 Agent，用户看到的回复随轮次换一套引擎，排错时无从解释。用户明确选择每轮接管。
- **让父运行把子运行当工具同步等待**：与既有 `agent_loop_runs` 的 loop 等待态、`max_turns` 预算与入口超时三条机制同时冲突；它要求的「运行期动态生成分支」也正是本次明确不做的动态扇出。
- **自动拼接所有分支输出注入下游**：排布、截断、概括规则会变成隐式约定，难复现难排错；改为显式汇聚步骤，`terminal_step_id()` 的输出即回复。
- **给 Agent 加 `run_workflow` 工具（模型自主触发工作流）/ 意图路由（系统自行判断用哪条工作流）**：都属于阶段二的自主委派面，不可预测，与「先声明式」冲突。
- **动态扇出（运行期按数组展开分支数）/ 条件分支与 `fail_branch` / 工作流级变量**：分别需要运行期分支创建与部分失败语义、变量作用域与汇合语义三条规则、变量声明节；都超出本阶段，留给新 request（`fail_branch` 与 `source_handle` 的占位沿用 ADR 0002）。
- **新建「分支组」列**：`workflow_step_runs` 已有 `step_id`/`seq`/`status`，并行信息可由定义快照 + 时间戳还原，无需新 DDL；本次只补 `(run_id, step_id)` 唯一索引，兜「并行下同一 run 内 step_id 重复」。
- **会话内触发时复用 `UnattendedPolicy` 自动批准**：该 policy 的 `approved_count`/`decisions`（`apps/backend/app/modules/tasks/unattended.py`）是普通实例属性，并行分支共享同一实例会竞态；且「终端用户在场却自动批准」语义自相矛盾。
- **自研 SVG 画布 / 只在保存期静态校验工具副作用白名单**：前者拖拽、坐标、连线、缩放、小地图的工程量远超后端 DAG 改造本身，改用 `@xyflow/react`；后者盖不住运行期才组装的工具集，改为运行期 decider 拒绝。

## Consequences

- **`fail_branch` 与 `source_handle` 仍是占位**：v1 的 `edges` 全部 `source_handle: "default"`；条件分支要同时补齐变量作用域、汇合语义与失败传播三条规则，届时以新 request 处理（与 ADR 0002 同一笔欠账）。
- **`Workflow.version` 只增不减、无版本表与回滚入口**：本次只把 `definition` 与 `workflow_step_runs.seq` 的字段注释改为 DAG 语义（`seq` 语义由「执行顺序」变为「定义位次，只用于稳定排序展示」）。日后要「回滚到上一版」或「按指定版本重跑」，需新增版本表并把 `workflow_runs.definition_version_id` 从整数升级为外键；历史 run 自带快照，仍能解释自己，不会返工。
- **`workflow_step_runs` 新增 `(run_id, step_id)` 唯一索引是加约束**：线性执行时「一步骤一条记录」由循环天然保证，并行下只能靠数据库兜底。升级前若库里已有同 run 内重复 `step_id` 的脏数据，迁移会失败，需先清理。
- **DAG 之后「工作流级变量」仍不支持**：数组选择器把表达力收紧为「只能引用上游步骤的输出」，跨分支共享可变状态只能经汇聚点传数据；要支持共享变量需新增变量声明节，而不是放宽选择器语法。
- **编排接管的一轮没有逐 token 流式**：汇聚步骤必须等全部分支产生终态才能开始，输出只可能在末尾成形，因此对外是一条整段 `message_delta`——终端用户看到「过程照常、回复一次性出现」。若日后要流式，需重新定义「汇聚步骤何时可以开始产出」。
- **`trigger_kind="conversation"` 的运行不参与「同一工作流串行」的部分唯一索引**：这是为「两个会话并发消息不互相改写成 skipped」付的代价——同一工作流的会话内运行可以并存，资源叠加由 `MAX_PARALLEL_STEPS` 与「分支内只允许 `side_effect="none"` 的工具」共同承担，而不是由串行化承担。迁移的 `downgrade()` 因此有一条已知限制：库里若仍有 conversation 记录，还原后的唯一索引会创建失败，这是有意的（回滚要求先清理这些记录）。
- **模型自主委派（子 Agent 工具派生）未做，需要另开 request**。它要面对四个已确认的卡点，而不是「把 subagent 接上」这么简单：①`agent_loop_runs` 没有父子列，派生出的运行无法挂到父运行下；②事件流是单层线性的，父与子的事件无法在同一 `AgentEventType` 序列里区分归属；③`AgentRunPersistence` 没有生产实现，子运行的落库链路不存在；④审批 decider 无法安全继承——父运行的 `UnattendedPolicy` 是可变实例，共享会给并行子运行带来竞态（本次并行编排踩过的同一个坑）。
- **「画布连线 ↔ `depends_on`」的语义对应只被半保护**。后端只保证定义自洽：边由 `depends_on` 编译、`_validate_edge_consistency` 拒绝不一致的库内定义、`position` 被视为不透明坐标原样存回，**从不校验坐标与依赖的语义是否对应**。前端把 `null` 与显式数组的折算规则放在自己手里（`apps/front/src/features/workflows/workflow-dag.ts::resolveDependencies` / `toDependsOnWrite`，画布另有一份前端校验，从 `apps/front/src/api/workflow.ts` 取 `MAX_PARALLEL_BRANCHES`）。验证脚本用 `node --experimental-strip-types` 直接跑该模块的真实实现，覆盖「存量线性解析为链」「写回折成 `null`」「扇出-汇聚往返稳定」「非首步的并行起点保留 `[]`」「环被识别」；**未覆盖的是画布拖拽产生 `position` 与连线的交互路径**——`apps/front` 没有测试运行器（脚本只有 dev/build/lint/knip，devDeps 无 vitest/jsdom/playwright），也没有登录态联调环境。这条闸不是形式上的：它当场抓出了 `toDependsOnWrite` 拿前一步的**依赖**当判断基准（只有两步以内才成立）的错误，使任何三步以上的存量线性定义保存后都被改写成显式数组。看到「画布连线与执行顺序不符」时，先比对 `definition.nodes[].depends_on`，而不是怀疑后端分层调度。
