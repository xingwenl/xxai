# 工作流条件分支：独立的 `condition` 步骤、依赖边上的 handle 出口、到达触发汇聚

## Status

accepted

关联 Harness request：`2026-10-15-workflow-conditional-branching`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-15-workflow-conditional-branching/`）。它把 ADR 0004 里「条件分支与 `fail_branch` 留给新 request」这一条封账。

## Decision

**判定做成独立步骤类型 `condition`，不把条件挂到边上。** 一个条件步骤声明多个具名分支（`branches: [{name, when}]`），`when` 是结构化谓词；判定按声明顺序取第一个为真，且**必须**恰好一个 `when is None` 的无条件兜底分支并排在最后。条件步骤只带 `branches`——不允许 `prompt`/`tool_name`/`agent_id`/`input_bindings`/`tool_arguments`/`default_output`/`max_retries`/`timeout_seconds`，`on_error` 只能是 `abort`：判定是纯数据求值，不建会话、不调模型、不调工具、无副作用。做成节点而不是边上的条件，是因为「一次判定、多个出口」在边模型里只能拆成多条各带条件的边，判定就无法在画布上复用、也无法单测；`_validate_edge_consistency`（画布一张图、运行按另一张图）的保护则要整个重写。

**出口沿用既有的 `source_handle`，依赖条目升级为 `"<step_id>@<出口名>"`。** 不带 `@` 等价于 `@default`（存量定义零改动）。普通步骤的出口只有 `default`；声明 `on_error='fail_branch'` 的步骤多一个 `failed`；条件步骤的出口就是它的分支名。`compile_definition` 生成的边带 `source_handle`，`edge_id` 在 default 出口上仍是 `a->b`、具名出口上才是 `a:handle->b`——这样存量定义的边 id 逐字不变。保存期的边集一致性校验（`_validate_edge_consistency`）随之从 `(source, target)` 二元组升级为 `(source, handle, target)` 三元组，`_validate_edges` 的判据也从「出口是不是 default」改成「出口在不在该步骤的 `declared_handles` 里」。

**调度语义从「依赖全部成功才执行」改为「至少一条依赖边到达即执行」。** 每条依赖边在运行期解析为 `success` / `failed` / `skipped`：步骤在至少一条入边到达（success 或 failed）时执行，否则自身落一条 `workflow_step_runs.status='skipped'` 记录并跳过。跳过沿下游继续传播，因此汇聚步骤不必等齐所有分支——这是条件分支能收敛的前提。`run_workflow_run` 的终态判定、`terminal_step_id` 与 `retry_count` 语义都不变；`abort` 失败仍是 fail-fast（后续层不产生记录），`fail_branch` 失败则**不抛错**，只让 `@failed` 这条边到达。

**被跳过与走失败出口的上游，对下游按空字符串参与渲染与判定。** 运行期 `outputs` 里为每个「已判定」的步骤都写一条记录，跳过的写空串；`_render_text`/`_render_json`/`_resolve_selector` 与谓词求值取到的是同一份语义。理由：跳过是正常结果而不是缺失，如果渲染层还要区分「没输出」与「输出为空」，条件分支就会退化成「必须等所有分支到齐」。代价是「上游输出为空」不再是一个可被渲染层捕获的异常——要把它当异常，必须在谓词里显式写 `not_empty` 兜底。

**谓词是纯数据结构，保存期穷举校验。** 算子固定为比较类 `equals`/`contains`/`not_empty`/`matches` 与组合类 `all`/`any`/`not`；比较算子的左操作数必须是**恰好一个** `{{step_id.output}}` 引用且 `step_id` 必须是祖先步骤，右操作数是字面量；组合算子只吃 `children`（非空、≤16，`not` 恰好一个）。上限是显式常量：分支数 `MAX_CONDITION_BRANCHES=8`、谓词嵌套 `MAX_PREDICATE_DEPTH=4`、正则长度 `MAX_REGEX_LENGTH=200` 且必须能编译。这些规则在保存期全部拒绝而不是等到运行期：配置错误在凌晨的定时任务里才暴露是不可接受的。

**`fail_branch` 与条件出口共用同一套 handle 语义，因此本轮一起落地。** 失败步骤落 `status='failed'`、`on_error_applied=False`（如实记录这是一次失败而非被兜底吞掉），失败走隐式 `@failed` 出口，只有接 `@failed` 的下游执行、接 `@default` 的下游跳过，整条 run 仍以 `completed` 收尾。

**不新增 DDL、不新增迁移。** 跳过状态用既有的 `WorkflowStepRun.status='skipped'`，出口用既有的 `definition.edges[].source_handle`，定义结构仍在 `workflows.definition` 这个 JSON 里——三者都在既有承载范围内，spec 的「不做」一节据此排除了新表/新列方案。

## Considered Options

- **边上的条件（`edges[].condition`）**：判定散在边上，一个判定节点无法表达「一次判定多出口」，成功出口与失败出口会混进同一条边；且 `_validate_edge_consistency` 的「画布一张图、跑起来按另一个图」保护需要重写。条件步骤把判定收拢成一个可复用、可单测的节点。
- **表达式字符串（Jinja / Python 子集）**：表达力更强，但要自写解析器与沙箱，语法一演化即成兼容负担；ADR 0002 已以同一理由否决字符串模板引用。结构化谓词能在保存期把「未知算子、非上游引用、非法正则」全部拦下。
- **让模型判定分支**：不可预测、难排错、成本不可控，会给每层增加不可控的调用；与本仓库「先声明式」的既定顺序冲突，留作日后单独评估。
- **把分支出口落成新列（如 `workflow_step_runs.branch_name`）**：无须 DDL——出口在 `source_handle`、跳过在既有 `status`，加列会让「一次运行里每步的分支名」多一份会漂移的真相。
- **把「未命中任何分支」当作运行失败**：主流实现（n8n 的 Switch、LangGraph 的显式兜底）一律要求显式兜底出口；把配置错误推迟到运行期等于让定时任务在凌晨失败。
- **沿用「全部依赖必须成功才能执行」**：那样条件分支永远无法汇聚。Airflow 的 `BranchPythonOperator` 正是同一课题：未选中分支标记 skipped 并沿 DAG 传播，下游必须显式声明 `trigger_rule`（`none_failed_min_one_success` 等）才不会一起跳过；本方案的取舍是**默认就是「到达即执行」**，把 Airflow 那条需要手工声明的规则变成条件分支下唯一合理的默认。
- **让条件步骤调用模型或工具**：判定一旦有副作用就不再可静态校验，且每层多一次不可控调用成本。
- **把 `fail_branch` 留到以后**：它与条件出口共用同一套 handle 语义（声明、校验、调度、画布四处），分开做等于每处改两遍。
- **为条件分支引入运行期动态调度（按实际到达的边临时决定下一层）**：`execution_layers` 的静态分层是 ADR 0004 已封账的结构，动态调度要把「尽早开始」换成运行期重算拓扑；本方案的「静态分层 + 层内到达判定」已足以表达条件分支，代价见 Consequences 的并发宽度一条。
- **循环 / foreach 一并做**：需要运行期拓扑生成与部分失败语义，超出本轮。
- **条件谓词读同层并行分支的输出**：与既有「引用只能指向祖先」的结构保证冲突（同层互不可读，Dify 同样不允许并行分支互读变量）。

## Consequences

- **「跳过不阻塞下游」成为所有汇聚步骤的默认语义，不再有「等齐所有分支」的开关。** Airflow 那套 `trigger_rule` 的表达力本次不引入；要「等齐」只能在定义里让汇聚步骤依赖具体的成功出口（`a@default`）而不是整条分支。
- **分支后不补显式汇聚步骤时会有两个 sink，`terminal_step_id` 在 sink 不唯一时回退到定义里的最后一个步骤。** 于是 Agent 编排接管模式（`execute_orchestration_run` 取 `terminal_step_id` 的输出当轮回复）可能取到**被跳过**的那条分支，回复变成空串。这是本轮最容易踩到的一处，**推荐模式是分支之后补一个显式汇聚步骤**；这条限制写在这里而不是留给用户自己发现。日后若要根治，需要给「多 sink」定义一个显式语义（例如全部 sink 输出拼接或强制声明出口），那是一次 API 契约变更。
- **`execution_layers` 仍是静态分层，并发宽度按「定义宽度」而非「运行宽度」算**：条件分支不会减少同层并发（`MAX_PARALLEL_BRANCHES=8` 的保存期校验也按定义算）。运行期靠 `MAX_PARALLEL_STEPS=4` 的并发闸兜住实际开销，被跳过的步骤根本不进 `asyncio.gather`，因此不占闸。
- **被跳过的步骤对下游读作空字符串**：这是「跳过不是错误」的直接代价。用户若把「上游没有输出」当成异常，必须在谓词里显式写 `not_empty` 兜底分支，而不是指望运行期报错。谓词求值本身不抛错，只有算子未知这类定义期问题才会抛（保存期已拦）。
- **条件步骤不建会话、不调模型，因此 `model_usage_records` 里没有它的行**：按步骤统计 token 时条件步骤会显示为 0，这是预期而非漏记。
- **两条既有测试被有意改写，不是回归**：`apps/backend/tests/workflows/test_validators.py` 的 `test_validate_definition_rejects_non_default_source_handle` 改名为 `test_validate_definition_rejects_an_outlet_the_step_never_reaches`（判据从「是不是 default」升级为「是不是 `declared_handles`」），`test_validate_steps_accepts_fail_branch_enum_without_implementing_it` 改名为 `test_validate_steps_accepts_fail_branch`（`validators` 里那份与 `ON_ERROR_STRATEGIES` 重复的 `IMPLEMENTED_ON_ERROR_STRATEGIES` 已删除，`fail_branch` 由 runner 真正实现）。
- **上限都是显式常量**：`MAX_CONDITION_BRANCHES=8`、`MAX_PREDICATE_CHILDREN=16`、`MAX_PREDICATE_DEPTH=4`、`MAX_REGEX_LENGTH=200`。放开任何一个都要重估「保存期可穷举校验」这条前提（尤其深度：`all`/`any` 可以互套，无界即是递归炸弹）。
- **前端与后端各有一份结构校验**（`workflow-dag.ts` 的 `validateDag` 与 `validators.py`），本轮的取法是两边规则集合对齐、后端为准；前端只做「保存前把用户拦下来」，任何一边单独改动都会让「界面上过得去、保存被打回」重现，改动时必须成对改。
- **谓词落库前要归一化掉「值为 `null` 的 `children`」**：请求里省略 `children` 时，`WorkflowStepInput.model_dump()` 会补出 `children: None`。若原样落库，读侧就拿到「有这个键、值是 null」的谓词，而编辑器正是用「有没有这个键」区分组合算子与比较算子的，于是把 `null` 当子条件列表用（`.map` 抛错 → 白屏）、保存校验还会误判成「比较算子带了子条件」。归一化在 `validators._validate_predicate` 里做（保存期唯一入口），读侧 `api/workflow.ts` 的 `toPredicate` 再兜一层以兼容本轮之前落库的旧行。
- **三处已知限制（本轮不做，已记在 verify.md 的未执行项里）**：①改分支名不联动下游 `depends_on`，改名后下游那条 `cond@yes` 变成不存在的出口，前后端都会拒绝保存并列出可用出口，用户需手删依赖再重连；②谓词正则的方言按各自引擎判定（后端 `re.compile`、前端 `new RegExp`），`(?P<n>x)` 这类 Python 独有的写法能过保存期但在编辑器里读不回去；③`removeEdges` 手写解析 `edge_id`（`indexOf('->')` / `':'`）与 `workflow-canvas-model.ts` 的 `edgeId()` 生成是两份实现，格式若改需同步。
