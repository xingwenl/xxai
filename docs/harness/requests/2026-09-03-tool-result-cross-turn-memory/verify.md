# 验证记录：工具查询结果跨轮记忆

- 验证时间：2026-09-03
- 验证方式：单元测试 + 回归 + 静态检查；迁移与真实模型联调因沙箱网络限制留待人工执行（见「待人工验证」）。

## 单元测试（新增，15 项全绿）

`cd apps/backend && poetry run pytest tests/conversation/test_tool_snapshots.py -q`

结果：`15 passed`，覆盖：

- 快照构造：只收成功态事件（平台真实成功态 `completed` + 兼容 `succeeded` 桩），失败/确认/提问/拒绝/过期不落快照；
- 大列表结果分档：`共 N 条` + `仅保留前 M 条` + 未保留提示，且快照文本不超单条预算；
- 条数/合计预算裁剪：超预算丢最旧条目；
- `attach_tool_snapshots` 元数据合并；
- 历史回放注入：第二轮产物在历史末尾含快照 SystemMessage（含时效指令与「变更动作需重查」规则），无伪造 `tool_calls`/`ToolMessage`；
- 无快照零注入；
- 同 `tool+params` 去重保留最新、不同条件共存、保留期过滤（10s/200s 窗口）；
- `run_graph` 第二轮回放含快照 SystemMessage 且无 ToolMessage；
- 护栏：系统提示与当前消息永不裁剪、先丢旧历史、快照被裁时保留「因上下文限制未保留」提示；
- 超限降级：命中 DeepSeek/OpenAI 兼容错误文本时仅系统提示+当前消息（含附注）重试一次；
- 错误映射：`build_agent_error_payload` 返回友好文案 `context_length_exceeded`、`retryable=false`；
- 窗口解析：版本显式列值 > 模型名映射（DeepSeek v4=1M、chat/reasoner 别名 128K、含 `provider/model` 后缀）> 未命中 None。

补充（2026-09-03 bugfix）：平台真实工具成功态为 `completed`（MCP/Builtin/宿主工具/技能 runner），
快照过滤器原先只认 `succeeded` 会把真实工具结果全部丢弃；已改为双状态词兼容并跳过
拒绝/过期/失败与 error 载荷，新增 2 项回归用例，当前 `test_tool_snapshots.py` 为 17 passed。

## 回归

- `poetry run pytest tests/agent tests/conversation tests/gateway -q`：`168 passed, 1 skipped`
- `poetry run ruff check`（改动文件 + 新增测试）：`All checks passed!`
- `poetry run python -m py_compile`（全部改动文件）：通过

## 配置与模型层改动

- `app/core/config.py`：新增 `tool_snapshot_max_chars/total_chars/max_entries/retention_seconds`、`context_input_ratio`、`context_estimate_chars_per_token`、`context_exceeded_retry_enabled`（默认开启），字段与取值随 `get_settings()` 生效。
- `agent_versions.context_window_tokens`（可空列）：模型字段 + Create/Read schema 已同步；`create_version` 经 `model_dump` 自动透传。

## 待人工验证（需本地数据库与 DeepSeek 实录）

- [ ] `cd apps/backend && poetry run alembic upgrade head && poetry run alembic current`：沙箱网络受限无法执行（迁移文件 `migrations/versions/20260903_0033_agent_version_context_window.py` 已通过 py_compile）。
- [ ] 真实/实录模型两轮对话：第一轮 `order_query` 成功查询；第二轮同范围追问不触发 `order_query` 而能基于快照回答；用户要求最新数据或变更日期区间时触发重新查询。
- [ ] 护栏校准：对照真实 `prompt_tokens` 与 debug 日志（估算 token、各裁剪层丢弃量、注入快照数）校准 `context_estimate_chars_per_token` 默认值（当前 1.2，倾向保守）。
