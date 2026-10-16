---
id: 2026-10-15-workflow-conditional-branching
tier: A
risk: high
approval:
  required: true
  granted: true
  granted_note: 用户在停点确认后继续实现（2026-10-15）
  why: ["架构边界变化：执行语义从「依赖全部成功才执行」升级为「按依赖边的到达状态执行」，被跳过的分支沿下游传播", "API 契约变化：WorkflowStepKind 新增 condition、WorkflowStepInput 新增 branches、depends_on 条目允许 <step_id>@<handle> 限定语法", "ADR 0004 把「条件分支与 fail_branch」明确留给新 request，本次封账；分档主动上调到 A 以补 ADR"]
---

## 目标与范围

一句话：给工作流加**条件分支**——把判定做成独立步骤类型 `condition`（结构化谓词、无模型调用、无副作用），把分支出口做成依赖边上的 `source_handle`，并让汇聚步骤按「至少一条依赖已到达」触发；被跳过的分支不再阻塞下游，而是沿下游传播。

给谁用：平台管理员在画布上编排条件流程（如「上游没有查到知识库结果就走兜底分支」）；工作流仍由定时任务、手动触发或 Agent 编排接管运行，终端用户无感。

**做**：
- 新增步骤类型 `condition`：声明多个具名分支，每个分支一个结构化谓词；**必须**恰好一个无条件兜底分支；判定按分支顺序取第一个为真
- 依赖限定语法：`depends_on` 条目写成 `"<step_id>@<分支名>"` 表示「只在该上游走这条出口时到达」；不带 `@` 等价于 `@default`
- 每个条件步骤只携带 `branches`，不允许 `prompt`/`tool_name`/`agent_id`/`input_bindings`，不建会话、不调模型
- 到达触发：每条依赖边解析为 `success`/`failed`/`skipped`；步骤在「至少一条依赖边已到达（success 或 failed）」时执行，否则自身记 `skipped`
- 跳过传播：未选中分支上的步骤落 `workflow_step_runs.status='skipped'`（每个步骤恰好一条记录），其下游继续按到达规则判定
- `fail_branch` 落地：步骤失败走隐式 `@failed` 出口，失败步骤记 `status='failed'` 且 `on_error_applied=False`
- 画布：条件节点按分支渲染多个 source handle、边带分支标签、属性面板内置分支与谓词编辑器、解锁 `fail_branch` 选项
- 文档与证据：ADR 0006、CONTEXT 术语、CHANGELOG、`tools/harness/verify/2026-10-15-workflow-conditional-branching.sh`

**不做**：
- 循环 / foreach（运行期按数组展开分支数）
- 变量声明节（跨分支共享可变状态仍只能经汇聚点传数据）
- 条件分支的「让模型判定」形态（把出口交给 LLM 选择）
- 表达式字符串（Jinja / Python 子集）
- 新增 DDL：不改 `workflows.definition` 结构之外的任何列，不新增迁移（`status='skipped'` 已在既有枚举与列注释里）
- 子工作流调用 / 跨工作流跳转

## 来源与方案比较

调研（2026-10-15，官方文档与本机源码）：

- **n8n 2.43.5**（https://docs.n8n.io/flow-logic/）IF 节点固定 true/false 两个出口，Switch 节点按规则多出口且**未命中任何规则时才走 fallback 出口**——兜底出口是定义的一部分。
- **Dify v1.17.1**（https://docs.dify.ai/ 工作流节点文档）有 if-else 与 question-classifier 两类判定节点；并行分支之间**不可互读变量**；节点错误三档 `None`/`Default Value`/`Fail Branch`，其中 Fail Branch 就是「让失败走一条独立出口继续」，与成功出口并列。
- **Airflow 3.4.0**（https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html）`BranchPythonOperator` **未选中的分支被标记 skipped 并沿 DAG 传播**；下游默认 `trigger_rule=all_success` 因此会被跳过阻塞，官方解法是按语义改用 `none_failed_min_one_success` / `all_done` / `one_success`——即「跳过不应阻塞汇聚」必须由汇聚侧显式声明。
- **LangGraph v1**（https://langchain-ai.github.io/langgraph/）`add_conditional_edges` 的路由函数返回节点名或 `END`，未命中要显式返回兜底节点，否则图跑到悬空。
- 横向结论：①判定主体一律是独立节点或显式路由，不做「边上的隐式条件」；②出口一律显式命名；③未命中一律要求兜底，配置错误在保存期暴露而不是运行期；④被跳过的分支不得阻塞汇聚，且跳过状态必须可观测。

