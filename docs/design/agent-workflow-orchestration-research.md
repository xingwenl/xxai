# 多步工作流编排 v1 技术调研（不做可视化画布）

调研问题、范围与验收标准见文末「调研口径」。本文件所有字段名均取自官方文档或官方源码，凡属推断处显式标注 **[推断]**。

> 取证方式说明：本会话 `web_search` 工具返回 HTTP 401（`Authentication Fails, Your api key: ****EHzb is invalid`，endpoint `https://api.deepseek.com/anthropic/v1/messages`），不可用；`raw.githubusercontent.com` 被网络阻断。因此结论来自：（a）各站点官方文档（Dify/n8n 支持在 URL 后加 `.md` 取干净 Markdown）；（b）官方 `llms.txt` 索引；（c）GitHub 官方 contents API（`Accept: application/vnd.github.raw`）直接读取官方仓库文件。所有 URL 均为真实可点击地址。

---

## 1. 定义格式：主流形态与真实片段

### 1.1 Dify：app DSL（YAML），节点图 + 选择器

[官方文档](https://docs.dify.ai/en/workspace/app-management)确认 DSL 是 YAML、导入时做版本兼容检查、旧版本会警告、导出**不含**第三方工具 API key、知识库正文与使用日志。当前 DSL 版本见官方源码 [`api/constants/dsl_version.py`](https://github.com/langgenius/dify/blob/main/api/constants/dsl_version.py)：

```python
CURRENT_APP_DSL_VERSION = "0.7.0"
```

下面是**真实片段**（来自官方仓库 [`scripts/stress-test/setup/dsl/workflow_llm.yml`](https://github.com/langgenius/dify/blob/main/scripts/stress-test/setup/dsl/workflow_llm.yml)，该文件 `version: 0.4.0`，字段名逐字保留，省略部分用 `...`）：

```yaml
app:
  description: ...
  mode: workflow
  name: ...
  use_icon_as_answer_icon: false
dependencies:
  - current_identifier: null
    type: marketplace
    value:
      marketplace_plugin_unique_identifier: "langgenius/openai:0.2.5@..."
kind: app
version: 0.4.0
workflow:
  conversation_variables: []
  environment_variables: []
  graph:
    nodes:
      - id: "1757611990947"
        type: custom
        title: Start
        position: { x: 0, y: 0 }
        data:
          type: start
          title: Start
          variables:
            - variable: question
              label: question
              type: text-input
              required: true
              max_length: null
              options: []
      - id: "1757611992921"
        type: custom
        data:
          type: llm
          title: LLM
          model:
            provider: langgenius/openai/openai
            name: gpt-4o
            mode: chat
            completion_params: { temperature: 0.7 }
          context: { enabled: false, variable_selector: [] }
          prompt_template:
            - { id: "<uuid>", role: system, text: "" }
            - { id: "<uuid>", role: user, text: "{{#1757611990947.question#}}" }
          variables: []
          vision: { enabled: false }
      - id: "1757611994xxx"
        type: custom
        data:
          type: end
          outputs:
            - variable: answer
              value_type: string
              value_selector: ["1757611992921", "text"]
    edges:
      - id: "1757611990947-source-1757611992921-target"
        source: "1757611990947"
        target: "1757611992921"
        sourceHandle: source
        targetHandle: target
        type: custom
        zIndex: 0
        data: { sourceType: start, targetType: llm, isInIteration: false, isInLoop: false }
    viewport: { x: 0, y: 0, zoom: 1 }
```

要点（均可直接支撑我们的 schema 设计）：

- **数据引用两种语法并存**：提示词里用 `{{#<节点id或节点名>.<变量名>#}}`（文档中亦见 `{{#user_input.topic#}}`、`{{#human_input.feedback#}}`）；结构化字段里用 `value_selector: ["<节点id>", "<变量名或对象路径>"]`。前端类型定义把它写成数组：`export type ValueSelector = string[] // [nodeId, key | obj key path]`（[`web/app/components/workflow/types.ts`](https://github.com/langgenius/dify/blob/main/web/app/components/workflow/types.ts)）。
- **节点与边都是显式 id + source/target**；节点 id 是字符串（Dify 前端用毫秒时间戳）。
- **节点类型字符串完整枚举**（同一文件 `BlockEnum`）：`start`、`end`、`answer`、`llm`、`knowledge-retrieval`、`question-classifier`、`if-else`、`code`、`template-transform`、`http-request`、`variable-assigner`、`variable-aggregator`、`tool`、`parameter-extractor`、`iteration`、`document-extractor`、`list-operator`、`loop`、`loop-start`、`loop-end`、`human-input`、`datasource`、`trigger-schedule`、`trigger-webhook`、`trigger-plugin`、`agent`、`agent-v2`（另有画布占位符 `start-placeholder`、`iteration-start`、`assigner` 旧名、`knowledge-index`、`datasource-empty`）。
- **起点节点二选一**：User Input（人或 API 触发）与 Trigger（Schedule / Integration / Webhook）在画布上互斥；Chatflow 只能 User Input，只有 Workflow 能用 Trigger（[官方文档](https://docs.dify.ai/en/guides/workflow/node)）。
- 节点级**运行时属性**也在 `data` 里：`error_strategy`、`retry_config`、`default_value`（见第 4 节），以及 tool 节点的 `provider_id`、`tool_name`、`tool_parameters`、`tool_configurations`（[`nodes/tool/types.ts`](https://github.com/langgenius/dify/blob/main/web/app/components/workflow/nodes/tool/types.ts)）。这些是「节点类型之外的通用属性」，比节点类型本身更容易返工。

### 1.2 n8n：JSON（节点 + 以「源节点名」为键的连接表）

n8n 的公开 API OpenAPI 3.0.0（`info.version: 1.1.1`）即其定义格式权威描述（[文档](https://docs.n8n.io/connect/n8n-api/workflow.md)）：

- 工作流对象必需字段：`id, name, description, active, activeVersionId, createdAt, updatedAt, isArchived, versionId, versionCounter, sourceWorkflowId, triggerCount, nodes, connections, nodeGroups, settings, staticData, meta, shared, activeVersion`。
- `nodes[]` 元素字段（逐字）：`id, name, webhookId, disabled, notesInFlow, notes, type, typeVersion, executeOnce, alwaysOutputData, retryOnFail, maxTries, waitBetweenTries, continueOnFail`（描述为「use `onError` instead」，已废弃）、`onError, position, parameters, credentials, customTelemetryTags, createdAt, updatedAt`。
- `connections` 的描述是「Connections between nodes, **keyed by source node name**」——即连线用**节点名**而不是 id 作键；`parameters` 里用表达式引用数据（`$json`、`$node["NodeName"].json`，见[表达式参考](https://docs.n8n.io/build/work-with-data/transform-data/expression-reference/)）。
- `pinData` =「Pinned sample data for nodes, keyed by node name」；`staticData` =「Data the workflow keeps between executions」。

### 1.3 LangGraph：定义即代码，「变量」= State schema

无序列化 DSL。定义是 Python 代码（[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)）：

```python
class OverallState(TypedDict):
    foo: str
    bar: Annotated[list[str], operator.add]   # 自定义 reducer 才累加

builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
builder.add_node("node_1", node_1)
builder.add_edge(START, "node_1")
builder.add_edge("node_3", END)
builder.add_conditional_edges("node_a", routing_function, {True: "node_b", False: "node_c"})
graph = builder.compile(checkpointer=InMemorySaver())
```

- 节点间数据引用 = **state key**；节点返回**部分更新**，默认 reducer 是覆盖，`Annotated[..., reducer]` 才合并。
- 条件路由有两种写法：`add_conditional_edges(node, routing_fn, mapping)`，或节点返回 `Command(goto=..., update=...)`（同一函数里同时更新状态并决定去向）。
- `Send` 用于运行期才知道数量的扇出（map-reduce），v1 不需要。

### 1.4 GitHub Actions：YAML，jobs/steps + needs

真实片段（官方仓库 [`.github/workflows/deploy-hitl-im-dev.yml`](https://github.com/langgenius/dify/blob/main/.github/workflows/deploy-hitl-im-dev.yml)）：

```yaml
name: Deploy HITL IM Dev
on:
  workflow_run:
    workflows: ['Build and Push API & Web']
    branches: ['build/feat/hitl-im-dev']
    types: [completed]
jobs:
  deploy:
    runs-on: depot-ubuntu-24.04
    if: |
      github.event.workflow_run.conclusion == 'success' &&
      github.event.workflow_run.head_branch == 'build/feat/hitl-im-dev'
    steps:
      - name: Deploy to server
        uses: appleboy/ssh-action@0ff4204d...
        with:
          host: ${{ secrets.HITL_SSH_HOST }}
          script: |
            ${{ vars.SSH_SCRIPT || secrets.SSH_SCRIPT }}
```

语法参考（[workflow-syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)）确认的键：`jobs.<job_id>.needs`、`.if`、`.continue-on-error`、`.outputs`、`.timeout-minutes`、`.strategy.fail-fast`、`.strategy.matrix`、`.steps`、`.uses/.with/.secrets/.env/.permissions/.environment/.concurrency`。步骤输出在同一个 job 内用 `steps.<step_id>.outputs.<name>` 引用（真实用例：`steps.docker-compose-changes.outputs.any_changed == 'true'`，同仓库 `autofix.yml`）；跨 job 用 `needs.<job_id>.outputs.<name>`。

### 1.5 对我们的 v1 的建议

- **[保留] 定义用结构化记录 + 显式节点/边 id + 数组式选择器**（照抄 `value_selector: [node_id, path]`），变量引用**不要**用模板字符串当唯一形式——字符串难校验，数组选择器可被 schema 验证、可做静态检查。
- **[保留] 节点上的「通用属性」**：`on_error`、`retry_config`、`default_value`（见第 4 节）。
- **[砍掉] 画布字段**：`position/positionAbsolute/width/height/zIndex/viewport/sourcePosition/targetPosition`。Dify 因为要画布而把布局写进定义；我们 v1 无画布，这些字段后加不需要改已有语义（纯附加字段），属于「砍掉不返工」。
- **[砍掉] 把触发方式放进工作流定义**。Dify 的 Trigger 是节点且与 User Input 互斥，这是它的历史包袱；我们已有「任务 + 时间触发」这一层，触发与执行图解耦更省事。来源同上（1.1 起点节点）。

---

## 2. v1 最小节点集合

目标形态：**线性多步 + 每步一次 Agent/工具调用 + 可选条件**。

**[保留，共 5 类]**

| 节点 | 理由 | 来源 |
| --- | --- | --- |
| `start`（输入声明） | 需要声明本次运行的外部输入变量，Dify 的 `variables[]`（`variable/label/type/required/max_length/options`）已是最小形态 | 1.1 节的真实 YAML |
| `agent`（一次 Agent 调用） | 我们的核心步骤；Dify 有独立 `agent` / `agent-v2` 节点类型 | `BlockEnum` 源码 |
| `tool`（一次工具调用） | 同上；Dify tool 节点核心字段仅 `provider_id / tool_name / tool_parameters / tool_configurations` | `nodes/tool/types.ts` |
| `condition`（if-else） | 「可选条件」的最小表达；Dify `if-else` 是独立节点类型，GHA 对应 `jobs.<job_id>.if` | `BlockEnum`；GHA syntax |
| `end`（输出声明） | 需要显式声明「这次运行输出什么」，Dify `outputs[]` 用 `value_selector` 关联 | 1.1 节真实 YAML |

**[砍掉，v1 省略且不返工]**

- `iteration` / `loop`（含 `loop-start`/`loop-end`）。Dify 文档明确：**重复执行的节点必须包进 Iteration/Loop 节点**，且「A single execution path supports up to 50 nodes」（[编排规则](https://docs.dify.ai/en/cloud/use-dify/build/orchestrate-node)）。我们 v1 的单条链远小于 50 节点，加循环容器是纯增量。
- `knowledge-retrieval`、`question-classifier`、`parameter-extractor`、`code`、`template-transform`、`http-request`、`variable-aggregator`、`variable-assigner`、`document-extractor`、`list-operator`、`datasource`。这些都是**类型**，后续以新增 `type` 值的方式接入，不影响已有定义。
- `answer`（Chatflow 的流式回复节点）：我们是无人值守任务，没有对话界面。

**[必须 v1 就设计进 schema（否则返工）]**

容易返工的不是节点类型，而是**节点通用属性与边的出口**：

1. 节点上的 `error_strategy` / `retry_config` / `default_value`（第 4 节）。
2. **边上的分支出口**：一旦要做 `condition`，edge 就必须带 `source_handle`（如 `true`/`false`）；若 v1 只写 `source/target`，之后加分支要改存储与执行器。Dify 的 edge 用 `sourceHandle/targetHandle`（真实值 `source`/`target`），失败分支则用额外 handle。
3. **每步的输出键命名**（`output_keys`）。Dify 的 `value_selector` 依赖「每个节点产出一个有名字的变量」；如果 v1 不强制每步输出命名，之后要显式引用就得回填历史数据。
4. 节点/边的 **id 必须是稳定字符串**（不要用自增行号），否则历史 run 无法解释（第 6 节）。

---

## 3. 变量/数据传递：(a) 整包传递 vs (b) 显式引用 + 类型化 schema

### 3.1 两种做法在真实系统里的样子

- **(a) 隐式整包**：n8n 是典型——数据以 item 列表在节点间流动，节点用 `$json` / `$node["Name"].json` 取用；连接表以源节点名作键。（[workflow API](https://docs.n8n.io/connect/n8n-api/workflow.md)、[表达式](https://docs.n8n.io/build/work-with-data/transform-data/expression-reference/)）
- **(b) 显式引用**：Dify 用 `value_selector: [node_id, key|obj key path]` + 可选 `value_type`；定义里的变量对象为 `Variable { variable, label?, value_selector, value_type?, variable_type?, value?, options?, required? }`（[types.ts](https://github.com/langgenius/dify/blob/main/web/app/components/workflow/types.ts)）。LangGraph 则是更硬的形态：**State 是 schema**（`TypedDict`/Pydantic/dataclass），每个 key 有自己的 reducer，节点只返回部分更新（[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)）。

### 3.2 什么时候会崩（有资料支撑的部分）

- **可见性规则先崩**：Dify 文档明确——串行时「Each node can read variables from any node earlier in the chain」，但**并行分支之间不能互读变量**，只有汇聚的下游节点能读到全部分支。也就是说隐式整包在「分支 + 汇聚」下无法表达，必须由平台规定可见集。（[orchestrate-node](https://docs.dify.ai/en/cloud/use-dify/build/orchestrate-node)）
- **结构变更的代价**：n8n 用 **dirty node** 机制兜底——插入/删除节点、改参数、加连线、停用节点、改 pinned data、循环内外改动，都会把相关节点标为「输出已过期/不可靠」，重跑该节点才清除。（[dirty nodes](https://docs.n8n.io/build/understand-workflows/understand-executions/understand-dirty-nodes.md)）这是隐式数据流的**工具层补偿**：结构一变，下游数据就失效。我们若采用隐式整包，等于把这套复杂度后置成「运行期才发现输入不对」。
- **单步重跑需要节点级数据**：n8n 的 partial execution（「Execute step」）能只跑某节点及其前置节点，前提是每次执行都持久化了**每个节点的输出**（[types-of-executions](https://docs.n8n.io/build/understand-workflows/understand-executions/types-of-executions.md)）。

### 3.3 结论

**[推断]** 以「步骤数」为分界的判断并不成立——真正的分界是：

1. 是否存在**非相邻引用**（第 4 步要第 1 步的输出）；
2. 是否**分支/并行**；
3. 是否需要**单独重跑某一步**。

三者任一命中，整包传递就开始靠约定（"约定第 2 步的输出字段名"）而不是靠结构，最终必然长出「变量池 + 选择器」。Dify 的做法的关键好处是：**选择器不要求类型化 schema 也能工作**（`value_type` 是可选的），因此「显式引用」的落地成本远低于「类型化 schema」。

**[v1 建议]**

- 采用 **「每步输出命名 + 显式选择器」**：运行期维护一个 `run 变量池 {node_id: {key: value}}`，节点声明 `input_bindings: [{name, value_selector: [node_id, path]}]`，等价于 Dify。
- **[砍掉]** 类型化 schema / 变量类型校验（`value_type`）与定义级 `environment_variables`/`conversation_variables` 池——Dify 有但可选，且我们无对话与多租户间共享变量需求。
- **[保留]** 每步 `output_keys` 必填（可为一步一个键），否则显式引用无从谈起。

---

## 4. 失败与重试语义

### 4.1 各系统的真实字段与取值

**Dify**（源码为准，[`error-handle/types.ts`](https://github.com/langgenius/dify/blob/main/web/app/components/workflow/nodes/_base/components/error-handle/types.ts)、[`retry/types.ts`](https://github.com/langgenius/dify/blob/main/web/app/components/workflow/nodes/_base/components/retry/types.ts)）：

```ts
export const ErrorHandleTypeEnum = { none: 'none', failBranch: 'fail-branch', defaultValue: 'default-value' }
export type DefaultValueForm = { key: string; type: VarType; value?: any }
export type WorkflowRetryConfig = { max_retries: number; retry_interval: number; retry_enabled: boolean }
```

文档语义（[predefined-error-handling-logic](https://docs.dify.ai/en/cloud/use-dify/build/predefined-error-handling-logic)）：`none` 是默认，整条工作流停止；`default-value` 用兜底值继续跑（「The default value must match the node's output type」）；`fail-branch` 走另一条分支（可用变量 `error_type`、`error_message`，类型见 [error-type](https://docs.dify.ai/en/cloud/use-dify/debug/error-type)）。另外：**Loop 节点的子节点失败一定立即终止**（无选项）；**Iteration 节点**有模式 `terminated`（默认）/ `continue-on-error` / `remove-abnormal-output`，`continue-on-error` 时失败项在输出数组里变成 `null`。

**n8n**（源码 [`packages/workflow/src/interfaces.ts`](https://github.com/n8n-io/n8n/blob/master/packages/workflow/src/interfaces.ts)）：

```ts
export type OnError = 'continueErrorOutput' | 'continueRegularOutput' | 'stopWorkflow';
// 节点同处还有：retryOnFail?: boolean; maxTries?: number; waitBetweenTries?: number; alwaysOutputData?: boolean
```

- 工作流级另有 `errorWorkflow`（一个以 **Error Trigger** 节点开头的工作流，可被多个工作流共用）；错误负载含 `execution.{id,url,retryOf,error{message,stack},lastNodeExecuted,mode}`（[handle-errors-gracefully](https://docs.n8n.io/build/flow-logic/handle-errors-gracefully.md)）。
- 执行数据保存策略属于工作流设置：`saveDataErrorExecution` / `saveDataSuccessExecution` / `saveManualExecutions`（enum `DEFAULT|all|none`）、`executionTimeout`、`saveExecutionProgress`（「If set to Save, the workflow resumes from where it stopped in case of an error. This may increase latency.」）、`redactionPolicy`（[configure-workflow-settings](https://docs.n8n.io/build/manage-workflows/configure-workflow-settings.md)）。
- **重试用哪一版定义，是显式产品选项**：重试执行时可「Retry with currently saved workflow」或「Retry with original workflow」（[retry-options](https://docs.n8n.io/build/understand-workflows/understand-executions/debug-executions.md)）。

**Temporal**（[Retry Policy](https://docs.temporal.io/encyclopedia/retry-policies)）：默认值逐字为 `Initial Interval = 1 second`、`Backoff Coefficient = 2.0`、`Maximum Interval = 100 × Initial Interval`、`Maximum Attempts = ∞`、`Non-Retryable Errors = []`。要点：**重试是 Activity 的属性**，Workflow 默认不重试（因为要确定性重放，易失败/非确定操作应放进 Activity）；`nonRetryable` 标记的失败永不重试；重试期间 Event History 只保留 `ActivityTaskScheduled`，直到终态才写 `Started/Completed/Failed`——**避免历史被重试噪声撑爆**。

**GitHub Actions**（[workflow-syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)、[contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)）：`needs` 失败或跳过会沿依赖链传播，除非用 `always()`/`failure()` 条件；`continue-on-error` 是 **job 级与 step 级**都有的设置；步骤有 `steps.<step_id>.outcome`（应用 continue-on-error 之前）与 `steps.<step_id>.conclusion`（之后）两个状态；`strategy.fail-fast` 默认 `true`。

**LangGraph**（[Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)）：`add_node(..., retry_policy=RetryPolicy(max_attempts=3, retry_on=ConnectionError))`、`timeout=60` 或 `TimeoutPolicy`、`error_handler=`（返回 `Command(goto=...)` 做补偿或转主线），另有 `set_node_defaults` 统一设默认值。

### 4.2 必须一开始定死 / 可以后加

**必须 v1 定死：**

1. **每步失败的三个选项**：`abort`（停整条）/ `continue-with-default`（兜底值继续）/ `fail-branch`（走失败分支）。三家的做法一致地把这个放在**节点属性**上（Dify `error_strategy`、n8n `onError`、GHA `continue-on-error`）。
2. **step 状态枚举与 run 终态语义**（尤其 `skipped` / `partial` / `waiting` 的归属），否则第 5 节的记录表要重构。
3. **重试计数与间隔属于「步」而不是「整个 run」**（Dify `WorkflowRetryConfig`、n8n `maxTries/waitBetweenTries`、Temporal 的 Activity 级 RetryPolicy 三方一致）。
4. **run 是否快照定义、重试是否沿用旧定义**——n8n 把它做成用户可见选项（retry with original / currently saved workflow），我们必须至少存 `definition_version_id`，并明确「默认重试用原版本」。
5. **最大步数上限**（Dify：单条执行路径 ≤50 节点），作为防环/防失控的第一道闸。

**可以后加（不破坏已存数据）：**

- 指数退避参数（`backoff_coefficient`/`maximum_interval`）与「非可重试错误类型白名单」——Temporal 的字段可以后补默认值。
- **补偿/回滚**（LangGraph 的 `error_handler` + `Command(goto=...)` 形态）、Saga。
- **单步重跑 / 局部重跑**（n8n partial execution + dirty node）。这是典型的「后加但有前提」：前提是**从第一天起就持久化每步的输入输出**（第 5 节），否则事后补不回来。
- 失败分支子图（若 v1 已有 `condition` + `source_handle`，`fail` 只是多一个 handle，属增量）。

**[v1 建议保留]** `on_error ∈ {abort, continue_with_default, fail_branch}`、步级 `retry{enabled,max_retries,retry_interval}`、`max_steps`、run 定义版本记录。
**[v1 建议砍掉]** 补偿事务、错误类型白名单、独立「错误处理器工作流」（n8n 的做法，我们 v1 用 fail-branch 边足够）。

---

## 5. 执行记录的粒度

### 5.1 各系统的实际粒度

| 系统 | 粒度 | 权威字段 |
| --- | --- | --- |
| Dify | **一条 run + `total_steps` 计数，但节点明细不经 Service API 暴露** | [Get Workflow Run Detail](https://docs.dify.ai/en/api-reference/workflow-runs/get-workflow-run-detail) 200 字段：`created_at, elapsed_time, error, finished_at, id, inputs, outputs, status ("succeeded"), total_steps, total_tokens, workflow_id` |
| Dify（节点级） | 只有**流式事件** | [list-workflow-logs](https://docs.dify.ai/en/api-reference/workflow-runs/list-workflow-logs) 原文：「Each entry is a run-level summary (status, token usage, step count, and timing), **not a node-by-node execution log**」；「**A finished run's node-level logs aren't available through the Service API**」。要节点级只能 `run-workflow` 流式模式（`node_started` / `node_finished`）或 `stream-workflow-events` 带 `include_state_snapshot=true` |
| n8n | **一条 execution；节点级明细在同一对象的 `data` 里（按节点名）** | [Executions API](https://docs.n8n.io/connect/n8n-api/executions.md) 字段：`id, finished(废弃), mode, retryOf, retrySuccessId, status, createdAt, startedAt, stoppedAt, deletedAt, workflowId, waitTill, storedAt, tracingContext{traceparent,tracestate}, deduplicationKey, jsonSizeBytes, binaryDataSizeBytes, workflowVersionId, usedPrivateCredentials, data, workflowData, customData`。枚举：`mode = cli|error|integrated|internal|manual|retry|trigger|webhook|evaluation|chat|agent`；`status = canceled|crashed|error|new|running|success|unknown|waiting` |
| n8n（自定义字段） | 每次执行最多 10 条自定义数据，`key` ≤50 字符、`value` ≤255 字符、只能是字符串 | customize-executions-data |
| GitHub Actions | **run → job → step 三级** | [workflow-runs](https://docs.github.com/en/rest/actions/workflow-runs)：run 有 `status`、`conclusion`、`run_attempt`、`run_started_at`、`path`、`rerun_url`；[workflow-jobs](https://docs.github.com/en/rest/actions/workflow-jobs)：step 为 `{ name, status, conclusion, number, started_at, completed_at }` |
| LangGraph | **super-step 检查点（全量状态快照）+ 每 task 写（`checkpoint_writes`）** | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpoint 在 super-step 边界落盘，`StateSnapshot` 含 `config{thread_id, checkpoint_ns, checkpoint_id}`、`values`、`next`、`metadata`、`parent_config`、`tasks`、`created_at`；节点级写用于「pending writes recovery」——同一步里失败节点之外的写入已持久化，恢复时不重跑 |
| Temporal | **Event History 本身** | [Event history](https://docs.temporal.io/encyclopedia/event-history)：Activity 相关事件 `ActivityTaskScheduled`（唯一在跑期间的事件）、`ActivityTaskStarted`+`ActivityTaskCompleted/Failed`、`ActivityTaskTimedOut`、`ActivityTaskCancelRequested/Canceled`；有数量/大小限制，超限须 Continue-As-New |

Dify 的运行期节点状态枚举（前端，可作 step status 设计参考）：`NodeRunningStatus = { NotStart:'not-start', Waiting:'waiting', Listening:'listening', Running:'running', Succeeded:'succeeded', Failed:'failed', Exception:'exception', Retry:'retry', Stopped:'stopped', Paused:'paused' }`。

### 5.2 step run 通常记什么

综合四家：**步身份**（`node_id`、`node_type`、序号）、**状态**、**尝试次数**、**开始/结束时间与耗时**、**该步输入**（解决后的绑定值，不是原始定义）、**输出**、**错误**（类型 + 消息，Dify 的 `error_type`/`error_message`、n8n 的 `error.message/stack`）、**token/成本**、**外部调用 id**（便于对账）、**审批信息**（若有）。

**[v1 建议保留]** 独立 `workflow_step_run` 表，字段见文末草案；节点级输入输出**必须**持久化（这是「后加单步重跑」的唯一前提）。
**[v1 建议砍掉]** pin data / dirty node 标记 / partial execution UI / `customData` 式的自定义过滤字段（n8n 有，但属于运行体验层）。

---

## 6. 版本化：定义改了，历史执行怎么解释

- **Dify**：工作流有三态——**Current Draft / Latest Version / Previous Versions**；Publish Update 后 draft 成为新的 Latest Version 并生成新 draft；旧版本可 Restore 回 draft（**完整覆盖当前 draft**）；不能删除 Current Draft 与 Latest Version。官方明确：「Restoring a version, exporting a specific version's DSL, and **running a specific published version through the Service API** are available on paid plans. On the Sandbox plan, apps always run the latest published version.」→ 「按版本执行」是一等能力（[version-control](https://docs.dify.ai/en/cloud/use-dify/build/version-control)、[run-workflow-by-id](https://docs.dify.ai/en/api-reference/workflow-runs/run-workflow-by-id)）。
- **n8n**：工作流有 `versionId` / `versionCounter`，`GET /workflows/{id}/history`、`GET /workflows/{id}/versions/{workflowVersionId}`、`POST /workflows/{id}/publish`（body `{versionId, name, description}`）。执行记录带 **`workflowVersionId`**（"ID of the workflow version this execution ran"）和 **`workflowData`**（"The workflow as it was saved when the execution ran. Only included when includeData is true. Older executions carry more fields than newer ones."）。文档明确警告 **workflow history ≠ execution history**；「Changes to workflow settings do not create a new version」（[view-change-history](https://docs.n8n.io/build/manage-workflows/view-change-history.md)）。
- **Temporal**：Workflow 代码必须确定性；改代码要用 **Patching**（在 Event History 里插 marker，旧执行不产生该 marker 也能重放）或 **Worker Versioning**（把执行 pin 到某个 revision），原文：「you can **pin your Workflows to specific revisions**, avoiding the need for patching」（[patching](https://docs.temporal.io/patching)、[worker-versioning](https://docs.temporal.io/worker-versioning)）。也就是说：历史之所以能解释，是因为**执行绑定了一个不可变版本**。
- **GitHub Actions**：run 记录里带 `path`（如 `.github/workflows/autofix.yml@main`）与 `head_sha`——定义版本由 commit 冻结。

**结论**：定义必须**不可变版本化**，run 必须记录 `definition_version_id`，并保留（或至少可重建）当时的定义快照。三家都做了：Dify 按版本执行、n8n 存 `workflowVersionId` + `workflowData`、GHA 存 commit ref。另有两条产品级决策要显式定：**重试/重跑时用哪一版定义**（n8n 给用户选），以及**删除旧版本时历史 run 是否仍可看**（Dify 允许删旧版本，说明历史 run 展示的是自己的快照，不依赖版本表——这是我们该学的）。

**[v1 建议保留]** `workflow_definition`（不可变版本表）+ `run.definition_version_id`，并在 run 上存定义快照（JSON）。
**[v1 建议砍掉]** draft/publish 工作流 UI、按版本重跑、diff 视图。但表结构必须留出 `status(draft/published/archived)` 与 `version`。

---

## 7. 人工审批节点

- **Dify：是一等节点类型**（`human-input`）。配置含投递方式（Web app / Email）、表单内容（Markdown，可插入变量渲染值；字段类型 Paragraph / Select / Single File / File List，只有 Paragraph 必填）、用户动作（若干决策按钮，每个有显示标题与 **action ID**，下游可用 `__action_id` 与 `__action_value`；表单内容渲染结果可用 `__rendered_content`）、超时策略（默认 3 天，可走超时分支）。原文：「The request closes after the first response regardless of delivery method.」（[human-input](https://docs.dify.ai/en/cloud/use-dify/nodes/human-input)）配套 API：[submit-human-input-form](https://docs.dify.ai/en/api-reference/human-input/submit-human-input-form)、[get-human-input-form](https://docs.dify.ai/en/api-reference/human-input/get-human-input-form)、[human-input-flow 指南](https://docs.dify.ai/en/api-reference/guides/human-input-flow)。
- **n8n：不是节点，而是长在「工具」上的审批步骤**。配置路径是 AI Agent 节点的 Tools Panel → **Human review** section，把需要审批的工具挂到这个 review step 上；审批渠道为既有节点：Chat / Slack / Discord / Telegram / Microsoft Teams / Gmail / WhatsApp Business Cloud / Google Chat / Microsoft Outlook。语义：Approve → 用 AI 给定的参数执行工具；Deny → 取消并告知 AI；消息里可用 `$tool.name` 与 `$tool.parameters` 描述「AI 想干什么」。原文：「This feature allows for selective oversight of tool use within AI workflows」，可以只对个别工具开审批。（[human-in-the-loop-for-tools](https://docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools.md)）
- **LangGraph：是函数而不是节点类型**。`interrupt(value)` 在节点内部调用即暂停，靠 checkpointer 持久化，用 `Command(resume=...)` 恢复；`interrupt(payload, response_schema=Decision)` 可以把期望的结构以 JSON Schema 暴露给客户端渲染表单。注意：**恢复时该节点会从头重跑**（`interrupt` 之前的代码会再执行一次），所以节点内逻辑必须幂等。（[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)）
- **GitHub Actions：不是节点，而是环境（environment）的 deployment protection rule**：Required reviewers（最多 6 人/团队，**任一批准即通过**）、可勾选 Prevent self-review、可加 Wait timer；参考 environment 的 job 必须先满足保护规则才能运行（[environments](https://docs.github.com/en/actions/reference/environments)）。
- **Temporal**：本轮未取到官方「审批节点」文档（`https://docs.temporal.io/encyclopedia/human-in-the-loop` 返回 221 字节 JS 壳，无法作为依据）→ **不作结论，标注未验证**。

**结论与建议**：主流路线是**两种**，「审批是独立节点」（Dify：因为它没有工具确认机制，只能新造节点）与「审批长在工具调用上」（n8n：平台已有工具/审批渠道概念，就挂在工具上；GHA 则挂在 job/environment 上）。我们**已有「工具调用需要确认」机制**，与 n8n 的处境相同 → **[建议] v1 复用既有确认机制，把它抽象成「step 可要求审批」的属性（`requires_approval`），而不是新建一套平行的审批节点**；同时在 run 上必须有 `waiting` 状态与唤醒条件（n8n 的 `status='waiting'` + `waitTill`、Dify 的 `Paused` + 超时策略可借鉴），并明确「**只接受第一次响应**」（Dify 原文）与审批结果落到 step run 的 `approved_by/approved_at`。

**[v1 保留]** run 的 `waiting` 状态 + 唤醒/超时 + 单次响应 + step 级审批记录。
**[v1 砍掉]** 多级会签、按角色路由、表单字段类型体系（Paragraph/Select/File…）、邮件投递渠道。

---

## v1 最小可行定义的字段草案

（仅字段名 + 类型 + 一句话含义；表名用 `snake_case`，JSON 字段统一用 `json`）

### `workflow_definition`（不可变版本）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string (uuid) | 版本记录主键 |
| `tenant_id` | string | 租户隔离键 |
| `key` | string | 工作流稳定标识（同名多版本） |
| `version` | int | 单调递增版本号，发布后不可变 |
| `status` | enum(`draft`,`published`,`archived`) | 生命周期状态 |
| `dsl_version` | string | 结构 schema 版本，用于向后兼容 |
| `nodes` | json[] | 步骤列表（见下 Node） |
| `edges` | json[] | 连接与分支（见下 Edge） |
| `variables` | json[] | 本次运行的外部输入声明（`name/type/required/default`） |
| `max_steps` | int | 单次执行步数上限（防环/防失控） |
| `default_on_error` | enum(`abort`,`continue`) | 未单独配置时的失败策略 |
| `created_at` / `updated_at` | timestamp | 审计时间 |

### Node（`nodes[]` 元素）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 节点稳定 id（定义内唯一，字符串而非自增序号） |
| `type` | enum(`start`,`agent`,`tool`,`condition`,`end`,`human_input`) | v1 节点类型 |
| `title` | string | 展示名（日志与审批消息里用） |
| `config` | json | 类型专属配置：agent→`agent_id/prompt`；tool→`tool_id/params`；condition→条件表达式 |
| `input_bindings` | json[] | `[{name, value_selector: [node_id, path], type?}]`，显式输入绑定 |
| `output_keys` | string[] | 该步输出的命名键（必填，选择器的引用目标） |
| `on_error` | enum(`abort`,`continue`,`branch`) | 失败行为：停整条 / 用兜底值继续 / 走 fail 分支 |
| `default_values` | json[] | `[{key, type, value}]`，`on_error=continue` 时的兜底值 |
| `retry` | json | `{enabled: bool, max_retries: int, retry_interval: int}` |
| `timeout_seconds` | int | 单步超时 |
| `requires_approval` | bool | 该步执行前是否需要人工确认（复用既有工具确认机制） |

### Edge（`edges[]` 元素）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 边 id |
| `source` | string | 源节点 id |
| `target` | string | 目标节点 id |
| `source_handle` | enum(`default`,`true`,`false`,`fail`) | 出口句柄；`condition` 与失败分支靠它区分 |

### `workflow_run`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string (uuid) | 一次执行（run）主键 |
| `tenant_id` | string | 租户隔离键 |
| `definition_id` | string | 所用定义版本 id |
| `definition_snapshot` | json | 执行时的定义快照（历史可解释的兜底） |
| `status` | enum(`queued`,`running`,`waiting`,`succeeded`,`failed`,`canceled`) | run 终态语义 |
| `trigger_type` | enum(`schedule`,`manual`,`api`) | 触发来源 |
| `input` / `output` | json | 本次运行的输入与最终输出 |
| `started_at` / `finished_at` | timestamp (nullable) | 起止时间；未开始/未结束为 null |
| `elapsed_ms` | int | 耗时 |
| `error_type` / `error_message` | string (nullable) | 失败分类与详情 |
| `total_steps` / `total_tokens` | int | 已执行步数与累计 token（对齐 Dify run 摘要字段） |

### `workflow_step_run`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string (uuid) | 一步执行的主键 |
| `run_id` | string | 所属 run |
| `node_id` | string | 定义里的节点 id |
| `node_type` | string | 节点类型（便于统计与展示） |
| `sequence` | int | 在本次执行中的顺序号 |
| `status` | enum(`not_started`,`running`,`waiting`,`succeeded`,`failed`,`skipped`,`canceled`) | 步状态（对齐 Dify `NodeRunningStatus` 的可用子集） |
| `attempt` | int | 第几次尝试（含重试） |
| `inputs` / `outputs` | json | 解析后的实际输入与输出（后加单步重跑的前提） |
| `error_type` / `error_message` | string (nullable) | 失败分类与详情 |
| `started_at` / `finished_at` | timestamp (nullable) | 起止时间 |
| `elapsed_ms` | int | 耗时 |
| `tokens` | int | 该步 token 消耗 |
| `external_ref` | string (nullable) | 外部调用/工具执行 id，用于对账 |
| `approved_by` / `approved_at` | string / timestamp (nullable) | 审批信息（`requires_approval` 步骤） |

---

## 调研口径（原文要求）

- 目标：为「多租户 Agent 平台增加多步工作流编排（v1 不做可视化画布）」收集成熟实现的做法与官方资料。现状：一条「任务」= 1 个 Agent + 1 段 prompt + 1 个时间触发规则，到点无人值守跑一轮；目标是升级为「跑一串有序步骤」，每步一次 Agent 调用或一次工具调用；v1 用结构化格式（数据库记录或 JSON DSL）定义。
- 要求回答 7 问：定义格式与变量引用语法；v1 最小节点集合；变量/数据传递的两种做法何时崩；失败与重试语义哪些必须一开始定死；执行记录粒度与 step run 字段；版本化与历史可解释性；人工审批是否一等节点及是否复用既有确认机制。
- 要求：可点击真实 URL、优先官方文档；每条结论注明来源；区分「官方文档明确写的」与「推断」；给出「v1 建议保留 / v1 建议砍掉」清单及理由与来源。

## 未验证项（明示）

1. Temporal 的人工审批/HITL 官方页面未取到（返回 221 字节 JS 壳），第 7 节未对其下结论。
2. Dify 内部是否存在持久化的节点级执行表（除 Service API 之外）**未验证**；本文只依据 Service API 文档与前端类型，未读其后端表结构。
3. Dify 的 `agent-v2`、`datasource` 等较新节点类型的语义未逐页阅读（不在 v1 范围内）。
4. n8n 的节点级 `onError` 三个枚举值取自 n8n 主仓库源码 `packages/workflow/src/interfaces.ts`（`OnError` 类型定义），其文档页仅以 UI 描述呈现，未找到逐值枚举的文档页。
5. GitHub Actions 的 `steps.<step_id>.conclusion` 取值（`success|failure|cancelled|skipped`）取自 contexts 参考页；run 级 `conclusion` 枚举取自 REST API 页面：`completed, action_required, cancelled, failure, neutral, skipped, stale, success, timed_out`（`status` 另含 `in_progress, queued, requested, waiting, pending`）。
