---
id: 2026-10-19-context-usage-and-compaction
tier: A
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-19
  grantedBy: 用户
  grantedNote: "停点确认：按 spec 的 12 条变更点全量实现（含新表、两个新事件、REST 手动压缩端点、四入口上下文构造收口与 REST/SSE 历史缺陷修复）。"
  why: ["数据模型变化：新增 conversation_context_compactions 表（摘要、保留边界、压缩前后 token 数）", "API 契约变化：线协议新增 context_usage / context_compacted 两个事件；新增 REST POST /embed/conversations/{conversation_id}/context/compact", "架构边界变化：四个对话入口的上下文构造收口到同一个构造器，压缩成为 agent_runtime 的新观测 seam"]
---

# 上下文占用显示与上下文压缩

## 目标与范围

目标：内嵌 widget 能显示当前会话「占了多少上下文」（header 占用环 + 百分比 + 绝对量），接近窗口上限时自动压缩，并支持用户手动压缩；压缩由同一个对话模型把较早的历史摘要成固定小节，原始消息全量保留在库。

范围外：不在管理后台（`apps/front`）显示占用；不给 REST 非流式 `ChatResponse` 补 context 字段；不在消息流里插入「已压缩」摘要卡片；不做会话分支/回滚；不引 tokenizer；不删除或改写 `conversation_messages` 的原始消息；不改鉴权语义（复用 `get_current_embed_claims` + 会话归属校验）。

受影响面：`apps/backend/app/modules/conversation/{models,repositories,runtime,services}.py`、`apps/backend/app/modules/agent_runtime/{hooks,loop,contracts,events}.py`、`apps/backend/app/modules/gateway/runtime.py`、`apps/backend/app/modules/embed/{router,schemas}.py`、`apps/backend/app/core/config.py`、`apps/backend/migrations/versions/`、`apps/ai-sdk/src/core/{protocol,types,client}.ts`、`apps/ai-sdk/src/ui/**`。

## 来源与方案比较

本机 Pi（`/Users/lixingwen/xw/git/pi`，调研日期 2026-10-19）与 OpenAI Codex（`codex-rs/core`，同日）第一手事实：

- **占用计量 = provider 真值基线 + 尾部本地估算**：`estimateContextTokens(messages)` 取最后一条有效 assistant usage 作基线（跳过 aborted/error/全零），只对该 usage **之后新增**的消息做本地估算，返回 `{tokens, usageTokens, trailingTokens, lastUsageIndex}`（`packages/coding-agent/src/core/compaction/compaction.ts:202-232`）；Codex 同口径，字段注释逐字 "server-observed usage replaces estimated resume/recompute baselines when available"（`codex-rs/core/src/state/auto_compact_window.rs`）。基线本身已含 system prompt、工具定义与历史（都是同一次请求的 input），所以只有增量需要估算，也不需要 tokenizer。
- **压缩阈值用绝对余量而非比例**：`shouldCompact = contextTokens > contextWindow - reserveTokens`，默认 `reserveTokens=16384`、`keepRecentTokens=20000`（`compaction.ts:126-137`）。
- **切点永不落在工具结果上**：从最新往前累加 token 估算凑够 `keepRecentTokens` 定切点，切点只能是 user/assistant 等消息边界，`toolResult` 被显式排除（`compaction.ts:308-318`）。
- **摘要是同一个模型的一次性请求**，maxTokens = `floor(0.8 * reserveTokens)`，固定小节 `Goal / Constraints & Preferences / Progress / Key Decisions / Next Steps / Critical Context`（`compaction.ts:467-497, 672-674`）；再次压缩用 `UPDATE_SUMMARIZATION_PROMPT` 把旧摘要并入新摘要（`compaction.ts:499-535`）。
- **坏摘要宁可不存**：`stopReason === "length"` 的摘要被拒绝写入（文案 `generation hit the token cap and the summary is incomplete`，`compaction.ts:542-552`）。
- **原始历史永不删除**：压缩结果是会话条目流里的新条目 `CompactionEntry{summary, firstKeptEntryId, tokensBefore, usage}`，`buildSessionContext()` 只产出「发给 LLM 的视图」（`packages/coding-agent/src/core/session-manager.ts:69-80, 395-410`）。
- 方案比较：（甲）新表持久化摘要 + 保留边界，硬截断护栏降为兜底 —— **采纳**；（乙）只保留现有硬截断 —— 零成本但不可逆丢信息，且已出现「删掉的历史拿不回来」；（丙）只清空工具结果（Anthropic context-management 的「最安全最轻」压缩）—— 损失最小但长对话本身的语义膨胀没解决，且本仓工具结果与 `tool_call_id` 强配对，需要额外一致性处理，留待后续。

## 被否决的选项