**方案 A（选中）独立条件步骤 + 结构化谓词 + handle 限定依赖 + 到达触发汇聚。** 判定与执行分离，谓词保存期可完整校验、可穷举测试；出口靠既有 `source_handle` 承载，扩展点最少。

**方案 B 边上的条件**（`edges[].condition`）：判定散在边上，画布上一个判定节点无法表达「一次判定多出口」，成功出口与失败出口会混在同一条边上；且 `_validate_edge_consistency`「画布一张图、跑起来按另一个图」的保护需要重写。

**方案 C 表达式字符串**：表达力更强，但要自写解析器与沙箱，语法一演化即成兼容负担——ADR 0002 已以同一理由否决字符串模板引用。

## 被否决的选项

- **边上的条件（方案 B）**：判定无法在画布上复用与单测；一个上游要表达多个出口只能靠多条边各带条件，等于把节点语义拆散到边集合里。
- **表达式字符串（方案 C）**：需要解析器与沙箱，兼容与注入负担重；结构化谓词能在保存期把「未知算子、非上游引用、非法正则」全部拦下。
- **让模型判定分支**：不可预测、难排错、成本不可控，与本仓库「先声明式」的既定顺序冲突；留作日后单独评估。
- **把分支出口落成新表/新列**（`workflow_step_runs.branch_name` 等）：无须 DDL——定义在 `definition` JSON、出口在 `source_handle`、跳过在既有 `status='skipped'`，三者都在既有承载范围内。
- **把「未命中任何分支」当作运行失败**：主流实现一律要求显式兜底；把配置错误推迟到运行期，等于让定时任务在凌晨失败。
- **沿用「全部依赖必须成功才能执行」**：那样条件分支永远无法汇聚（Airflow 的 skipped 传播就是同一课），必须改为到达触发。
- **让条件步骤调用模型或工具**：判定一旦有副作用，条件分支就不再可静态校验，且会给每层增加不可控的调用成本。
- **把 `fail_branch` 留到以后**：它与条件出口共用同一套 handle 语义，分开做等于把校验、调度、画布三处各改两遍。
- **循环 / foreach**：需要运行期拓扑生成与部分失败语义，超出本轮。
- **条件谓词读同层并行分支的输出**：与既有「引用只能指向祖先」的结构保证冲突（同层互不可读）。

## 停点判断

- **架构边界变化**：是。执行语义从「依赖全部成功」变为「按依赖边到达状态执行 + 跳过传播」，这是调度层的语义变化，不只是加字段。
- **数据模型变化**：否。不新增列/表/索引，不新增迁移；`status` 的 `skipped` 取值与 `source_handle` 字段都已存在。
- **API 契约变化**：是。`WorkflowStepKind` 新增 `condition`；`WorkflowStepInput` 新增 `branches`；`depends_on` 条目允许限定语法；条件步骤的字段约束变严。
- **鉴权与权限行为变化**：否。条件步骤不产生模型与工具调用、不新建会话、不触碰执行身份与审批策略。

## 变更点

