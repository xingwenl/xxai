# 实施计划

## 变更文件

- `apps/backend/app/core/config.py`：`Settings` 新增 `agent_max_iterations: int`，读取 `AGENT_MAX_ITERATIONS`（默认 20，0 或空视为不设限）。
- `apps/backend/app/modules/conversation/runtime.py`：
  - 新增统一轮次计数与收尾逻辑（含收尾提示文案常量与内部辅助函数）；
  - `_stream_graph` 工具分支循环加守卫：达到上限后停止工具执行，用不带工具的模型 `astream` 做收尾，输出 `message_delta` 与 `completed`；
  - `run_graph` 工具循环加守卫：达到上限后停止工具执行，用不带工具的模型 `ainvoke` 做收尾，结果并入 `GraphResult.content`；
  - 两处均输出 warning 日志。
- `apps/backend/app/modules/gateway/router.py`：宿主工具失败时把 `code`/`message` 透传到工具结果（保留 `error: host_tool_failed` 兼容键），供运行时识别 `page_tool_budget_exceeded`。
- 增量：`runtime.py` 检测到 `page_tool_budget_exceeded` 后立即停止循环，不再调用模型，直接输出固定限制提示并正常 `completed`。
- `apps/backend/tests/conversation/`：新增或扩展 `test_runtime.py` 用例，覆盖超限收尾、未超限不变、`0` 不设限、收尾异常回退。
- `apps/backend/readme.md`：补充 `AGENT_MAX_ITERATIONS` 配置说明。
- `docs/harness/requests/2026-08-20-agent-loop-max-iterations/`：本 request 的 `research.md`、`spec.md`、`plan.md`、`meta.json`。

## 实施步骤

1. 配置先行：在 `config.py` 增加 `agent_max_iterations` 字段与环境变量读取，同步 `readme.md` 配置说明。
2. 实现守卫：
   - 定义轮次计数：每轮 = 一次带工具的 LLM 调用（含其工具执行）；收尾调用不计入；
   - `_stream_graph`：`while True` 内计数，达到上限且仍有工具请求时跳出工具执行，追加收尾系统提示后用不带工具的模型实例流式收尾，正常 emit `completed`；
   - `run_graph`：`while tool_calls` 内计数，同样处理；收尾结果作为最终 `GraphResult.content`；
   - 保留 `confirmation_required` 提前返回逻辑；收尾调用异常时回退固定提示文本。
3. 单测：用 mock 模型构造"前 N 次返回工具调用、之后返回普通文本"的场景，断言工具执行次数、收尾文本、事件结构与 `completed` 正常；补充未超限回归与边界用例。
4. 运行后端单测验证。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/conversation -q`：预期新增用例全部通过，既有用例不回归。
- 如环境允许，本地起后端手工验证一个带工具对话的超限场景，观察 SSE 事件顺序与 warning 日志。

## 回滚说明

- 改动集中在 `config.py` 与 `runtime.py`，可按文件回滚；删除或置空 `AGENT_MAX_ITERATIONS` 即恢复原行为。
- 关注点：`completed` 事件结构与 `GraphResult` 字段不能变化，避免前端与下游解析回归。

## 人工确认点

- 无（不涉及架构边界、数据模型、API 契约与权限行为变化；设计已获用户确认）。

## 详细任务清单（writing-plans 细化）

### 任务 1：配置项 `AGENT_MAX_ITERATIONS`

**文件：**

- 修改：`apps/backend/app/core/config.py`
- 文档：`apps/backend/readme.md`

**步骤：**

- [x] 步骤 1.1：`Settings` 数据类在 `agent_fetch_timeout_seconds` 后新增字段 `agent_max_iterations: int`。
- [x] 步骤 1.2：`get_settings()` 中读取 `int(os.getenv("AGENT_MAX_ITERATIONS", "20"))`。
- [x] 步骤 1.3：`apps/backend/readme.md` 追加说明：`AGENT_MAX_ITERATIONS` 默认 20，0 或负值视为不设限。

### 任务 2：运行时守卫与优雅收尾

**文件：**

- 修改：`apps/backend/app/modules/conversation/runtime.py`

**步骤：**

- [x] 步骤 2.1：新增 `from app.core.config import get_settings` 导入。
- [x] 步骤 2.2：新增模块常量与解析函数：

```python
_MAX_ITERATIONS_WRAPUP_PROMPT = (
    "你已达到本次任务的最大执行轮数，请停止调用任何工具，"
    "直接基于已有信息给出最终回答；如果信息不足，请明确说明。"
)


def _resolve_max_iterations(max_iterations: int | None) -> int | None:
    """解析 Agent 循环迭代上限；0 或负值视为不设限。"""
    value = (
        max_iterations
        if max_iterations is not None
        else get_settings().agent_max_iterations
    )
    return value if value and value > 0 else None