1. **复用 `conversation_messages` 加 `role="summary"`**：`role` 是读侧契约的一部分（REST 消息快照、后台会话查阅、桌面与扩展消费），加未知取值会污染所有消费者；且消息 `role` 表示「谁说的一句」，摘要不是任何一方说的话。
2. **压缩结果不落库（仅在单次请求内压缩）**：每次超限都要重新摘要，成本随对话轮数放大；摘要不可审计、不可复现。
3. **用窗口比例或固定轮数定阈值**：Pi 的绝对 reserve/keep 是被验证过的默认值，比例法需要重新标定；固定轮数在单轮很长时仍会爆窗口。
4. **把 WS 出站帧当作手动压缩入口**：需要新增出站帧类型与异步结果事件，而压缩是长任务；REST 可同步返回压缩前后快照，且 SDK 已有 Bearer 调用姿势。
5. **同时提供 REST 与 WS 两个手动入口**：范围翻倍，两条入口要各自维护事件与错误语义。
6. **坏摘要落库并标记 incomplete，或失败重试一次**：把不完整摘要当上下文用会让模型基于错误前提继续；宁可放弃本次压缩、保留旧上下文（Pi 同结论）。
7. **纯本地字符估算当占用真值**：中文与工具 JSON 场景偏差大，而 provider 真值本来免费拿到。
8. **只修 WS 路径的历史构造**：REST/SSE 用户既看不到占用也不会有压缩效果，缺陷会留在系统里。
9. **在消息流里插入摘要卡片**：需要同时改消息列表渲染与历史回放契约（`getMessages` 的 role 语义），本次收敛为 header 状态 + 压缩后刷新。
10. **切点只允许落在 user 消息，或完全不限制切点**：前者在长工具轮场景压缩近乎无效，后者会切出非法消息序列（现护栏已踩过这个坑）。
11. **把多份历史摘要拼接进上下文**：重叠摘要会累积互相矛盾的内容；并入新摘要（Pi 语义）才有单一权威。
12. **用一个事件承载「占用」与「压缩」两种语义**：占用是每轮持续量，压缩是离散事件，混在同一 payload 里无法独立演进。
13. **摘要请求改用专用的便宜模型**：引入第二个模型配置与回退分支，收益不确定。
14. **顺手给 REST `ChatResponse` 补 context 字段**：会动 `conversation/schemas.py` 的公开契约，而本次 SDK 需求不需要，留作独立 request。
15. **压缩内联在 `apply_runtime_context_guardrail` 里、不持久化保留边界**：可用「从最新往前按预算取」代替保留边界，但新消息会把老消息挤出保留窗口，出现「摘要没覆盖、也没保留」的盲区。

## 停点判断

命中 A 档：数据模型变化（新表）、API 契约变化（两个新事件 + 新 REST 端点）、架构边界变化（四条入口的上下文构造收口 + runtime 新 seam），因此 `approval.required: true`。本 spec 即停点产物，用户确认前不写实现代码。鉴权行为不变（复用既有 embed claims 与会话归属校验），不单独触发审批。

## 变更点

