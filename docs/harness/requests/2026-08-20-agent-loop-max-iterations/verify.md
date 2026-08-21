# 验证记录

## 已执行命令

- `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py -q`：通过，32 个测试通过（含本次新增 5 个用例）。
- `cd apps/backend && poetry run pytest tests/conversation -q`：通过，38 个测试通过，无回归。
- `cd apps/backend && poetry run pytest tests -q --ignore=tests/embed/test_models.py --ignore=tests/user/test_routes.py --ignore=tests/user/test_services.py`：通过，239 passed、1 skipped。
- `cd apps/backend && poetry run ruff check app/modules/conversation/runtime.py app/core/config.py tests/conversation/test_runtime.py`：All checks passed!
- `git diff --check`：通过，无空白错误。
- 增量：`poetry run pytest tests/conversation/test_runtime.py -q`：35 passed；`tests/conversation tests/gateway`：72 passed、1 skipped；跳过既有收集冲突后全量 242 passed、1 skipped；`ruff check`（含 `gateway/router.py`）通过。

## 验证覆盖

- `run_graph` 达到上限（`max_iterations=2`）：工具只执行 1 次，追加一次不带工具的收尾调用，`GraphResult.content` 为收尾文本，warning 日志记录上限与请求工具名。
- `stream_graph` 达到上限（`max_iterations=2`）：事件序列为 `tool_started -> tool_completed -> message_delta(收尾) -> completed`，工具只执行 1 次。
- `max_iterations=0`：视为不设限，2 轮工具全部执行，无收尾调用。
- 收尾调用抛错：流式与非流式路径均回退固定提示文本，不产出 `error` 事件。
- 未超限的既有用例全部通过，`completed` 事件结构与 `GraphResult` 字段未变。
- 配置项：`AGENT_MAX_ITERATIONS` 默认 20，`0` 或负值不设限，`readme.md` 已补充说明。
- 增量：`_is_budget_exceeded_outcome` 能从 `error`/`code`/`message` 识别 `page_tool_budget_exceeded`；`run_graph` 与 `stream_graph` 检测到预算耗尽后模型只调用 1 次、不执行剩余工具、直接输出固定限制提示并正常 `completed`。

## 失败项与例外

- 全量测试存在 3 个既有收集冲突（`tests/embed/test_models.py`、`tests/user/test_routes.py`、`tests/user/test_services.py` 与 `builtin_tool`/`skill_runner` 同名文件模块冲突），与本改动无关，跳过这三个文件后其余全量通过。
- 未在真实模型上联调：收尾提示词对模型的约束效果依赖真实模型遵循度，单测使用 mock 模型验证守卫与回退逻辑。