```

- [x] 步骤 2.3：`_stream_graph`、`stream_graph`、`run_graph` 三个函数新增关键字参数 `max_iterations: int | None = None`；`stream_graph` 透传给 `_stream_graph`。
- [x] 步骤 2.4：`_stream_graph` 工具分支：`while True` 前初始化 `limit = _resolve_max_iterations(max_iterations)`、`iteration_count = 0`、`wrap_up = False`；循环体开头 `iteration_count += 1`；在 `invoke_tool_fn is None` 检查之后新增：达到上限且仍请求工具时记 warning、置 `wrap_up = True` 并 `break`（不执行工具）。
- [x] 步骤 2.5：`_stream_graph` 在循环结束、`completed` 事件之前，新增收尾块：`wrap_up` 为真时用**不带工具绑定的 `model.astream`** 追加一次调用，消息为 `[SystemMessage(_MAX_ITERATIONS_WRAPUP_PROMPT), *messages]`，继续产出 `thinking_delta`/`message_delta` 并合并 usage；异常时记日志并产出固定回退文本 `"已达执行上限，本次回答可能不完整。"` 的 `message_delta`。
- [x] 步骤 2.6：`run_graph`：初始调用后 `iteration_count = 1`；`while tool_calls` 开头、`invoke_tool_fn is None` 检查之前新增：达到上限时记 warning、置 `wrap_up = True` 并 `break`；每次循环内 `ainvoke` 后 `iteration_count += 1`。
- [x] 步骤 2.7：`run_graph` 在组装 `GraphResult` 之前新增收尾块：`wrap_up` 为真时用**不带工具绑定的 `model.ainvoke`** 追加一次调用（消息同上），异常时回退固定文本；将结果写入 `result = {"content": content, "messages": [response]}` 并合并 usage。
- [x] 步骤 2.8：`confirmation_required` 提前返回逻辑保持不变；`completed` 事件结构与 `GraphResult` 字段不变。

### 任务 3：单测

**文件：**

- 修改：`apps/backend/tests/conversation/test_runtime.py`

**步骤：**

- [x] 步骤 3.1：新增 `InfiniteToolCallingModel`（`ainvoke`：前 `tool_rounds` 次返回工具调用，之后返回普通文本）与 `InfiniteStreamingToolCallingModel`（`astream` 同语义，工具调用用 `tool_call_chunks`），以及各自的收尾失败变体（第 `tool_rounds+1` 次调用抛 `RuntimeError`）。
- [x] 步骤 3.2：`test_run_graph_stops_tools_and_wraps_up_after_max_iterations`：`max_iterations=2`，断言模型共调用 3 次、工具只执行 1 次、`result.content` 为收尾文本。
- [x] 步骤 3.3：`test_stream_graph_stops_tools_and_wraps_up_after_max_iterations`：`max_iterations=2`，断言事件类型序列为 `["tool_started", "tool_completed", "message_delta", "completed"]`，工具只执行 1 次。
- [x] 步骤 3.4：`test_run_graph_unlimited_when_max_iterations_is_zero`：`max_iterations=0` 且模型第 3 次返回普通文本，断言 2 轮工具全部执行、无收尾。
- [x] 步骤 3.5：`test_run_graph_falls_back_to_fixed_text_when_wrap_up_fails` 与 `test_stream_graph_falls_back_to_fixed_text_when_wrap_up_fails`：收尾调用抛错时，结果/事件内容为固定回退文本，且不产出 `error` 事件。

### 任务 4：验证与记录

- [x] 步骤 4.1：运行 `cd apps/backend && poetry run pytest tests/conversation -q`，预期新增用例全部通过、既有用例不回归。
- [x] 步骤 4.2：按真实输出更新 `docs/harness/requests/2026-08-20-agent-loop-max-iterations/verify.md`，并同步 `meta.json` 的 `phase` 与 `updatedAt`。

### 任务 5（增量）：页面工具预算耗尽即停止

**文件：**

- 修改：`apps/backend/app/modules/gateway/router.py`、`apps/backend/app/modules/conversation/runtime.py`、`apps/backend/tests/conversation/test_runtime.py`

**步骤：**

- [x] 步骤 5.1：`gateway/router.py` 的 `_handle_host_tool_result` 失败分支把载荷中的 `code`/`message` 写入 `future` 结果：`{"error": "host_tool_failed", "code": code, "message": message_text}`。
- [x] 步骤 5.2：`runtime.py` 新增 `_PAGE_TOOL_BUDGET_EXCEEDED_MESSAGE` 常量与 `_is_budget_exceeded_outcome()`，识别 `error`/`code`/`message` 中的 `page_tool_budget_exceeded`。
- [x] 步骤 5.3：`_stream_graph` 与 `run_graph` 在工具结果回填前检测预算耗尽：置 `budget_exceeded = True` 并跳出循环；循环结束后不调用模型，直接输出固定提示并 `completed`。
- [x] 步骤 5.4：新增 3 个用例：`_is_budget_exceeded_outcome` 识别、`run_graph`/`stream_graph` 预算耗尽即停（模型只调用 1 次、事件序列含固定提示与 `completed`）。