1. `conversation/models.py` 新增 `ConversationContextCompaction`：`conversation_id`（外键 + 索引）、`summary`、`first_kept_message_id`、`tokens_before`、`tokens_after`、`trigger`（auto/manual）、`instructions`（可空）、`model_name`、`usage`（JSON，摘要请求自身用量，用于审计压缩成本），每字段带中文 `comment`；迁移 `20261019_0042_context_compaction.py` 建表加索引。
2. `core/config.py` 新增 `context_compaction_enabled=True`、`context_compaction_reserve_tokens=16384`、`context_compaction_keep_recent_tokens=20000`、`context_compaction_summary_max_tokens=0`（0 表示按 `floor(0.8*reserve)` 推导），均可由环境变量覆盖。
3. `conversation/runtime.py` 新增 `estimate_context_tokens(messages, *, baseline_usage)`（真值基线 + 增量估算）、`resolve_compaction_threshold(window_tokens)` = `min(window - reserve, floor(window * context_input_ratio))`、`plan_compaction_cut(...)`（复用 `_split_guardrail_units` 的 unit 边界）；`build_history_messages` 升级为「摘要 SystemMessage + 保留边界之后的消息」。
4. 新增 `conversation/compaction.py`：中文版摘要 prompt（固定六小节 + 「不要继续对话、不要回答对话中的问题、只输出结构化摘要」）、`compact_conversation(...)`（会话行 `SELECT ... FOR UPDATE` → 读历史 → 定切点 → 摘要请求 → 校验非空且未被长度截断 → 落库 → 返回快照）、`build_context_controller(...)` 返回的 `ContextCompactionController`（实现时的实际形态，替代原先设想的两个工厂函数：`controller.transform` 作 `context_transform`，controller 自身作 `context_metrics`——每轮上报占用、超阈值自动压缩，最后仍走 `apply_runtime_context_guardrail` 兜底）。
5. `agent_runtime/hooks.py` 新增 `context_metrics` seam；`loop.py` 在 `_transform_context` 之后 drain 压缩结果、每轮模型调用后用该轮真值 usage 上报占用，并由 loop 自己 `emit` 两种新事件（注入的 on_event 只能观测、不能向流里插事件）。
6. `agent_runtime/contracts.py` 新增 `AgentEventType.CONTEXT_USAGE`/`CONTEXT_COMPACTED`；`events.py` 新增 `RunEventType.context_usage`/`context_compacted` 与 payload：`context_usage={usedTokens, windowTokens|null, percent|null, source, lastCompactedAt|null}`、`context_compacted={trigger, tokensBefore, tokensAfter, windowTokens|null, percent|null, summaryChars, ok}`。
7. 四条入口改用统一构造器并顺带修历史缺陷：`conversation/services.py:519/934/1297`、`gateway/runtime.py:753`；ORM 行 → LangChain 消息的转换收口成一个函数（现在 REST/SSE 直接传 `ConversationMessage`，被 `messages_for_model` 静默丢弃，等于没有历史）。
8. `embed/router.py` 新增 `POST /embed/conversations/{conversation_id}/context/compact`：body `{instructions?}`，响应 `{compacted, reason, tokensBefore, tokensAfter, windowTokens, usedTokens, percent}`；无可压缩内容幂等返回 `compacted=false, reason="nothing_to_compact"`；非本主体 404；并发由会话行锁串行化。
9. `ai-sdk/src/core/protocol.ts` 两处白名单同步加两个事件（`parseProtocolEvent` 把未知类型归一到 `unknown` 后丢弃，不同步则前端收不到）；`types.ts` 新增 `ContextUsage`/`ContextCompacted`。
10. `ai-sdk/src/core/client.ts`：接住两个事件并维护 `contextUsage` getter，`emit('context_usage')`/`emit('context_compacted')`；新增 `compactContext(instructions?)`（复用 `_getToken()` + Bearer REST）；补订阅 `'client_info'`（QuotaRing 正因未订阅而晚到不刷新）。
11. `ai-sdk/src/ui/context-ring.ts`（纯函数，沿用 `quota-ring.ts` 形状与测试风格）+ `ContextRing.vue` + `ChatWidget.vue` header：占用环与 `used/limit(percent%)` 文案，70/90 两档配色；窗口未知时只显示绝对 token 数；旁边一个手动压缩按钮（飞行中禁用）。
    - 2026-10-19 追加（验收后按用户要求收紧文案）：环旁只留百分比（`11%`，不足 0.5% 时 `<1%`），`used/limit` 绝对量改为 `detail` 字段、只出现在悬停提示里（`上下文已用 11%（12.3K / 1.0M）`）——header 那一行横向空间有限，长文案会把连接状态挤掉。
12. 测试与文档：`tests/conversation/test_context_compaction.py`、`tests/conversation/test_rest_parity.py`（新增「REST 历史真的到达模型」回归用例；原计划的 `tests/gateway/test_context_events.py` 未单独建，等价覆盖在 `tests/agent_runtime/test_context_metrics.py` 与 golden 对拍）、`tests/gateway/test_event_parity.py` 与 `apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json` 同步新增 2 事件、SDK `context-ring.test.ts`/`client.test.ts`、`tools/harness/verify/2026-10-19-context-usage-and-compaction.sh`、README、`docs/CHANGELOG.md`、`docs/adr/0011-context-usage-and-compaction.md`。

## 验收标准

1. 后端 `pytest tests/conversation tests/gateway tests/agent_runtime -q` 全绿，且压缩测试覆盖：切点不拆工具调用与结果、坏摘要不落库、窗口未知只给绝对值、二次压缩并入旧摘要。
2. SDK `pnpm test` 全绿；共享 golden 与后端 `tests/gateway/test_event_parity.py` 同时通过，两个新事件两端形状一致。
3. `pnpm build && node scripts/verify-package.mjs` 通过（产物无密钥、入口齐全）。
4. 端到端可核对：对同一会话连续发消息，header 占用随真实输入 token 增长；把窗口值调小后自动压缩触发，DB 出现一行 `conversation_context_compactions`，且模型可见上下文 = 摘要 + 保留边界之后的消息。
5. 手动压缩 REST 幂等：无可压缩内容返回 `compacted=false`/`nothing_to_compact` 且不报错；并发两次只产生一行新摘要。
6. 摘要请求失败（stub 模型抛错）时不写新行、请求仍能完成（回退现有硬截断护栏），客户端收到 `context_compacted{ok:false}`。
7. `python3 tools/harness/audit.py` 无 ERROR。
