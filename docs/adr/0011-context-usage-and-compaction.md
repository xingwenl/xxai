# 上下文占用计量与上下文压缩

## Status

accepted

关联 Harness request：`docs/harness/requests/2026-10-19-context-usage-and-compaction/`（tier A，spec 与验证证据见该目录）。
术语（上下文占用、上下文压缩、保留边界、压缩摘要）见 `CONTEXT.md`。
本 ADR 修订了「上下文超预算就删最旧轮次」这一既有护栏的地位：护栏保留为兜底，压缩成为首选动作。

## Decision

1. **占用是「真值基线 + 增量估算」，不是跨轮累计 usage。** 现有 `message_completed.payload.usage` 是 `merge_usage` 累加出来的跨轮总量（`contracts.py:38` 的 docstring 明确要求保持这一口径），拿它当「当前上下文占用」会把历史轮次的输出重复计入，数值只增不减。占用改由「上一次模型调用返回的输入 token 数」作基线，加上该次调用之后新增内容的字符估算得到（Pi `estimateContextTokens` 口径，`compaction.ts:202-232`）。之所以不引 tokenizer：基线本身已经含系统提示、工具定义与全部历史，只有增量需要估，字符估算是保守的近似即可。
2. **压缩结果落库成独立表 `conversation_context_compactions`，而不是改写消息。** `conversation_messages` 是原始历史，是回放、审计与后台查阅的唯一真相；压缩只改变「模型可见视图」。压成表还带来保留边界、压缩前后 token 数与摘要请求自身用量可以逐次审计。这与 Pi 把 `CompactionEntry` 追加进会话条目流、`buildSessionContext()` 只产出视图是同一种分离。
3. **触发阈值取 `min(window - reserve_tokens, floor(window * context_input_ratio))`。** 只用 Pi 的 `window - reserve` 会在窗口很大时把阈值抬到现有护栏预算 `0.75 * window` 之上，导致护栏先于压缩把历史硬删掉——压缩永远不会触发。取两者较小值，保证压缩先于硬截断发生。
4. **切点必须落在既有护栏的 unit 边界上。** `_split_guardrail_units`（`conversation/runtime.py:570-604`）已经把「assistant 的工具调用 + 紧随其后的工具结果」合成一个单元，正是因为历史版本按单条消息删除时切出过非法序列。压缩复用同一套边界，切出的视图天然是可发给模型的合法序列。
5. **摘要是同一个对话模型的一次性请求，失败就放弃本次压缩。** 复用 `build_chat_model`（`agent/services.py:300`）避免引入第二个模型配置；`maxTokens = floor(0.8 * reserve)` 沿用 Pi。摘要为空、或输出被长度截断（finish reason 为 length）时不写行、回退现有硬截断护栏，并向客户端报 `context_compacted{ok:false}`。理由：把不完整摘要当上下文，会让模型基于错误前提继续工作，比丢历史更糟（Pi 同样拒绝写入，`compaction.ts:542-552`）。
6. **压缩后的模型可见上下文 = 摘要（SystemMessage）+ 保留边界之后的消息。** 摘要是系统给出的既有前提，不是任何一方说的话，所以用 `SystemMessage` 注入而不是伪造一条 user/assistant 消息。保留边界之前的消息不再进上下文，但仍在库里。
7. **再次压缩时新摘要并入旧摘要，而不是拼接两份。** 多次压缩若各留一份摘要，重叠区间会累积互相矛盾的描述；并入后一条会话始终只有一份权威摘要（Pi `UPDATE_SUMMARIZATION_PROMPT` 语义）。旧行保留作审计，不删除。
8. **新增 `context_usage` 与 `context_compacted` 两个运行事件，protocolVersion 仍为 1。** 只做加法：旧客户端把未知类型归一到 `unknown` 后丢弃，不报错。占用是每轮持续量、压缩是离散事件，两者形状与演进节奏不同，不合并成一个事件。
9. **手动压缩走 REST `POST /embed/conversations/{id}/context/compact`，不走 WS 出站帧。** 压缩是可能数十秒的长任务，REST 可同步返回压缩前后快照（`tokensBefore`/`tokensAfter`/`percent`），且 SDK 已有 token + Bearer 的调用姿势；WS 需要新增出站帧与异步结果事件两套东西。端点用会话行 `SELECT ... FOR UPDATE` 串行化同一会话的并发压缩，无内容可压时幂等返回 `compacted=false`。
10. **四个对话入口（REST 非流式、REST SSE、确认后续跑、embed WS）共用同一个上下文构造器。** 现在四条路径各自注入 `context_transform` 闭包，压缩与占用必须对四条路径语义一致，否则「同一会话在 WS 与 SSE 上占用不同」这类问题无从定位。
11. **顺带修复 REST/SSE 历史被静默丢弃的缺陷。** `build_langchain_messages(history=...)` 收到的是 ORM 行对象，而 `messages_for_model`（`langchain_adapter.py:114`）只放行 LangChain 消息类型，其余静默丢弃——REST/SSE 路径上历史等于不存在。压缩若建在这个缺陷之上会「压了但没人看见」，所以本次把 ORM 行 → LangChain 消息的转换收口成一个函数，四条路径统一使用。
12. **窗口未知时只显示绝对 token 数，不显示百分比与环，手动压缩仍可用。** `resolve_context_window_tokens` 会对未登记模型返回 `None`（护栏静默关闭）。此时编造分母会让用户看到假信息；显示绝对值并保留手动入口是诚实的降级。
13. **不做「在消息流里插入摘要卡片」，不做会话分支，不动管理后台。** 摘要卡片会牵动消息列表渲染与历史回放契约（`getMessages` 的 role 语义、桌面与扩展消费），本轮收敛为 header 状态与压缩后刷新；管理后台的占用展示另立需求。

