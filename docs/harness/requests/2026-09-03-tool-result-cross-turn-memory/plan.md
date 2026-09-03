# 实施计划：工具查询结果跨轮记忆

## 变更文件

后端（均在 `apps/backend`）：

- `app/modules/agent/models.py`（或 agent_versions 模型所在文件）：新增可空字段 `context_window_tokens: int | None`，带中文 comment（护栏窗口，跟随版本模型；NULL=未显式声明）。
- `alembic/versions/`：新增迁移，为 `agent_versions` 加列 `context_window_tokens`（nullable Integer）。
- `app/core/config.py`：新增配置组：
  - 快照：`tool_snapshot_max_chars=8000`、`tool_snapshot_total_chars=20000`、`tool_snapshot_max_entries=20`、`tool_snapshot_retention_seconds`（默认 None=跟随 `conversation_history_window_seconds`）；
  - 护栏：`context_guardrail_ratio=0.75`、`context_estimate_chars_per_token=1.2`、`model_context_window_map`（DeepSeek v4 系列 1M、chat/reasoner 别名 128K 首批条目）、`context_exceeded_retry_enabled=True`、超限错误识别正则/关键词列表。
- `app/modules/conversation/runtime.py`：新增唯一公共 helper——快照构造 `build_tool_snapshots`（从 `GraphResult.tool_events` 只取 succeeded，结构化分档保留大结果）+ 快照落库 `attach_tool_snapshots`；`build_history_messages` 增加快照收集（按 `tool+params` 去重留新、注入 SystemMessage 含时效指令与防误导两条规则）；模型消息组装处新增预算护栏（窗口×0.75、字符折算 token、按「旧历史→快照→知识引用」裁剪、debug 埋点）；模型调用处包装超限识别与降级重试一次/友好兜底。
- `app/modules/conversation/services.py`：`_finish_stream_chat` 调用唯一 helper 写 `message_metadata["tool_snapshots"]`。
- `app/modules/gateway/runtime.py`：`_finish_embed_chat` 同样调用唯一 helper。

测试与文档：

- `tests/conversation/`、`tests/gateway/` 新增用例（见「测试步骤」）。
- request 目录：`verify.md`（验证证据）、`meta.json`（阶段推进到 verify/implement 状态）。

## 实施步骤

1. **数据层**：agent_versions 模型加字段 → 生成/手写 alembic 迁移 → `poetry run alembic upgrade head`。
2. **配置层**：config.py 加配置项与默认值、DeepSeek 窗口映射、超限错误识别文本表。
3. **快照纯函数（runtime.py）**：先写 `build_tool_snapshots`（含大结果分档保留、单条/条数/合计预算）、去重与注入文本组装（含「带出数据时间」「变更动作需重查」指令、保留期过滤）；配单测。
4. **落库接线**：两个 `_finish_*` 收尾函数调用唯一 helper；配链路单测（两轮消息，第二轮产物含快照 SystemMessage、无伪造 tool 配对）。
5. **护栏与超限兜底（runtime.py）**：窗口解析（版本列 > 模型映射 > 不启用）→ 预算估算与裁剪（旧历史→快照→知识引用；系统提示与当前消息不可裁；被裁快照加「因上下文限制未保留」标注；debug 埋点）→ 模型调用错误识别 → 降级重试一次（system+当前消息+附注）→ 友好文案。
6. **验证**：跑快照/护栏相关单测与 `tests/conversation`、`tests/gateway` 回归 + ruff；记录 `verify.md`（含真实/实录 DeepSeek 两轮对话对照与护栏校准埋点输出）。
7. **收尾**：同步 `meta.json` 阶段；更新 `docs/CHANGELOG.md`（如仓库要求）。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/ -k "snapshot or tool_snapshot or guardrail or context_limit" -q`：新增用例全绿。
- `cd apps/backend && poetry run pytest tests/conversation tests/gateway -q`：既有回归无破坏。
- `cd apps/backend && poetry run ruff check app tests`：无新增错误。
- `poetry run alembic upgrade head && alembic current`：迁移可执行。
- 人工/实录联调（记入 verify.md）：两轮对话——第二轮同范围追问不触发 `order_query`；要求最新数据/变更条件时触发重查；DeepSeek 实录对照 prompt_tokens 校准字符折算系数。

## 回滚说明

- 迁移：`poetry run alembic downgrade -1`（仅新增可空列，低风险）。
- 代码：按单次提交回滚 `apps/backend` 改动即可；快照只写 `message_metadata` JSON，不清库无副作用。
- 行为回归点：`build_history_messages` 无快照时须与现状一致；护栏未命中窗口来源时行为不变；超限降级仅识别到的错误触发。

## 人工确认点

- 已确认：spec 待确认项 ①–⑪（用户 2026-09-03 回复「可以」）。
- 实施中不再引入新的人工确认点；数据模型变化（agent_versions 加可空列）已包含在已批准变更内。
