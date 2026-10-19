# 运行检查点与确认后的续跑

## Status

accepted

关联 Harness request：`docs/harness/requests/2026-10-19-run-confirmation-resume/`（tier A，spec 与验证证据见该目录）。
术语（运行检查点、工具确认、确认记忆、无人值守运行）见 `CONTEXT.md`。
本 ADR 推翻了 `docs/adr/0007-run-event-model-unification.md` 中「SSE 上需要确认的工具仍然无法被批准：本轮不修」这一条。

## Decision

1. **SSE/REST 上「待确认」必须可解决。** 控制台实时对话走 WS（有连接级确认通道），但 REST 流式与微信助手此前只能收到 `confirmation_required` 而没有回复途径。本轮补齐：新增 `POST /api/v1/agents/{agent_id}/runs/{loop_run_id}/resolve`，请求体 `{"approved": bool}`，成功后**以 SSE 返回同一次运行的续跑流**。
2. **续跑是真续跑，不是重发。** 用显式传入的上下文快照在**同一条 `agent_loop_run`** 内继续，而不是让用户重新发一条消息。这样 loop/步骤/消息的记录保持一条时间线，模型也不会重复已经做过的工具调用。
3. **快照放在新建的专用表 `agent_loop_run_checkpoints`，不复用 `agent_loop_runs.metadata`。** 该列的中文注释明确写着「不保存完整 Prompt 或敏感数据」，把整段对话上下文塞进去既违反这条约定，也让它承担两种语义。检查点与 `loop_run_id` 一一对应（唯一约束），状态机 `pending → resolved → consumed`（或 `expired`），`consumed` 时**清空 `context`**，避免整段对话长期留在表里。
4. **解决句柄是 `loop_run_id`。** 检查点与运行一一对应，`confirmation_required` 事件同时带 `confirmationId`（确认记录主键）与 `loopRunId`（运行主键），端点以 `loop_run_id` 定位——它既是归属校验的锚点，也让「客户端只要记住一个 id」成立。
5. **内置工具与 MCP 工具走同一条续跑通路，按 `confirmation_source` 分派执行。** 内置工具：`ToolApprovalService.resolve` 落定用户决定 + `invoke_builtin_tool`（注入「恒批准」裁决器，不再二次弹窗）；MCP：既有的 `resolve_tool_confirmation`。两条通路的结果都归一成 `ToolOutcome` 并把 `call_id` 恢复成检查点里的 `tool_call_id`，模型侧的 tool_call/tool_result 才能配上对。
6. **拒绝也续跑。** `approved=false` 不是「结束运行」，而是「带着『用户拒绝了』这个工具结果继续」——模型需要看到这个结果才能换方案。为此内置工具侧返回 `status="rejected"` 的 `ToolOutcome`（而不是抛错或空结果）。
7. **过期是惰性收尾 + 稳定错误码，不引入后台清扫作业。** 过期只在被访问时发现：`mark_expired` + 把 loop 置为 `cancelled` + 返回 409 `run_confirmation_expired`。TTL 复用 ③a 的 `CONFIRMATION_TTL_SECONDS = 600`。理由：开发期没有真实的长任务压力，为一个「没人处理的确认」常驻一个清扫进程，是拿运维复杂度换一个可以惰性完成的事。
8. **会话内的「确认记忆」对 REST 同样生效。** 复用 ③a 的同一张 `tool_confirmations` 与 `ToolApprovalService.remember_check`：同会话内同类工具批准过一次就不再弹（`financial` 除外）。
9. **非流式与微信助手保持 fail-closed。** 没有等待通道的通路（非流式 REST、微信 `stream:false`）不注入交互式裁决器，写工具仍按「无确认通道」被拒绝（`no_confirmation_channel`）。给它们补确认需要异步通知通道（微信推消息），不在本轮范围。
10. **快照只在进程内传递，不进线协议。** `ToolOutcome.pending_context` 刻意不写进 `model_dump()`，SSE/WS 事件里也不会出现整段对话；事件只带 `confirmationId`/`loopRunId` 这类锚点。
11. **删掉 `ToolOutcome.resume_token`。** 它从落地起就没有生产者也没有消费者，是「以后也许要续跑」留下的空壳；续跑现在有了明确的入口（检查点 + 端点），留着它只会让后来者以为存在一条基于 token 的恢复路径。

## Considered Options

