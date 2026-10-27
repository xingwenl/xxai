---
id: 2026-10-27-ai-sdk-message-usage
tier: B
risk: medium
approval:
  required: true
  granted: true
  grantedAt: 2026-10-27
  grantedBy: 用户
  grantedNote: "停点确认：按 spec 六条要点全量实现（消息元数据承载逐轮明细、快照新增 usage、缓存字段归一化、内联明细卡、会话累计放消息列表末尾），并接受「存量消息不补明细」的局限。"
  why: ["API 契约变化：embed 消息快照 ConversationMessageRead 新增 usage 字段；message_completed 事件 payload.usage 增加缓存与模型键", "跨 apps/ 改动：apps/backend 与 apps/ai-sdk 同时修改"]
---

# 内嵌 SDK 逐轮用量与缓存命中展示

## 目标与范围

目标：`apps/ai-sdk` 悬浮/内嵌 widget 里，每条 assistant 回复底部显示「用量」chip（如 `用量 1.3M tok`），点击展开明细卡：标题「本轮用量」+ 右侧总量，下面依次为「提供方/模型 / 缓存命中率 / 未缓存输入 / 缓存读取 / 输出」——与 DSH Web GUI 的「本轮用量」弹层同字段、同口径（用户截图）。消息列表末尾再显示本会话累计（总量 + 缓存命中率）。刷新页面、切换会话后仍能显示（历史回放）。

范围外：管理后台 `apps/front` 的会话查阅页不显示用量；REST 非流式 `ChatResponse` 不加字段；控制台 SSE 的两处 assistant 写库点（`conversation/services.py:326-340`、`:862-873`）不补用量元数据；不改 `model_usage_records` 表与计费口径；不引 tokenizer 做估算；不改鉴权与权限边界；不给存量（本方案上线前）消息补历史明细。

受影响面：`apps/backend/app/modules/gateway/runtime.py`、`agent_runtime/{usage.py,langchain_adapter.py,events.py}`、`conversation/serializers.py`、`embed/schemas.py`；`apps/ai-sdk/src/core/{types.ts,usage.ts}`、`src/history/map-history.ts`、`src/ui/{usage-view.ts,components/UsageChip.vue,ChatMessage.vue,ChatMessageList.vue,styles/index.css}`。

## 来源与方案比较

- **缓存计数已有官方归一化层**：本机 `langchain-core 1.5.1` 把 provider 缓存计数规范化到 `usage_metadata["input_token_details"]{"cache_read","cache_creation"}`（`apps/backend/.venv/lib/python3.12/site-packages/langchain_core/messages/ai.py:47-66,115-147`）；`langchain-openai 1.4.1` 把 OpenAI 的 `prompt_tokens_details.cached_tokens` 映射成 `cache_read`，且 priority/flex 服务档会写成 `priority_cache_read` / `flex_cache_read`（同 venv `langchain_openai/chat_models/base.py:4139-4165`）。上游同一实现：https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/ai.py ；字段来源官方文档 https://platform.openai.com/docs/guides/prompt-caching （均调研于 2026-10-27）。本仓 `_normalize_usage` 现在只保留三个 int（`agent_runtime/langchain_adapter.py:29-46`），缓存明细在这里被丢掉。
- **口径参照 DSH Web GUI**（用户截图，2026-10-27）：「缓存命中率 = 缓存读取 /（缓存读取 + 未缓存输入）」，「未缓存输入 = 总输入 − 缓存读取」，「输出 = completion_tokens」，「总量 = total_tokens」；`1,239,936 / (1,239,936 + 79,386) ≈ 94%` 与截图一致。
- 方案比较：（甲）**逐轮用量明细写进 assistant 消息的 `message_metadata["usage"]`，消息快照新增 `usage` 字段** —— 采纳；（乙）给 `model_usage_records` 加 `cache_read_tokens`/`cache_creation_tokens` 列并新增迁移，快照按 message_id 回查 —— 单一事实源、存量会话也能显示，但命中 `**/models.py` + `**/migrations/**` 升 A 档（spec+ADR+拷问），且把观测展示与计费事实绑在同一张表上；（丙）只在前端用实时 `message_completed` 事件展示、不落库 —— 零后端改动，但刷新即丢，做不到历史回放。

## 被否决的选项

1. **乙（给 `model_usage_records` 加缓存列 + 快照回查）**：能覆盖存量会话，但要动 `models.py` 与迁移（A 档），一个"看用量"的展示需求换来表结构变更与计费表耦合；且 `record_model_usage` 的写入点是计费事实，展示字段混入会让后续计费口径演进受限。留作后续若确实要"给历史补明细"时单独立 A 档。
2. **丙（纯前端展示，不落库）**：刷新、切换会话即丢，用户明确要求的是"每个对话都有"的常驻信息，不满足。
3. **明细里只显示总量与输出（少几行）**：用户已明确选「照抄截图全量」，缓存命中率正是这次要看的核心指标，不能省。
4. **会话累计再加一个后端聚合端点（如 `GET /embed/conversations/{id}/usage`）**：`fetchHistory` 本来就一次拉全量消息（`client.ts:1456`，无分页），客户端按消息求和即得，且与逐轮 chip 同源不会互相矛盾；多一个端点等于多一套契约与查询。
5. **用 provider 名硬编码映射（如 model_name 里含 `deepseek` 就显示 DeepSeek）**：模型名不是可靠提供方标识，靠字符串猜会误导；改为落库时按 `resolved_model.base_url` 的主机名推导，取不到就不显示该行。

## 停点判断