## Considered Options

1. **只保留现有硬截断护栏（不做摘要）** ——零额外成本，但历史不可逆丢失、用户无从得知丢了什么；实测已出现「删掉的历史拿不回来」。
2. **只清空工具结果（Anthropic 语境管理里「最安全、最轻」的压缩）** ——损失最小且不需要额外模型调用，但没有解决长对话本身的语义膨胀，且工具结果与 `tool_call_id` 强配对，清空后要么留占位要么破坏配对，需要额外一致性处理。
3. **在 `apply_runtime_context_guardrail` 内联做压缩、不持久化保留边界** ——改动最小，但每次请求都要重新决定「哪些进摘要」，且新消息会把老消息挤出保留窗口，出现既没被摘要覆盖、也没被保留的盲区。
4. **复用 `conversation_messages` 加 `role="summary"` 存摘要** ——省一张表，但 `role` 是读侧公开契约，加未知取值会污染 REST 快照、后台查阅与所有桌面/扩展消费者。
5. **摘要只在单次请求内生成、不落库** ——省一次写入，但每次超限都要重新摘要，成本随轮数放大，且摘要不可审计、不可复现。
6. **按窗口比例或固定轮数触发压缩** ——比例法需要重新标定（Pi 的绝对 reserve/keep 是被验证过的默认值）；固定轮数在单轮很长时仍会爆窗口。
7. **切点允许落在工具结果之前，或不限制切点** ——会切出「工具调用与结果分离」的非法序列，正是现护栏 `_split_guardrail_units` 要修的历史坑。
8. **坏摘要落库并标记 incomplete，或失败后重试一次** ——用户至少能看到「压过但没压好」，但模型会基于不完整摘要工作；重试一次要新增重试状态与超时预算，收益不确定。
9. **多份摘要拼接进上下文** ——实现最直白，但重叠区间会累积互相矛盾的内容。
10. **手动压缩同时提供 WS 出站帧入口** ——对 WS 客户端更顺手，但要新增出站帧类型、异步结果事件与超时语义，范围翻倍。
11. **顺手给 REST 非流式 `ChatResponse` 补 context 字段** ——调用方一致性更好，但会改 `conversation/schemas.py` 的公开契约，而本次 SDK 需求不需要，留作独立 request。
12. **摘要请求改用专用的便宜模型** ——成本可能更低，但引入第二个模型配置、回退分支与「摘要模型不可用」这一新失败模式。
13. **用一个事件同时承载占用与压缩** ——少一个事件类型，但两者的生命期与消费方式不同，混在一个 payload 里无法独立演进。

## Consequences

1. **数据模型变化**：新表 `conversation_context_compactions`（迁移 `20261019_0042`），每个字段带中文注释。迁移必须与镜像同版本发布（api 启动命令是 `alembic upgrade head && uvicorn ...`）。
2. **线协议新增两个事件**：`context_usage`、`context_compacted`，`protocolVersion` 仍为 1。共享 golden（`apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json`）与后端 `tests/gateway/test_event_parity.py` 必须同步更新，否则两端一致性测试失败。
3. **新增 REST 端点**：`POST /embed/conversations/{conversation_id}/context/compact`，鉴权为 embed claims + 会话归属校验（非本主体 404，不泄露存在性）。响应体是压缩快照，失败是普通 REST 错误。
4. **REST/SSE 的历史从此真正进入模型上下文**，这会改变这两条路径上已存在会话的行为：此前它们实际上「每轮从零开始」。修复后 token 消耗会上升、响应可能变慢——这是修正缺陷的必然后果，需要在上线说明里写明。
5. **压缩会破坏 prompt 前缀缓存**：压缩后模型可见前缀被重写，下一次主模型请求的 prefix cache 必然失效。本次不做额外缓解（摘要请求与主请求本就不同前缀），但这是一次可感知的延迟尖峰，观测时不要误判为回归。
6. **自动压缩在请求内联完成**：压缩耗时（一次完整模型调用）会加到触发压缩的那一轮请求上。阈值取 `min(window - reserve, floor(window * ratio))` 预留了余量，但极长的单轮仍可能先触发护栏硬截断。
7. **占用的两种来源必须在 UI 上可区分**：`context_usage.source` 取 `provider` 或 `estimated`，窗口未知时 `windowTokens`/`percent` 为 `null`。客户端显示逻辑必须容忍这三个空值，不能假设百分比总存在。
8. **测试需要 stub 模型**：摘要请求走真实 `build_chat_model` 工厂，单测里必须替换为 stub（仓库已有 `apps/backend/tests/**` 的 stub 模式），否则测试会打真实上游。
9. **`conversation_context_compactions` 只增不删**：一行一次压缩，用于审计；长期运行需要按 TTL 归档或只读最近一行，本次按「读最近一行」实现，不做清理作业。
