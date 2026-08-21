# 设计说明

## 目标

- 为后端对话图执行增加"单次任务最大迭代轮数"守卫，防止 Agent 因工具结果反馈或模型误判无限循环调用工具。
- 影响对象：所有通过 `apps/backend` 对话接口发起的带工具对话，包括流式（`_stream_graph`）与非流式（`run_graph`）两条路径。
- 完成后应产生可验证结果：达到上限后不再执行工具，模型输出收尾说明并正常结束，不再无限循环。
- 调研结论见 `research.md`：参考 OpenAI `max_turns`（10）、LangGraph `recursionLimit`（25）、smolagents `max_steps`（20，超限合成回答）；本项目采用全局配置 + 优雅收尾，默认 20。

## 范围

- `apps/backend/app/core/config.py`：`Settings` 新增 `agent_max_iterations`，读取环境变量 `AGENT_MAX_ITERATIONS`，默认 20；`0` 或空值视为不设限。
- `apps/backend/app/modules/conversation/runtime.py`：
  - `_stream_graph` 工具分支的 `while True` 循环加轮次计数；
  - `run_graph` 的 `while tool_calls` 循环加轮次计数；
  - 轮次定义：每轮 = 一次带工具的 LLM 调用（含其工具执行）；收尾调用为受控的最后一次，不计入上限；
  - 达到上限且模型仍请求工具时：停止工具执行，追加"已达执行上限，请基于已有信息直接给出最终回答"的系统提示，用不带工具绑定的模型实例做收尾调用（流式路径继续输出 `message_delta` 并 emit `completed`，非流式路径并入 `GraphResult.content`），并输出 warning 日志。
- 检测到宿主工具结果包含 `page_tool_budget_exceeded` 时：不再执行剩余工具、不再调用模型，直接输出固定提示"已达到页面工具使用限制（次数/时长），本次执行已停止。"并正常 emit `completed`；`apps/backend/app/modules/gateway/router.py` 将宿主工具错误码与信息透传到工具结果（保留 `error: host_tool_failed` 兼容键）。
- 单测：`apps/backend/tests/conversation/` 下补充超限、未超限与边界用例。
- 配置文档：在 `apps/backend/readme.md` 或本 request 文档中说明 `AGENT_MAX_ITERATIONS` 的取值与行为。
- 与原闭环的关系：独立新 request；不修改 `2026-08-07-page-interaction-tools` 的 `pageTools.maxCalls`（那是 SDK 侧页面工具预算，属另一个概念）。

## 非目标

- 不改 `page_tool_budget_exceeded` 及 SDK 侧页面工具预算逻辑。
- 不做 Agent 级或请求级可配置（本次仅全局配置文件）。
- 不新增 API 字段、不改数据库表结构。
- 不引入外部依赖或新框架。

## 风险

- 回归风险：两条执行路径行为需保持一致，若只改一条会出现行为不一致；用统一计数逻辑并单测覆盖。
- 兼容性风险：收尾调用必须使用不带工具绑定的模型实例并追加系统提示约束；若收尾调用本身异常，回退为固定提示文本并沿用现有异常兜底。
- 现有 `confirmation_required` 提前返回逻辑必须保留，不受计数影响。
- 当前未识别到高风险运行时变更。

## 停点判断

- 是否涉及架构边界变化：否，守卫在既有对话运行时内部实现。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：否。
- 是否涉及鉴权或权限行为变化：否。
- 结论：进入实现前无需人工确认；用户已在设计中确认配置层级（全局配置文件）、超限行为（优雅收尾）与默认值（20）。

## 验收标准

- `AGENT_MAX_ITERATIONS` 可被识别，缺省时默认 20；`0` 或空值不设限。
- 带工具对话达到上限后不再调用工具，收到收尾文本并正常收到 `completed` 事件（流式）或返回 `GraphResult`（非流式）。
- 宿主工具结果包含 `page_tool_budget_exceeded` 时，循环立即停止、不再调用模型，返回固定限制提示并正常 `completed`。
- 未达上限的对话行为与改动前一致：事件流顺序、工具执行、确认流程均不变。
- 达到上限时日志输出 warning，包含已执行轮次与上限值。
- 后端单测通过：覆盖超限收尾、未超限不变、`0` 不设限、收尾调用异常回退。

## 变更记录

### 初始版本

- 时间：2026-08-20
- 变更原因：首次创建后端 Agent 循环最大迭代轮数守卫设计
- 变更内容：确定全局配置文件上限（默认 20）、轮次定义（一次带工具的 LLM 调用）、超限优雅收尾、两条循环路径统一守卫
- 影响章节：全部
- 是否触发人工确认：否

### 2026-08-20 实现与验证

- 变更原因：用户审阅 spec 后批准实现，按计划完成代码与单测
- 变更内容：`config.py` 新增 `AGENT_MAX_ITERATIONS`；`runtime.py` 两条工具循环加轮次守卫与不带工具的收尾调用；`test_runtime.py` 新增 5 个用例；`readme.md` 补充配置说明
- 影响章节：范围、验收标准
- 是否触发人工确认：否，验证通过后进入验收阶段

### 2026-08-20 增量：页面工具预算耗尽即停止

- 变更原因：用户要求当前端报 `page_tool_budget_exceeded` 时不再继续执行 Agent，直接提示用户次数限制
- 变更内容：`gateway/router.py` 将宿主工具错误码/信息透传到工具结果（保留 `error: host_tool_failed` 兼容键）；`runtime.py` 两条循环检测到 `page_tool_budget_exceeded` 后停止工具执行与模型调用，直接输出固定限制提示并正常 `completed`
- 影响章节：范围、验收标准
- 是否触发人工确认：否，属同一循环守卫闭环的增量；不涉及数据库与外部 API 契约变化（`host_tool_error` 协议载荷原本就包含 `code` 与 `message`）
