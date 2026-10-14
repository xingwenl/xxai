---
id: 2026-10-14-multi-agent-orchestration
tier: A
risk: high
approval:
  required: true
  granted: false
  why: ["架构边界变化：工作流从纯线性升级为 DAG，conversation 与 workflows 出现新的调用方向", "数据模型变化：agents 表新增编排绑定列 + 新增迁移；workflow definition JSON 形状扩展", "API 契约变化：definition 新增 depends_on/position；新增 Agent 编排绑定字段与端点", "鉴权权限行为变化：会话内触发路径下需审批工具由「无人值守策略裁决」改为「一律拒绝」"]
---

## 目标与范围

一句话：让 ai-base 的声明式工作流支持**扇出-汇聚（并行多智能体）**——一个步骤可被多个步骤同时依赖（并行分支），分支可各自指定不同 Agent，再汇聚到一个步骤；Agent 可绑定一个此类编排，使该 Agent 的**每一轮**会话消息都由编排接管，汇聚步骤的输出即当轮回复；后台提供画布编辑器。

给谁用：平台管理员/开发者定义编排；终端用户在 embed 会话里无感触发。

**做**：
- 工作流定义的扇出-汇聚：步骤显式声明 `depends_on: [step_id]`，由依赖编译出边
- 运行期 DAG 拓扑分层调度 + 同层并发 + 并发闸
- 分支异构：每个 Agent 步骤自带 `agent_id`（复用既有能力）
- Agent 绑定编排，会话每轮接管（带会话历史，输出即当轮回复）
- 画布编辑器（`@xyflow/react`），与既有表单属性面板共存
- 会话内触发路径收紧：需审批工具一律拒绝

**不做**：
- 模型自主委派 / 运行期动态生成分支（阶段二，另开 request）
- 条件分支、循环、动态扇出（按数组展开）、工作流级变量
- 分支级交互式人工审批
- 跨分支共享可变状态（只能经汇聚点传数据）
- 工作流级"已发布"概念与版本回滚（沿用 ADR 0002 的快照语义）

## 来源与方案比较

本次专程调研（2026-10-14，全部取自官方文档/官方仓库）：

| 来源 | 版本锚点 | 并行声明 | 汇聚 |
|---|---|---|---|
| Temporal | Server 1.33 | Activity/Child Workflow + Promise/Future | await 全部后自己归约；大规模用 MapReduce Tree |
| LangGraph | v1（JS 1.5.0） | 多出边同 superstep 并行 + Send API | 隐式 reducer（默认覆盖，合并需显式标注） |
| n8n | 2.43.5 | 画布分支，但**分支串行**执行 | 显式 Merge 节点（等全部输入到齐） |
| Dify | v1.17.1 | 画布并行连线 + Iteration（**上限 10**） | Variable Aggregator 仅互斥分支；并行须 Code/Template |
| Airflow | 3.4.0 | `.expand()` 运行期映射 | 下游任务即汇聚点，`trigger_rule` 决定语义 |
| GitHub Actions | 文档快照 | `strategy.matrix` 笛卡尔积 | 无 reducer，手工 `needs` + `outputs` |
| 本机 Pi | HEAD 4e69b0c | 示例扩展 `subagent/index.ts` 起独立进程 | 只取子进程最后一段 assistant 文本 |

