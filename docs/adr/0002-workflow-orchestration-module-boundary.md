# 工作流做独立模块，定义不可变版本 + 运行快照，步骤引用用数组选择器

## Status

accepted

关联 Harness request：`2026-10-13-workflow-orchestration`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-13-workflow-orchestration/`）。

## Decision

多步编排做成独立的 `apps/backend/app/modules/workflows/` 模块，而不是给 `tasks` 表加 `kind` 列。工作流定义以 JSON（`nodes[]` + `edges[]`，节点与边都是稳定字符串 id）存在 `workflows.definition` 里，每次保存令 `workflows.version` 加一；每次运行把当次的定义**快照**写进 `workflow_runs.definition_snapshot` 并记下 `definition_version_id`，但不建独立版本表、不做 draft/published 三态、不做回滚与按版本重跑。

步骤之间的数据传递用**数组式选择器** `input_bindings: [{name, value_selector: [step_id, path]}]`，而不是字符串模板 `{{步骤名.output}}`。字符串模板只保留在「渲染给模型的提示词」这一层。

失败语义挂在**步骤属性**上：`on_error` 的三档枚举 `abort` / `continue_with_default` / `fail_branch` 在 v1 就写进 schema，但只实现前两档；`fail_branch` 依赖边上的 `source_handle`（v1 恒为 `default`），值先占住、行为后加。

执行时每个步骤调用一次 `conversation/services.py:911` 的 `execute_unattended_chat`，于是每步天然新建一个会话、拥有独立上下文——这既是「多步」相对「一条长提示词」的核心收益，也是不需要先做多 Agent 的理由。

## Considered Options

- **给 `tasks` 表加 `kind='agent'|'workflow'` 列**：改动量最小，能直接复用任务的一切。但会让 `prompt`/`model_id`/`cron_expression`/`timeout_seconds` 这些列退化成「仅当 kind=agent 才有意义」，是典型的表内二义性；而且工作流每多一个字段都要回头改任务模块的模型与校验。独立模块的代价是多一套 CRUD，收益是现有任务行为零回归。
- **工作流自带触发器，完全不依赖 tasks**：看似更干净，实际等于把 `docs/adr/0001` 定案的数据库抢占调度与看门狗重写一遍——那套逻辑解决了多副本抢占、重叠跳过、进程被杀后的悬挂收敛，重写一遍几乎不可能不丢语义。
- **完整版本管理（独立版本表 + draft/published + 回滚 + 按版本重跑）**：Dify 确实是这么做的，n8n 与 GHA 也都记录版本号。但 Dify 允许**删除旧版本**，而历史 run 靠**自己携带的快照**解释自己——这条证据说明快照是表达力所必需的，版本表只是发布管理与对比的基础设施。v1 没有发布评审流程，也就没有「谁能跑草稿」的权限语义要定，因此先只留 `version` 整数 + 快照。
- **字符串模板引用（`{{步骤名.output}}`）**：写法对用户更友好，但「引用只能指向排在前面的步骤」这条校验（它必须在保存时做，否则错误要到运行时才炸，而那时前序步骤的副作用已经发生）用字符串模板实现就得自写一个解析器，并且这个解析器的语法一旦演化就成了兼容负担。数组选择器把同一件事变成纯数据比对，且能被 JSON Schema 直接描述。
- **把 `continue-on-error` 排除在 v1 之外**：最初的理由是「会让工作流成功状态失去意义」。调研显示三家成熟实现都把它做成节点属性，并且 n8n 用 `continueErrorOutput` 与 `continueRegularOutput` 两个不同出口来表达「失败但继续」与「成功继续」的区别——也就是说这个担忧有解。因此改为：枚举值 v1 就进 schema，`continue_with_default` 落地，`fail_branch` 因依赖分支机制而暂不实现。
- **先做多 Agent（模型自主委派），工作流后置**：Pi 的 subagent 扩展靠 `--no-session` 起独立进程，其真实收益是**上下文隔离**，不是能力扩张。而本方案里「每步一个新会话」已经拿到同样的隔离效果。反过来，自主委派路线给出的是不可预测、难排错、成本不可控的系统，而且它**仍然解决不了**「固定流程要确定性执行」这个问题。因此顺序是先声明式工作流（默认全部步骤用同一个 Agent），多 Agent 作为「每步可覆盖 `agent_id`」的能力自然长出来。

## Consequences

- 工作流与任务成为两个平行的执行概念，二者通过 `tasks.workflow_id` 这一个可空外键连接。这条边让「定时触发工作流」不需要新调度器，代价是调度链路里多一个分支：抢占到的任务若带 `workflow_id`，由 `workflows/scheduler.py::_claim_and_dispatch_workflows()` 落运行记录，再由 `workflows/runner.py::run_workflow_run()` 逐步执行；`tasks/scheduler.py` 的两条派发路径共用同一个并发上限。
- `version` 只增不减，且没有版本表与回滚入口。日后若要支持「回滚到上一版」或「按指定版本重跑」，需要新增版本表并把 `workflow_runs.definition_version_id` 从整数升级为外键——届时历史 run 因为自带快照，仍然能解释自己，不会返工。
- `on_error` 的 `fail_branch` 与边的 `source_handle` 是提前占位。v1 的 `edges` 全部是 `source_handle: "default"`，若日后加条件节点，需要同时补齐变量作用域、汇合语义与失败传播三条规则，届时以新 request 处理。
- 数组选择器把定义的表达力收紧成「只能引用已完成的步骤输出」，这排除了「把自定义常量提升为工作流级变量」这类写法；若要支持，需要新增一个变量声明节，而不是放宽选择器语法。
