# 验收记录

## 验收结论

对照 `spec.md` 的验收标准逐条核对：

| 验收标准 | 结论 | 证据 |
|---|---|---|
| 任意提前结束路径下，内层模型 Task 都在请求级 Session 关闭前结束 | 达成 | `tests/gateway/test_stream_session_teardown.py`（模型 Task 清理早于任一 Session `close`）；`tests/agent_runtime/test_stream_task_ownership.py` |
| 请求级 Session 只被消费方 Task 使用；工具执行使用独立 Session | 达成 | `tests/conversation/test_tool_session_isolation.py::test_prepare_binds_tool_execution_to_tool_session`；网关侧 `produce_embed_request` 新增第二个 Session | 
| 工具能读到请求方已提交的会话数据 | 达成 | `tests/conversation/test_tool_session_isolation.py::test_tool_session_sees_only_committed_request_data` |
| WS 与 REST/SSE 两条流式路径行为一致 | 达成 | 两条路径都改为「持有 Session 的作用域负责 join」；`tests/gateway`、`tests/conversation` 回归全通过 |
| 现有 `tests/gateway`、`tests/conversation`、`tests/agent_runtime` 用例全部通过 | 达成 | 295 passed, 1 skipped |
| 新增回归测试能拦住退化 | 达成 | 三处修复点均做过反向验证，见 `verify.md` |
| `ruff check` 通过 | 达成 | All checks passed |

结论：本 request 的实现与验证已完成，可以视为**实现闭环完成**。

需要说明的两点：

- 本 request 与 `2026-08-24-ai-sdk-question-flow` 的 `2026-09-18` 修复是**两个独立缺陷**：前者修问题 1（入站 `requestId` 被当作聊天请求 ID 过滤，导致 `question_answer` / `confirmation_resolve` / `host_tool_result` 被静默丢弃），本 request 修问题 2（Session 跨 Task 并发 + 内层 Task 未 join）。问题 1 的修复让问答链路能继续跑，从而更频繁地触发问题 2，二者需要一起生效。
- 两个修复目前都**尚未提交**；工作区还混有若干与本 request 无关的未提交改动（Markdown 图表、OpenCode 兼容、店铺技能等），提交时需要按任务拆分，不要一并带上。

## 剩余风险

- 数据库连接占用上升：每个流式请求会同时占用请求级 + 工具 Session（外加连接级宿主工具 Session）。当前未调整连接池配置，并发流式请求较多时需要后续评估。
- Session 归属仅覆盖网关与 REST/SSE 两条已确认的入口；`build_langchain_runtime` 的非流式路径（`execute_chat`）在同一 Task 内执行，不受影响，但若将来新增其它流式入口，必须同样登记并 join 模型 Task。
- 工具 Session 只能看到已提交数据，依赖 `BaseRepository` 每次写操作都 commit 的既有约定；该假设已有测试锁定，但若今后出现"先 flush 再调工具"的写法会失效。
- 未做真实 PostgreSQL + 真实模型调用的端到端复现；建议本地起后端 + SDK 示例，完整走一次"提问 → 回答 → 工具调用 → 收尾"，确认不再出现 `agent_request_failed` / `IllegalStateChangeError`。
- `AgentRuntime.stream` 的 `asyncio.create_task` 结构未重构（非目标）：模型 Task 与消费方 Task 仍分属两个 Task，本次只是把生命周期收口做确定；彻底同 Task 化列为后续 request 的候选。

## 人工验收记录

- 2026-09-18：用户在对齐根因（跨 Task 共用 Session + 内层 Task 未 join）后回复“可以 帮我修吧，一起修”，明确批准 P0 + P1 同批实现，并认可新建本 request。
- 本 request 未触发架构边界、数据模型、API 契约、鉴权权限四类人工确认条件（`spec.md` 停点判断均为“否”）。
- 额外人工回归：尚未执行；建议按上面「剩余风险」中的端到端步骤本地观察一次。
