# 业界调研记录

## 调研问题

- 本次要解决什么问题：防止 Agent 在单次对话任务中因工具结果反馈或模型误判无限循环调用工具，需要为后端对话图执行增加"单次任务最大迭代轮数"守卫，并在超限时优雅收尾。
- 调研结果将影响哪些范围、架构、接口或实现决策：`apps/backend/app/modules/conversation/runtime.py` 的两条执行循环（流式 `_stream_graph` 与非流式 `run_graph`）、后端全局配置 `apps/backend/app/core/config.py`，以及验收标准与实施计划。

## 功能复杂度

- 级别：普通业务功能
- 选择理由：改动集中在后端对话运行时循环与全局配置，不涉及数据库与 API 契约；但涉及两条执行路径，需要用单测保证行为一致。
- 最低调研要求：参考成熟 Agent 框架的循环上限机制（参数名、默认值、超限行为），比较至少两种超限处理路线。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenAI Agents SDK — Running agents
- 链接：https://openai.github.io/openai-agents-python/zh/running_agents/
- 版本或发布日期：持续维护，调研日期 2026-08-20
- 核心做法：`max_turns` 默认 10；turn 定义为"一次 AI 调用（含其工具调用）"；超限抛出 `MaxTurnsExceeded`；`max_turns=None` 可禁用上限。
- 对本项目的启发：轮次按"一次 LLM 调用"计数最符合模型执行语义；超限抛异常的做法对聊天产品偏硬，本项目改为优雅收尾；默认值参考 10，本项目为降低复杂任务误杀概率取 20。

### 来源 2

- 类型：官方文档
- 名称：LangChain LangGraph — GRAPH_RECURSION_LIMIT
- 链接：https://docs.langchain.com/oss/javascript/langgraph/errors/GRAPH_RECURSION_LIMIT
- 版本或发布日期：持续维护，调研日期 2026-08-20
- 核心做法：`recursionLimit` 默认 25，用于防止图死循环；超过后抛 `GraphRecursionError`。
- 对本项目的启发：主流图执行框架均有内置递归上限；但本项目超限要求"优雅收尾"而非抛错，LangGraph 内置机制需要额外捕获改造，且无法覆盖流式 `while True` 路径，因此不直接复用。

### 来源 3

- 类型：成熟开源项目（基于搜索结果核实，未逐字核对原文）
- 名称：Hugging Face smolagents
- 链接：https://huggingface.co/docs/smolagents/zh/reference/agents ；https://deepwiki.com/huggingface/smolagents/3.1-agent-framework
- 版本或发布日期：`max_steps` 为现行参数（由 `max_iterations` 更名），默认值 20，调研日期 2026-08-20
- 核心做法：`max_steps` 默认 20，超限抛 `AgentMaxStepsError`；框架在步数超限时先尝试基于历史合成最终回答（`_handle_max_steps_reached`），而非直接中断。
- 对本项目的启发：提供"超限后基于已有信息收尾"的成熟先例，与本次"优雅收尾"方案一致；默认值 20 与本项目选定默认值一致。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 全局配置 + 循环内计数 + 超限优雅收尾 | 实现简单、两条路径行为一致、不把异常暴露给用户、默认值可配置 | 需同时修改两个循环 | 高 |
| 超限直接抛异常（OpenAI 风格） | 语义清晰、实现最简 | 聊天场景把异常暴露给用户，体验差 | 中/低 |
| 复用 LangGraph 内置 recursionLimit | 非流式路径少写代码 | 超限抛 `GraphRecursionError` 仍需捕获改造；流式 `while True` 路径绕不开 | 低 |

## 最终决策

- 选择方案：全局配置文件上限（`AGENT_MAX_ITERATIONS`，默认 20）+ 两条循环统一计数 + 超限时停止工具并追加一次不带工具的收尾调用。
- 选择原因：用户明确要求"配置文件即可"与"优雅收尾"；smolagents 同为默认 20 且有超限合成回答的先例；不改数据库与 API 契约，风险最小。
- 不选择其他方案的原因：抛异常方案与"优雅收尾"要求冲突；LangGraph 内置限制无法覆盖流式路径且超限行为不符合要求。
- 对后续 spec、plan 或人工确认的影响：不涉及架构边界、数据模型、API 契约与权限行为变化，实现前无需人工审批；仍按 request 流程记录设计与验收标准。

## 剩余风险

- 资料时效性：smolagents 默认值基于搜索结果，实施时如引用需以官方文档复核。
- 与本项目上下文的差异：本项目使用 LangChain 风格消息并自维护 `while` 循环，无现成 recursionLimit 参数，需自行计数。
- 尚未验证的假设：收尾调用本身仍可能异常（模型超时、限流），需沿用现有异常处理兜底；收尾调用必须使用不带工具绑定的模型实例，避免模型再次请求工具。
