---
id: 2026-10-19-run-confirmation-resume
tier: A
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-19
  grantedBy: 用户
  grantedNote: "停点确认：按 spec 实现 ③b；拷问两轮共 10 项决策全部按推荐（真续跑、新建检查点表、resolve 返回 SSE、拒绝也续跑、过期惰性收尾、REST/SSE 内置写工具改弹确认、句柄用 loop_run_id、内置+MCP 统一通路、确认记忆对 REST 生效、删 resume_token）。"
  why: ["鉴权或权限行为变化：新增「解决工具确认并续跑同一次运行」的对外入口，需会话归属校验与 CAS 抢占", "数据模型变化：新增 agent_loop_run_checkpoints 表与迁移 20261019_0041", "API 契约变化：conversation 路由新增 runs/{loop_run_id}/resolve；SSE confirmation_required 补 confirmationId/loopRunId/sideEffect/expiresAt；ErrorCode 新增四个码；删除 resume_token", "核心行为变化：REST 流式通路上内置写工具从「拒绝并告知」改为「弹确认并等待」，确认后在同一次运行内续跑"]
---

# 运行级工具确认与续跑（REST/SSE）

## 目标与范围

让 REST 流式（SSE）通路的工具确认**可以被解决，并在同一次运行内续跑**，结束「控制台收到确认后只能让用户重发一条消息」的状态。

范围：

- 新增运行级检查点，持久化「等待确认那一刻喂给模型的完整上下文」，使续跑不依赖进程内存。
- 新增 `POST /api/v1/agents/{agent_id}/runs/{loop_run_id}/resolve`：解决该运行的待确认工具，响应为**续跑 SSE 流**。
- REST/SSE 流式通路注入会话级确认裁决器；内置写工具由 ③a 的「拒绝并告知」改为「落确认行 + 短路 + 出确认事件」。
- 确认来源统一：内置工具（`tool_confirmations`）与 MCP 工具（`mcp_tool_confirmations`）走同一条续跑通路，按来源分派执行。
- 补齐 SSE 确认事件缺失字段；删除死字段 `resume_token`。

不做：WS 通路（③a 已可用）；非流式 REST 与微信助手（无确认通道，维持拒绝并告知）；独立待确认收件箱/列表端点；后台过期清扫作业。

## 来源与方案比较

本机一手调研（`apps/backend`）：

- SSE 遇确认后流即结束：`apps/backend/app/modules/conversation/services.py:1035-1067` 构造 `wait_result` 后 `return`；`_finish_stream_chat`（`:288-377`）把 `loop.status` 置 `waiting_confirmation`，但出站 `agent_loop_completed`/`completed` 的 loop 状态由 `apps/backend/app/modules/agent_runtime/events.py:276-286` **硬编码 completed**。
- SSE 确认事件缺字段：`apps/backend/app/modules/agent_runtime/events.py:642-651` 不传 `confirmation_id`（构造器 `:377-409` 已支持）；`apps/backend/app/modules/agent_runtime/adapters.py:45-49` 把 `metadata` 清空，`sideEffect`/`expiresAt` 因此恒为 null。
- 内置工具在 REST 走不到确认：`apps/backend/app/modules/builtin_tool/services.py:101-108` → `_decide_confirmation`（`:170-180`）→ `no_channel_decision`（`apps/backend/app/modules/tool_approval/contracts.py:72-86`）→ `status="rejected"`；REST 调用方（`apps/backend/app/modules/conversation/router.py:44-99`）从不注入裁决器。
- 续跑入口已存在但零调用：`apps/backend/app/modules/agent_runtime/loop.py:427-451`（`continue_run(messages, outcome, ...)`，docstring 要求「调用方应传入原请求的消息快照」）与 `apps/backend/app/modules/agent_runtime/runtime.py:136-165`（多一个 `prior_result` 用于合并 usage/tool_events）。
- 无法仅凭 DB 重建消息列表：system prompt 现算不落库（`apps/backend/app/modules/conversation/services.py:883-889`）；assistant 的 tool_calls 消息与 ToolMessage 从不落 `conversation_messages`（全仓无 `role="tool"` 写入）；工具结果只落 `agent_loop_steps` 且有摘要截断（`apps/backend/app/modules/conversation/runtime.py:784-790,812-814`）；挂起 outcome 只在内存（`apps/backend/app/modules/agent_runtime/loop.py:401`），`agent_loop_runs.metadata` 恒空。
- 死字段：`resume_token` 生产者 0、消费者 0（`apps/backend/app/modules/agent_runtime/contracts.py:80,94`、`adapters.py:35,45`）。