- 触发审批：**API 契约变化**（`ConversationMessageRead` 新增可选 `usage`；`message_completed.payload.usage` 从三个 int 扩为含缓存/模型键），且**跨 `apps/` 改动**（backend + ai-sdk）→ B 档，`approval.required: true`。
- 未触发：数据模型变化（不加表/列/迁移）、架构边界变化（沿用"消息元数据 = 消息自带展示附属数据"的既有位置，与 tool_snapshots 并列）、鉴权与权限行为变化（快照仍走原 `get_embed_message_snapshot` 校验）。
- 本 spec 经用户确认后进入实现；实现完成跑 `tools/harness/verify.sh 2026-10-27-ai-sdk-message-usage`，真实输出落 `verify.md`。

## 变更点

1. 新增 `agent_runtime/usage.py`：`decorate_usage(usage, *, model, provider)` 把归一化用量整理成展示用字典（int 校验、`total` 缺失时按 prompt+completion 补齐、附加 `model`/`provider`），`usage_from_message_metadata(metadata)` 按白名单反序列化（坏数据返回 `None`），`provider_from_base_url(base_url)` 取主机名推导提供方标识。
2. `agent_runtime/langchain_adapter.py` 的 `_normalize_usage` 增加缓存字段：从 `input_token_details` 取 `cache_read`/`cache_creation`（兼容 `priority_`/`flex_` 前缀，多个前缀键求和），并回退读 `prompt_tokens_details.cached_tokens`、`prompt_cache_hit_tokens`；取不到就不输出该键（否则 `merge_usage` 会把缺失当 0 累加，UI 会误报 0%）。
3. `agent_runtime/events.py` 的 `message_completed` 增加可选 `usage` 覆盖参数，默认仍用 `result.usage`，token 统计口径不变。
4. `gateway/runtime.py` 的 `_finish_embed_chat` 增加 `provider_name` 参数：用 `decorate_usage` 生成 `usage_payload`，写入 assistant 消息 `message_metadata["usage"]`（与 `tool_snapshots` 并列），`record_model_usage` 仍只取三个 token 数，`message_completed` 事件改用 `usage_payload`；调用点用 `resolved_model.base_url` 推导 provide_name。
5. `conversation/serializers.py` 的 `build_message_snapshots` 输出 `usage` 字段（来自消息元数据白名单解析），embed 与后台共用同一投影。
6. `embed/schemas.py` 新增 `MessageUsage`（`prompt_tokens/completion_tokens/total_tokens` 必填，`cache_read_tokens/cache_creation_tokens/model/provider` 可选），`ConversationMessageRead` 增加 `usage: MessageUsage | None = None`。
7. 新增 `apps/ai-sdk/src/core/usage.ts`：`parseUsage(raw)`（兼容实时事件的蛇形字段与历史快照）、`sumUsage(list)`、`cacheHitPercent`、`uncachedPromptTokens`，纯函数。
8. `core/types.ts` 增加 `ModelUsage`/`SessionUsage`，`Message.metadata.usage` 仍存原始蛇形字典（保持既有 `client.test.ts:200-206` 契约）。
9. `history/map-history.ts` 把快照的 `usage` 映射进 `metadata.usage`，历史回放不再丢用量。
10. 新增 `ui/components/UsageChip.vue`（chip + 内联明细卡，排版照截图：灰底圆角卡、行左标签右数值、「本轮用量」标题右侧总量）与 `ui/usage-view.ts`（chip 文案、明细行、缺省行隐藏、格式化复用 `context-ring.ts` 的 `formatTokens`）。
11. `ui/components/ChatMessage.vue` assistant 消息底部插入 chip；`ChatMessageList.vue` 末尾渲染本会话累计行（无用量时不渲染）；`styles/index.css` 补齐 chip/明细卡/累计行样式，沿用现有 CSS 变量与 `xxai-` 前缀。
12. 测试与脚本：后端 `tests/agent_runtime/test_usage.py`、扩展 `tests/embed/test_message_snapshot.py`（快照 usage 与坏数据容错）、`tests/gateway/test_chat_flow.py` 断言元数据落库；SDK `core/__tests__/usage.test.ts`、`ui/__tests__/usage-view.test.ts`、`client.test.ts` 历史映射用例；`tools/harness/verify/<id>.sh` 逐条跑真实命令。

## 验收标准

1. `pytest tests/agent_runtime -q`：`input_token_details.cache_read=100`、`priority_cache_read` 前缀、`prompt_tokens_details.cached_tokens` 三种来源都归一化为 `cache_read_tokens`；没有缓存信息的用量不产出该键；`merge_usage` 跨轮相加不报错。
2. `pytest tests/embed/test_message_snapshot.py -q`：带 `message_metadata["usage"]` 的消息快照输出完整 `usage`；元数据里 usage 是坏类型/多余键时输出 `None` 而非 500，且其他字段不受影响。
3. `pytest tests/gateway -q`：一轮 embed 对话后 assistant 消息 `message_metadata["usage"]` 含总量与模型名，`record_model_usage` 仍只写三个 token 数（不回归既有测试）。
4. `pnpm --filter xxai-agent test`：usage 解析/求和/格式化用例通过，覆盖 `1,332,145` → `1.3M tok`、命中率 `94%`、未缓存输入 `79,386`、缺缓存字段时明细只显示总量与输出。
5. `pnpm --filter xxai-agent type-check && pnpm --filter xxai-agent build`：类型与产物构建通过。
6. `verify.md` 里显式记录「真实浏览器里一轮对话后 chip 出现、刷新后仍在、会话累计与逐轮之和一致」的手动确认结论，或列为未执行项并写原因。