1. `apps/backend/app/modules/workflows/validators.py`：`STEP_KINDS` 增 `condition`；新增常量 `DEFAULT_HANDLE`/`FAILED_HANDLE`/`BRANCH_HANDLE_SEPARATOR`/`MAX_CONDITION_BRANCHES`/`PREDICATE_OPS`/`MAX_REGEX_LENGTH`；`resolve_depends_on` 解析 `<step_id>@<handle>`（保持「缺省 = 前一个步骤」不变）；`compile_definition` 生成的边带 `source_handle`、`edge_id` 形如 `src:handle->target`；`_validate_edges`/`_validate_edge_consistency` 改为比对三元组；`_validate_step_shape` 增加条件步骤的分支与谓词校验；`_ancestor_map`/`execution_layers` 按基础 step_id 计算拓扑；`execution_layers` 仍是静态分层。
2. `apps/backend/app/modules/workflows/runner.py`：层内先解析每条依赖边的到达状态，未到达的步骤落一条 `status='skipped'` 记录并跳过执行；到达的执行；失败路径新增 `fail_branch` 分支（记 `failed` 并让 `@failed` 边到达）；`terminal_step_id` 剥离 handle。
3. `apps/backend/app/modules/workflows/schemas.py`：`WorkflowStepKind` 增 `condition`；新增 `ConditionPredicate` 与 `ConditionBranch` 模型；`WorkflowStepInput` 新增 `branches: list[ConditionBranch] | None = None`，并在 docstring 写明 `depends_on` 的限定语法。
4. `apps/backend/app/modules/workflows/services.py`：`_validate_step_references` 跳过条件步骤（它没有 agent/tool 可校验）；其余保存顺序不变（先纯数据校验、再查库、最后 compile）。
5. `apps/front/src/api/workflow.ts`：`WorkflowStepKind` 增 `condition`；新增 `ConditionBranch`/`ConditionPredicate` 类型与 `BRANCH_HANDLE_SEPARATOR`；`WorkflowStep` 增 `branches`；`WorkflowStepOnError` 注释解除 `fail_branch` 的「暂未实现」。
6. `apps/front/src/features/workflows/workflow-dag.ts`：`resolveDependencies` 保留限定串、新增 `baseStepId`/`branchHandle` 助手；`validateDag` 扩展（未知分支名、重复分支名、缺兜底、多兜底、谓词引用非上游、`@failed` 用于非 `fail_branch` 上游、条件步骤字段冲突）；拓扑与环检测按基础 step_id 计算。
7. `apps/front/src/features/workflows/workflow-canvas.tsx` 与 `workflow-canvas-model.ts`：条件节点每个分支一个 source handle（`sourceHandle` id = 分支名）；`buildCanvasEdges` 输出 `sourceHandle`、`label` 与按分支区分的样式；`onConnect` 透传 `sourceHandle`。
8. `apps/front/src/features/workflows/workflow-definition-form.tsx`：`connectSteps(source, target, handle)` 写限定条目；属性面板新增条件分支编辑器（分支顺序 + 谓词字段 + 兜底项）；上游依赖选择器提供 `step@handle` 选项并标注 `@failed` 仅对 `on_error='fail_branch'` 的上游可见；`ON_ERROR_OPTIONS` 解锁 `fail_branch`；`toStepWrite` 输出 `branches`。
9. 新增测试 `apps/backend/tests/workflows/test_validators_conditions.py` 与 `test_runner_conditions.py`；`test_validators_dag.py` 补限定语法用例。
10. 文档：`docs/adr/0006-workflow-conditional-branching.md`（Decision / Considered Options / Consequences）、`CONTEXT.md` 新增术语（条件步骤、分支出口、到达触发、跳过传播）、`docs/CHANGELOG.md`。
11. 新增 `tools/harness/verify/2026-10-15-workflow-conditional-branching.sh`：迁移无新增（校验 `alembic current` 不变）、谓词真值表、跳过传播、到达触发汇聚、`fail_branch` 路由、保存期拒绝清单、兼容回归、前端 `tsc -b`/`vite build` 与 `workflow-dag.ts` 真实实现探针。

## 验收标准

1. `poetry run pytest tests/workflows -q` 全绿；`ruff check` 与 `black --check` 在本次改动文件上通过；既有 `tests/workflows/test_runner_parallel.py` 与 `test_validators_dag.py` 用例**一条不改**地继续通过。
2. 兼容：不含 `condition` 步骤、`depends_on` 无 `@` 的定义，保存后的 `definition.edges` 仍全部 `source_handle='default'`，运行后的步骤集合与状态与改造前逐字一致。
3. 条件判定：`equals`/`contains`/`not_empty`/`matches` 四个算子与 `all`/`any`/`not` 组合的真值表通过；多分支命中时取定义顺序第一个；未命中走兜底分支。
4. 跳过传播：未选中分支上的步骤落 `status='skipped'`，每个步骤恰一条记录（`uq_workflow_step_runs_run_step` 不冲突）；其下游在全部依赖被跳过时同样跳过。
5. 到达触发汇聚：汇聚步骤在「至少一条依赖边已到达」时执行；只有一条分支到达时也能执行；全部依赖被跳过时自身跳过。
6. `fail_branch`：失败步骤落 `status='failed'` 且 `on_error_applied=False`；只有 `@failed` 出口的下游执行、`@default` 下游跳过；整条 run 仍以 `completed` 收尾。
7. 保存期拒绝（均 400 且不改动既有定义）：未知分支名、缺兜底或多兜底、分支名重复或非法、条件步骤带 `prompt`/`tool_name`、谓词引用非上游、谓词算子未知、正则非法、`@failed` 用在上游非 `fail_branch` 的依赖上。
8. 画布往返由 `node --experimental-strip-types` 直接跑 `workflow-dag.ts` 的真实实现覆盖（条件分支解析/写回/标签/环检测/跳过路径）；`apps/front` 的 `tsc -b` 与 `vite build` 通过。