业界参照：OpenAI Agents SDK Sessions 把会话状态外置存储、由 session 承载「跨请求继续」；Pi 的 compaction 走「阈值触发 + 结构化摘要」。两者共同点是**上下文必须落成显式状态**，而不是指望从业务表反推。本方案因此落检查点而不是重放 `agent_loop_steps`。

## 被否决的选项

1. **只解决确认、不续跑**（用户重发消息）：解决后模型看不到那次工具结果，等于把确认变成一次静默状态变更，语义不完整。
2. **复用 `agent_loop_runs.run_metadata` 存快照**：该列 comment 明确「不保存完整 Prompt 或敏感数据」，且 `AgentLoopRun` 属运行元数据，混入大块上下文会让每次列表查询都拖上 JSON。
3. **只凭 DB 重建上下文**：见「来源与方案比较」——system prompt 与工具链原文都不在库里，重建必然失真。
4. **阻塞式等待**（HTTP 请求内 await 用户决定）：REST 请求生命周期不可控，且与 SSE 的「流可以结束、稍后续跑」语义冲突。
5. **后台清扫作业处理过期**：多一个常驻组件与调度面；惰性收尾（resolve 时判定）已能给出稳定错误码。
6. **同时给非流式 REST/微信弹确认**：非流式调用没有后续通道，弹了必然挂死；维持 ③a 的「拒绝并告知」。
7. **把 MCP 确认也迁进 `tool_confirmations` 统一存储**：需要改写既有 MCP 审计与确认链路，收益只是少一个分派分支，风险远大于收益；本轮按来源分派。
8. **做待确认收件箱/列表端点**：用户 ③a 已否决独立收件箱，确认在对话流里当场解决。
9. **保留 `resume_token` 并改造成对外句柄**：它语义未定义且零消费，新句柄已定为 `loop_run_id`，留着只会多一个似是而非的续跑句柄。
10. **让 `navigation` 也弹确认**：与 ③a 交互式通路一致，navigation 直通。

## 停点判断

- 架构边界变化：否（不新增模块，检查点落在 `conversation` 模块内，续跑复用既有 `continue_run`）。
- 数据模型变化：**是**（新增表 + 迁移 `20261019_0041`）。
- API 契约变化：**是**（新增 resolve 端点、SSE 事件补字段、ErrorCode 扩容、删 `resume_token`）。
- 鉴权/权限行为变化：**是**（新增会话归属校验与 CAS 抢占）。
- 核心功能缺少关键资料：否。
- 结论：`approval.required: true`。已经两轮拷问（`grilling`，两轮封顶），决策见下节。

已定决策（拷问两轮，用户均取推荐）：真续跑；新建专用检查点表；resolve 返回 SSE 续跑流；**拒绝也续跑**；过期惰性收尾 + 稳定错误码；REST/SSE 内置写工具改为弹确认；句柄用 `loop_run_id`；内置 + MCP 统一通路；确认记忆对 REST 也生效；删除 `resume_token`。

## 变更点