链接：[Temporal parallel-execution](https://docs.temporal.io/design-patterns/parallel-execution.md)｜[LangGraph graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api.md)｜[n8n merge](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.merge.md)｜[Dify iteration](https://docs.dify.ai/en/cloud/use-dify/nodes/iteration.md)｜[Airflow dynamic-task-mapping](https://github.com/apache/airflow/blob/main/airflow-core/docs/authoring-and-scheduling/dynamic-task-mapping.rst)｜[GitHub Actions limits](https://docs.github.com/en/actions/reference/limits)

横向结论（用来定本方案的口径）：
1. 并行一律在**数据/图**层声明，没有一个是让模型在自然语言里自己循环的。
2. 并发上限**一律是显式配置项**，不是自适应（Dify 10 / Airflow 32+16 / Temporal 2000 / GHA 256 / Pi 4 并发·8 任务）。
3. 汇聚**一律显式**：要么显式汇聚节点，要么显式声明的 reducer/await。
4. **默认一律 fail-fast**（GHA `fail-fast: true`、Temporal `Promise.all`、n8n `On Error=Stop`、Dify `None`）；"部分失败也继续"必须显式选择。
5. **隔离默认、共享显式**：Dify 原文"并行分支不可互读变量"，跨分支只经汇聚点传数据。
6. 失败粒度对齐**可独立重试/观测的执行单元**；Pi 只回传最后一段文本会丢掉过程，故本方案保留既有 `workflow_step_runs` 的逐步落库。

方案比较：
- **方案一（采纳）**：把既有线性 `steps[]` 升级为**显式 `depends_on`**，边由依赖编译，运行时拓扑分层并发。
- 方案二（否决）：新增 `fork`/`join` 容器节点类型。
- 方案三（否决）：从 `input_bindings`/模板引用**隐式推导**依赖。

选方案一的理由：它在保留既有 `steps[]`、数组选择器、模板引用规则的前提下，把"线性"这一假设升级为"DAG"；存量定义因"缺省 `depends_on` 即前驱"而**零改动兼容**；画布连线与 `depends_on` 一一对应，可无损双向往返。

## 被否决的选项

- **方案二 fork/join 容器节点**：需新增节点类型 + 嵌套作用域 + 汇合规则，validators/runner/前端全线重写；表达能力与 `depends_on` 等价（fork=多条同源边，join=多条入边）。
- **方案三 隐式推导依赖**：把"并行"变成 `input_bindings`/模板的副作用，画布无法稳定往返，静态校验失去唯一事实源。
- **把阶段二（模型自主委派）并入本次**：`docs/adr/0002-workflow-orchestration-module-boundary.md` 已否决"先做多 Agent"，理由是自主委派不可预测、难排错、成本不可控，且仍解决不了"固定流程要确定性执行"。
- **会话内触发时复用 `UnattendedPolicy` 自动批准**：该 policy 的 `approved_count`/`decisions`（`apps/backend/app/modules/tasks/unattended.py:31`）是普通实例属性，并行分支共享同一实例会**竞态**；且"终端用户在场却自动批准"语义矛盾。
- **自动拼接所有分支输出注入下游**：排布/截断/概括规则会变成隐式约定，难复现难排错；改为显式汇聚步骤。
- **只在保存期静态校验工具副作用白名单**：Agent 步骤的实际工具集在运行期才组装，静态校验盖不住；改为运行期 decider 拒绝。
- **动态扇出**（运行期按数组展开分支数）：需新增运行期分支创建语义、长度上限与部分失败语义，超出本阶段。
- **条件分支与 `fail_branch`**：需同时补齐变量作用域、汇合语义、失败传播三条规则（ADR 0002 Consequences 已记）。
- **意图路由**（系统自行判断该用哪个工作流）：不可预测、难排错，与"先声明式"冲突。
- **只在会话首轮跑编排**：多轮语义不一致，用户已明确选择每轮接管。
- **自研 SVG 画布**：拖拽/坐标/连线/缩放/小地图的工程量远超后端 DAG 改造本身。
- **给 Agent 加 `run_workflow` 工具**（模型自主触发工作流）：属于阶段二的自主委派面。
- **新建"分支组"列**：`workflow_step_runs` 已有 step_id/seq/status，并行信息可由定义快照 + 时间戳还原，无需新 DDL。

## 停点判断

- 架构边界变化：**是**——工作流执行模型由线性序列升级为 DAG；`conversation` 与 `workflows` 之间出现反向调用。
- 数据模型变化：**是**——`agents` 新增编排绑定列（新迁移）；`workflow.definition` JSON 形状扩展。
- API 契约变化：**是**——definition 新增 `depends_on`/`position`；新增 Agent 编排绑定字段与端点。
- 鉴权与权限行为变化：**是**——会话内触发路径下，需审批工具由策略裁决改为一律拒绝。
- 缺少关键资料无法比较方案：**否**——6 个成熟案例 + 本机 Pi 已覆盖并发上限、汇聚、失败语义三处争议。

→ `approval.required: true`

## 变更点

**数据模型与迁移**
1. 新增迁移 `apps/backend/migrations/versions/<rev>_agent_orchestration_binding.py`（`down_revision="20261013_0036"`），`upgrade()` 写中文 docstring：①`agents` 加 `orchestration_workflow_id`（可空 FK→`workflows.id`、`ondelete="SET NULL"`、中文 comment）；②`workflow_step_runs` 补 `(run_id, step_id)` 唯一索引（现仅有非唯一的 `Index("ix_workflow_step_runs_run_seq","run_id","seq")`，`workflows/models.py:284`，DAG 下同一 run 内 step_id 重复在库层无人兜底）；③**重建** `uq_workflow_runs_one_running_per_workflow`(`workflows/models.py:156-167`)，谓词由 `status='running'` 改为 `status='running' AND trigger_kind &lt;&gt; 'conversation'`——否则同一 Agent 的多个会话并发接管会互撞唯一索引（`trigger_kind` 新增取值 `conversation`；双方言 where 都要写，否则 sqlite 退化为全表唯一）。
2. `apps/backend/app/modules/agent/models.py`：`Agent.orchestration_workflow_id` 字段（中文 comment）+ relationship；不改 `AgentVersion`。
3. `apps/backend/app/modules/agent/{schemas,services,repositories}.py`：绑定/解绑端点与**同平台校验**（只能绑本平台工作流；复用 `get_published_agent(agent_id, platform_id)` 的强租户口径，不用不限定平台的 `get_published_agent_by_id`）。
4. `apps/backend/app/modules/workflows/models.py`：`Workflow.definition` 的 comment（`:111-117` 现写"edges[] 顺序边"）与 `WorkflowStepRun.seq` 的 comment（`:301-303` 现写"执行顺序，从 0 开始"）同步改为 DAG 语义（拓扑序位次），三个字段 comment 均为中文。

**校验（保存期）**
5. `apps/backend/app/modules/workflows/validators.py`（改动量最大）：
   - `compile_definition`(`:74-110`)：node 增加 `depends_on`(`:84-98`)；edges 由依赖生成（`edge_id`/`source`/`target` 语义重定，保留 `source_handle="default"`）。
   - `steps_from_definition`(`:113-134`)：按 `seq` 排序(`:117`)改为按拓扑序位次还原。
   - `validate_steps`(`:137-220`)：把"只能引用排在前面的步骤"这一顺序遍历假设（`:218` 的 `seen.add`、`:269-273` 与 `:286-291` 两处判定）换成 **`depends_on` 祖先判定**——`input_bindings` 与 `{{x.output}}` 模板引用只能指向直接或间接依赖的步骤（并行下这是"数据已就绪"的硬条件，也是并行分支不可互读变量的落点）。
   - 同一处新增：`depends_on` 结构校验（存在/非自引用/无重复）、**环检测**（全文现无任何环检测代码）、孤儿检测（每步须自起点可达）、单步扇出宽度上限。
   - `_validate_edges`(`:330-345`)：改为真正校验依赖生成的边——现在 `validate_steps` 内的调用因 `definition is None`(`:333-334`) 直接返回，是死路径，实际只在 `:234` 生效。
   - 兼容规则：`depends_on` **缺省 → 回退为"序列中前一个"**（存量定义零改动）；显式 `[]` = 起点（并行分支的第二条靠它声明）。
6. `apps/backend/app/modules/workflows/schemas.py` + `router.py`：`WorkflowStepInput`(`:30-51`) 增加 `depends_on` 与 `position`；400 语义沿用现有错误路径。

**运行时（DAG 调度）**
7. `apps/backend/app/modules/workflows/runner.py`：
   - `_execute_steps`(`:206-355`) 的 `for seq, step in enumerate(steps)`(`:223`) 改为**拓扑分层调度**：同层 `asyncio.gather` 并发、跨层等待；`outputs`(`:220`) 与 `completed`(`:221`) 改由"主协程收各步返回值后合并"，避免并发写同一 dict；`create_step_run`(`:228-233`) 的 `seq` 传拓扑序位次。
   - 重试循环(`:253`)与 `_render_text`(`:256`)/`_render_json`(`:268`)/`input_bindings` 解析(`:269-270`) 按步隔离，保持原样。
   - 失败语义：`:353` 的直接 `raise StepFailedError` 在 `gather` 下会取消同层其余步骤，改为**收齐同层结果后再判定**（默认 fail-fast，但已启动的分支跑完再收尾，避免半途取消造成副作用不确定）；`continue_with_default`(`:347-350`) 逐分支生效；`fail_branch` 仍不实现。
   - 新增**分支并发闸**（`asyncio.Semaphore`，默认 4），与运行级闸正交：`tasks/scheduler.py:43 MAX_CONCURRENT_RUNS = 5` 限的是同时跑几条 run，新闸限的是一条 run 内并行几步。注意 `workflows/scheduler.py:34` 的同名常量是**死代码**，真实闸在 `tasks/scheduler.py:135`。
   - 单步超时：`timeout_seconds` 现已落进 node（`validators.py:97`）但 runner 从不读取，本次在 `_run_agent_step`(`:358-391`)/`_run_tool_step`(`:394-455`) 外层包 `asyncio.wait_for`；整条 run 的超时 `asyncio.wait_for`(`:156-169`) 与 `_fail_running_steps`(`:531-543`) 收尾语义不变。
8. `apps/backend/app/modules/workflows/orchestration.py`（新）：`run_orchestration_turn(...)` —— 为绑定编排的 Agent 建一次 `trigger_kind="conversation"` 的 `workflow_run`、复用 `runner` 的步骤执行、把汇聚步骤输出交回会话层；**不 import conversation**（否则与既有 `workflows/runner.py`→`conversation/services.py:919` 成环）。**递归必须显式排除**：`execute_unattended_chat`(`:919`)、`execute_chat`(`:490`)、`stream_chat`(`:613`) 增加 `allow_orchestration: bool` 参数；工作流 `_run_agent_step`(`runner.py:375-386`) 与任务链路传 `False`——否则「工作流的 Agent 步骤 → execute_unattended_chat → execute_chat → 再次接管」会自我递归。

**会话接管**
9. 会话接管落在**两个互不复用的装配点**（只改一处必漏另一端）：
   - REST/SSE：`conversation/services.py:451`/`:716` 的运行时装配点；
   - 终端用户入口：WS `/ws/agents/{agent_id}`(`gateway/router.py:890`，embed token 经 `authenticate_embed_token`) → `produce_embed_request`(`:619`) → `gateway/runtime.py:565 stream_embed_chat` → 在 `:727` 自行装配运行时。
   三处（`execute_chat`/`stream_chat`/`stream_embed_chat`）都在 `allow_orchestration=True` 时判断 `agent.orchestration_workflow_id`，非空则以编排产出的**同一套 AgentEvent 事件流**替代 `build_langchain_runtime(...).stream(...)`，下游 `stream_runtime_as_conversation`、SSE 序列化、assistant 落库全部不动；编排入口用**函数内延迟导入**（`workflows/runner.py:32-37` 与 `services.py:29-30` 已 import conversation，模块级反向 import 必成环）；会话历史经 `load_recent_history`/`build_history_messages` 打包交编排；`workflow_step_runs.conversation_id`/`agent_loop_run_id`(`:338-348`) 沿用既有语义。
10. 会话内触发路径强制 `UnattendedPolicy(auto_approve=False, strict_approval=False)`（`tasks/unattended.py:30-55`）作为 `confirmation_decider`：任何需审批工具一律拒绝并把原因回给模型；`side_effect="none"` 的工具本就不走 decider（`mcp/services.py:168-183`），故只读能力不受影响。`Workflow` 虽已有 `auto_approve`/`strict_approval` 列(`:125-138`)，此路径**忽略**它们。

**前端**
11. `apps/front/package.json`：新增 `@xyflow/react`。
12. `apps/front/src/features/workflows/workflow-canvas.tsx`（新）：节点=步骤、连线=`depends_on`、节点内联属性面板；与既有 `workflow-definition-form.tsx` 合并为"画布 + 属性"编辑器；`apps/front/src/api/workflow.ts` 类型同步 `depends_on`/`position`；Agent 编辑页新增"编排绑定"选择器。

**测试与验证**
13. `apps/backend/tests/workflows/test_validators.py`（补依赖校验用例）、`apps/backend/tests/workflows/test_runner_parallel.py`（新：并发时间窗、汇聚就绪、失败语义、并发闸、`continue_with_default`）。
14. `apps/backend/tests/conversation/test_orchestration_binding.py`（新：绑定接管落库、未绑定回归、审批一律拒绝）。
15. `tools/harness/verify/2026-10-14-multi-agent-orchestration.sh`。

**文档**
16. `docs/adr/0004-workflow-parallel-orchestration.md`（新 ADR，含对 ADR 0002 被否决选项的回应）、`CONTEXT.md` 术语（扇出/汇聚/编排绑定）、`docs/CHANGELOG.md`。

（注：`migrations/env.py` 无需改动——`agent` 与 `workflows` 均已在 import 列表中。）

## 验收标准

1. `poetry run pytest tests/workflows tests/conversation tests/agent -q` 全绿；`poetry run ruff check .` 与 `poetry run black --check .` 通过。
2. 保存期校验有真实拒绝：成环 / 悬空依赖 / 引用非祖先 / 扇出超上限 → 400 且错误信息指出具体 step_id。
3. 3 分支扇出 + 1 个汇聚：三个分支的 `workflow_step_runs` 时间窗重叠（真并发），汇聚步骤在三个分支都到终态之后才开始；`outputs` 与选择器解析正确。
4. 分支异构：三个分支指定三个不同 `agent_id`，`model_usage_records.agent_id` 各自正确落库。
5. 失败语义：默认 fail-fast 下 `workflow_run.status="failed"` 且同层其余分支仍有终态记录；`continue_with_default` 分支落 `on_error_applied=True` 并继续。
6. 绑定编排：embed 会话发一条消息 → 编排被触发 → 汇聚输出落为该轮 assistant 消息且可在会话历史中读回；**未绑定 Agent 的行为与改造前逐字一致**（回归）。
7. 定义往返：加载既有线性定义（无 `depends_on`）→ 保存 → 执行语义与改造前等价；含 `depends_on` 的定义经前端画布加载再保存后与后端语义等价；`apps/front` 构建通过。
8. 会话并发：同一 Agent 两个会话同时发消息 → 两条 `trigger_kind="conversation"` 的 run 并存不撞唯一索引；工作流的 Agent 步骤链路不触发接管（无递归）。