1. **让用户重新发一条消息（不做续跑）** ——改动最小，但 loop 记录断成两条时间线，模型会重复已完成的工具调用，且「确认卡」变成一个假的交互：用户点「批准」后还得自己去对话里再问一遍。
2. **复用 `agent_loop_runs.metadata` 存快照** ——省一张表，但该列注释明令不保存完整 Prompt/敏感数据，且会让「运行摘要」与「可续跑快照」两种语义混在一列里，同时失去唯一约束与状态机。
3. **泛化 MCP 的确认存储（`mcp_tool_confirmations`）来承载检查点** ——它的 `tool_id`/`audit_id` 都是 MCP 专属的 NOT NULL 外键，内置工具既无工具表也无审计表；强行泛化要么放开外键（丢掉审计完整性），要么给内置工具造两张空表。
4. **给 SSE 加一条「解决」REST 端点但不续跑**（只执行工具、让模型下次再答） ——用户会看到「批准了但没有下文」，模型在下一条消息里丢失上下文，等于把 ③a 的 bug 从「不能批准」换成「批准了没用」。
5. **决议后用 resume token 恢复（把 `resume_token` 真正接上）** ——token 不携带运行身份与归属信息，服务端仍要落一份等价于检查点的状态；多一层间接寻址却没有省下任何存储，还会引入「token 泄漏即可续跑别人运行」的鉴权面。
6. **在解决请求里回传整段上下文（客户端持有快照）** ——服务端省一张表，但把对话历史与工具结果的完整性交给客户端，既不可信（客户端可篡改工具结果），又把 payload 放大到不可控。
7. **拒绝时不续跑（直接结束运行）** ——模型无法得知拒绝原因与替代方案，用户体验是「拒绝即失败」。选择带着拒绝结果继续，是为了让模型换一条路。
8. **给过期确认加后台清扫任务** ——可以更及时地把 `pending` 收成 `expired`，但要新增一个常驻进程/调度项与对应观测；惰性收尾在语义上等价（过期确认永远不会被批准），成本接近零。
9. **让非流式 REST 与微信助手也弹确认** ——微信侧需要一个异步推送 + 回执通道，且非流式请求本身没有「等待」的语义载体；本轮保持 fail-closed 并在工具结果里说明原因，等真正有需求再做。

## Consequences

1. **新增公开 API 契约**：`POST /api/v1/agents/{agent_id}/runs/{loop_run_id}/resolve`，鉴权为平台后台用户（`require_current_active_user`）。失败返回普通 REST 错误（404 `run_confirmation_not_found`、409 `run_confirmation_already_resolved`、409 `run_confirmation_expired`、409 `run_resume_unavailable`），成功返回 `text/event-stream`。**同一个端点既可能回 JSON 错误也可能回 SSE**，客户端要按 `Content-Type` 分支处理。
2. **数据模型变化**：新表 `agent_loop_run_checkpoints`（迁移 `20261019_0041`）。迁移必须与镜像同版本发布——`apps/backend/Dockerfile` 构建期 `COPY` 源码，api 启动命令是 `alembic upgrade head && uvicorn ...`，镜像落后于 DB 会直接起不来（实测报 `Can't locate revision identified by '20261019_0041'`）。
3. **`ConversationMessage.status` 新增取值 `waiting_confirmation`**：该列是自由字符串（无 check 约束），只同步了中文注释；这会带来一处 alembic comment 漂移，仓库本就有大量预存在的同类漂移。
4. **确认挂起时的 assistant 占位消息**由此前的 `completed` 改为 `waiting_confirmation`，续跑完成后会被同一条消息的最新状态覆盖（续跑落库的是**新**的 assistant 消息，占位消息保持 `waiting_confirmation`，作为「这里等过确认」的痕迹）。
5. **`_consume_agent_events` 成为首答与续跑的唯一消费循环**：两条路径的消息落库、工具步骤、收尾语义因此不可能漂移；代价是 `stream_chat` 与 `resume_stream_chat` 都必须通过它进出，任何一方想「顺手多做一点」都会作用于另一方。
6. **`pending_context` 是进程内的对象引用**，不是可序列化数据：它只在「事件在同一个进程内被消费」的前提下成立。当前 SSE 与 WS 都在 API 进程内消费事件，因此成立；若将来把事件消费搬到独立进程/队列，这条通路会静默失效（表现为「确认卡出现但无法续跑」）。检查点落库正是这个约束的补偿：跨请求续跑读的是库里的序列化快照。
7. **`gateway/router.py` 的 `pending_mcp_confirmations` 命名债仍在**（③a 引入，同时承载内置工具的确认等待）。本轮的 REST 通路不复用它，因此没有加重这条债。
8. **续跑不复用原始用户消息**：因此不注入 `on_model_error` 的上下文降级重试。若续跑阶段上下文超限，走的是常规模型错误路径（`context_length_exceeded`），不会静默丢历史重试。
9. **检查点表会留下 `pending` 记录**：若客户端拿到确认卡后直接断开且再无人调用解决端点，记录会停在 `pending`，靠 600s TTL 在下次访问时判过期。没有后台清理，表里可能积累过期行——开发期可接受，生产期需要补清扫或按 TTL 归档。
10. **`resume_token` 被删除**，同时删除了 `ToolOutcome.model_dump()` 里的对应字段：这属于线协议 payload 的字段删减（该字段此前恒为 `null`），SDK 侧无消费者，golden 夹具中也不存在。
11. **续跑事件流与首答事件流形状一致**：都由 `run_events_from_stream_item` 映射，因此客户端只需处理一套事件；`confirmation_required` 新增 `loopRunId`（`confirmationId` 由 ③a 引入），这两个字段是调用解决端点的全部输入。