1. 新增表 `agent_loop_run_checkpoints`（`apps/backend/app/modules/conversation/models.py`，字段带中文 comment）：`id`、`loop_run_id`（FK `agent_loop_runs.id` CASCADE，**唯一**）、`conversation_id`（FK CASCADE）、`platform_id`/`agent_id`（FK CASCADE）、`user_id`/`platform_end_user_id`（可空，CheckConstraint 恰一个有值）、`confirmation_source`（`tool_confirmations`｜`mcp_tool_confirmations`）、`confirmation_id`、`tool_call_id`、`tool_name`、`tool_type`、`side_effect`、`status`（`pending`/`resolved`/`expired`/`consumed`）、`context`（JSON，适配器层消息快照）、`expires_at`、`resolved_at`、`consumed_at`。
2. 迁移 `apps/backend/migrations/versions/20261019_0041_run_checkpoints.py`（`revision="20261019_0041"`、`down_revision="20261019_0040"`）：建表 + 唯一索引 + 外键，downgrade 对称 `drop_table`。
3. `apps/backend/app/modules/agent_runtime/loop.py:393-412` 等待短路分支新增 `last_turn.metadata["pending_context"] = list(context)`（**活的**消息列表，不序列化；循环仍不接触存储）。
4. `apps/backend/app/modules/agent_runtime/langchain_adapter.py` 新增 `dump_context(messages) -> list[dict]` 与 `load_context(payload) -> list[Any]`：LangChain 消息走 `messages_to_dict`/`messages_from_dict`，`ToolOutcome` 走 `model_dump`/重建；该模块本就是 LangChain 专属，序列化不外泄到循环。
5. `apps/backend/app/modules/agent_runtime/runtime.py:287-307` 把 `pending_context` 装进 `AgentResult`（`contracts.py` 增可选字段 `pending_context`）；`conversation/runtime.py` 的 `GraphResult` 同步增同名可选字段，供流式收尾取用。
6. `apps/backend/app/modules/builtin_tool/`：`schemas.py` 的 `BuiltinToolOutcome` 增 `confirmation_id: int | None` 字段，`services.py` 的 `_deferred_outcome` 在 `metadata` 里带 `side_effect`/`expires_at`/`confirmation_id`。**口径订正**：SSE 的 `sideEffect`/`expiresAt` 恒为 null 并不是 `adapters.py` 清空 metadata（该文件一直是 `getattr(raw, "metadata", {}) or {}`），而是 `BuiltinToolOutcome.metadata` 本身为空；因此修在产出侧，`adapters.py` 不改。
7. `apps/backend/app/modules/agent_runtime/events.py:642-651` 的 `confirmation_required` 传 `confirmation_id=payload.get("confirmation_id")`；构造器 `:377-409` 增可选 `loop_run_id` 并在 payload 输出 `loopRunId`。
8. `apps/backend/app/modules/tool_approval/contracts.py`：`ConfirmationDecision` 增 `defer: bool = False`；新增 `DEFERRED_FOR_CONFIRMATION`；`ErrorCode` 见变更点 12。
9. `apps/backend/app/modules/builtin_tool/services.py`：`_decide_confirmation` 收到 `decision.defer` 时返回 `status="confirmation_required"` 且 `result={"confirmation_id","expires_at","side_effect","tool_name"}`；`apps/backend/app/modules/builtin_tool/schemas.py` 的 `BuiltinToolOutcome.status` 增 `"confirmation_required"`（不影响既有 none/rejected 分支）。
10. 新增 `apps/backend/app/modules/conversation/approval.py`：`InteractiveConfirmationDecider`（`__call__(tool, call)`）：`navigation` → 放行；`remember_check` 命中 → 放行（`REMEMBERED_APPROVAL`）；否则 `ToolApprovalService.request(...)` 落确认行后返回 `ConfirmationDecision(approved=False, defer=True, reason=DEFERRED_FOR_CONFIRMATION)`。仅在 SSE 分支注入（`conversation/services.py` 的 `build_tool_invoker(confirmation_decider=...)`，`stream=True` 时），非流式不注入。
11. `apps/backend/app/modules/conversation/services.py`：等待分支用 `GraphResult.pending_context` + `dump_context` 落检查点（TTL 与 `CONFIRMATION_TTL_SECONDS` 一致）；`_finish_stream_chat` 在等待态写入的 assistant 占位消息 `status="waiting_confirmation"`；出站 loop 终态如实为 `waiting_confirmation`；新增 `resume_stream_chat(...)`：读检查点 → `load_context` → 把末位那个挂起的 `ToolOutcome` **替换**为新结果（而不是追加，避免同一 `call_id` 出现两条工具结果）→ 复用既有装配（模型解析、工具清单、上下文预算）→ `runtime.stream(messages, request_id=loop.request_id)` → 用既有编码器输出后半段 → 写 assistant 消息、`loop.status="completed"`。
12. `apps/backend/app/modules/agent_runtime/error_codes.py` 增 `RUN_CONFIRMATION_NOT_FOUND`/`RUN_CONFIRMATION_ALREADY_RESOLVED`/`RUN_CONFIRMATION_EXPIRED`/`RUN_RESUME_UNAVAILABLE`；`conversation/router.py` 新增 `POST /agents/{agent_id}/runs/{loop_run_id}/resolve`（`Depends(require_current_active_user)`，body `{"approved": bool}`，成功返回 `text/event-stream`；流开始前失败返回结构化 `ApiResponse` + `error_code`）：归属校验（运行 → 会话 → 当前用户/platform admin，否则 404）、检查点 CAS 抢占（抢不到 409）、过期惰性收尾（检查点 `expired`、`loop.status="cancelled"`、确认行 `expire`、409）。
13. 解决后的执行分派（同一端点内）：内置 → `ToolApprovalService.resolve` + 以注册表定义执行工具（注入恒批准裁决器）；MCP → `resolve_tool_confirmation`（`apps/backend/app/modules/mcp/services.py:190-231`）；两者结果统一归一为 `ToolOutcome`（`call_id` 取检查点的 `tool_call_id`）。`approved=False` 不执行，构造 `status="rejected"` 的 `ToolOutcome`，同样续跑。
14. 删除 `resume_token`：`apps/backend/app/modules/agent_runtime/contracts.py:80,94`、`apps/backend/app/modules/agent_runtime/adapters.py:35,45`。
15. 文档：`docs/adr/0010-run-confirmation-resume.md`（含推翻 `docs/adr/0007-run-event-model-unification.md:40`「SSE 上的确认无法被批准，本轮不修」的取舍）、`CONTEXT.md` 补术语「运行检查点」「续跑」，`docs/CHANGELOG.md`。
16. 测试与验证：`apps/backend/tests/conversation/test_run_confirmation_resume.py`（检查点落库、CAS、过期、拒绝续跑、非流式仍拒绝）、`tests/tool_approval/` 与 `tests/builtin_tool/` 补三态用例；`tools/harness/verify/2026-10-19-run-confirmation-resume.{sh,probe.py,stub-model.py}` 真进程跑 SSE 全链路。

## 验收标准

1. `agent_loop_run_checkpoints` 在 DB 中存在（列、唯一约束、外键、中文 comment 齐全），`alembic upgrade head`/`downgrade -1` 往返可逆。
2. SSE 触发 `create_task` 时收到 `confirmation_required`，payload 含非空 `callId`、`confirmationId`、`loopRunId`、`sideEffect="write"`、`expiresAt`、`summary.arguments`。
3. 该次请求结束后 `agent_loop_runs.status == "waiting_confirmation"`，检查点 `status='pending'` 且 `context` 非空。
4. `POST /agents/1/runs/{loop_run_id}/resolve {"approved": true}` 返回 SSE，流中出现续跑后的模型输出，`tasks` 表新增一行，`loop.status == "completed"`，检查点 `status='consumed'` 且 `context` 已清空。
5. `approved: false` 时工具**不执行**（`tasks` 不增），但同样续跑并有模型输出。
6. 同一 `loop_run_id` 第二次 resolve 返回 409 且 `error_code == "run_confirmation_already_resolved"`。
7. 检查点 `expires_at` 已过时 resolve 返回 409、`error_code == "run_confirmation_expired"`、`loop.status=="cancelled"`。
8. 非流式（含微信路径，`stream=false`）行为与 ③a 一致：不出确认事件、工具 `rejected`、`reason == "no_confirmation_channel"`、`tasks` 不增。
9. 会话内确认记忆对 SSE 生效：同一 conversation 内第二次调用同一写工具不再弹确认直接执行。
10. 归属不符（他人会话 / 不存在 / 无检查点）返回 404 且不泄露存在性；`error_code` 为 `run_confirmation_not_found` 或 `run_resume_unavailable`。
11. 全仓无 `resume_token` 残留（grep 零命中）；`apps/backend/tests` 全量目录通过；`python3 tools/harness/audit.py` 无新增 ERROR。
12. 既有回归不变：MCP 在 WS 上的确认与批准行为、③a 的 `navigation` 直通与 `financial` 永不自动批准。
