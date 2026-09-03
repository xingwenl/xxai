# 设计说明：工具查询结果跨轮记忆（后端智能体复用订单等查询结论）

## 目标

- 解决什么问题：后端智能体（REST `execute_chat`/`stream_chat` 与 ai-sdk embed WebSocket 两条链路）在一轮内通过工具查到订单/店铺等数据后，用户紧接着追问（例如「刚才那批订单里金额最大的是哪笔？」），下一轮模型看不到上一轮的工具查询结果，只能重新调用工具查询或含糊回答。
- 目标用户/调用方：`ai-base` 后端智能体的使用方，重点是 `order_query`（店铺订单）等工具查询场景。
- 完成后可验证结果：第一轮用户问「我的订单」→ 工具 `order_query` 查询并回答；第二轮追问「刚才列表里金额最大的订单是多少」时，模型能直接复用上一轮查询快照回答（stub/实录场景下第二轮不再触发 `order_query` 调用）；当用户要求最新数据或变更时间/查询条件时，模型仍会重新查询。
- 引用 `research.md` 关键结论：业界标准做法（OpenAI Agents SDK Session、LangGraph checkpointer、Dify）是「完整消息原生重放」，但其前提是存储层保留了「assistant(带 tool_calls) + tool(ToolMessage)」完整元组，且 OpenAI 系接口对 `tool` 消息有强配对校验；本仓库现状只存最终 assistant 文本、无任何 `role="tool"` 写入点，无法重建元组。故采用**脱敏摘要快照**方案：把每轮成功工具查询压成带时间戳的事实快照，随历史文本注入下一轮，规避配对约束且 token 可控。

## 范围

### 现状与差距（代码证据）

- `conversation_messages` 表已支持 `role`（含 `user/assistant/tool`）与 `tool_call_id`、`message_metadata`（JSON）字段（`apps/backend/app/modules/conversation/models.py`）；`list_recent_context_messages` 已按该角色集过滤（`repositories.py`）；`build_history_messages` 已能把 `role="tool"` 转 `ToolMessage`（`runtime.py`）。
- **差距：没有任何代码写入 `role="tool"` 消息行**；工具结果只落 `agent_loop_steps.output_summary`（500 字符摘要，不回填模型）；跨轮回填的 `history` 只含 user/assistant 最终文本 ⇒ 下一轮模型拿不到上一轮查询结果。
- 单轮内工具结果回填正确：`_execute_tool_round` 以 `ToolMessage(content=_tool_result_content(...))` 回填（`runtime.py`）；REST 与 embed WebSocket 共用同一图执行，落库都只在 `_finish_stream_chat`（`conversation/services.py`）与 `_finish_embed_chat`（`gateway/runtime.py`）写最终 assistant。

### 本次改动（均在 `apps/backend`，后端）

1. **快照生成（运行时）**
   - 在 `apps/backend/app/modules/conversation/runtime.py` 新增快照构造函数：输入 `GraphResult.tool_events`（或同源工具事件），只收集成功态事件（平台 MCP/Builtin/宿主工具/技能 runner 的成功态均为 `completed`，兼容 `succeeded` 测试桩；拒绝/过期/失败与 error 载荷不落），输出快照条目列表。
   - 每个条目包含：`tool`（工具名）、`queried_at`（查询时间，ISO8601）、`params`（`input_summary` 复用，≤120 字符）、`summary`（同轮回填模型的脱敏结果文本，截断到单条上限）。
   - 失败、`confirmation_required`、`waiting_question`、预算超限等状态的工具不产生快照。
   - **大结果分档保留（不做无脑长度截断）**：快照基于结构化结果（`outcome.result`）构造。结果含列表字段（如 `order_query` 的 `orders` 数组 + `total` 计数）时，保留概要字段（`total`/`page`/`page_size` 等）与预算内尽量多的条目，并显式注明「共 N 条，仅保留前 M 条，其余未保留；需要具体某条时可缩小查询条件重新查询」；非列表/未知结构按长度预算截断并同样提示。预算不超过同轮内工具回填上限（`_tool_result_content` 对宿主工具为 2 万字符），避免保留模型本轮从未见过的内容。
2. **快照落库（两处收尾函数）**
   - `_finish_stream_chat`（REST）与 `_finish_embed_chat`（embed WebSocket）在创建最终 assistant 消息时，把快照写入 `message_metadata["tool_snapshots"]`；`content`/`content_blocks` 保持用户可见内容不变。
   - 快照构造与写入收敛为 `runtime.py` 的**唯一公共 helper**（快照构造函数 + `attach_tool_snapshots` 写入函数），REST/embed WebSocket 两个 `_finish_*` 收尾函数只做调用方，避免两条链路逻辑漂移。
   - 不改表结构、不加列、不新增消息角色值；`message_metadata` 为既有 JSON 列。
3. **历史回放注入（`build_history_messages`）**
   - 遍历窗口内 assistant 消息时读取其 `message_metadata["tool_snapshots"]`，把收集到的快照组装为一段文本，在历史转换结果末尾（即当前用户消息之前）注入一条轻量 `SystemMessage`。
   - 注入文本语义：「以下是此前通过工具查询到的数据快照（数据截至各自查询时间）。回答与快照同范围的问题时可直接使用快照；用户要求最新数据、变更时间/查询条件、或快照缺失时，应重新调用工具查询。」快照文本随后按条目逐条列出（含 `queried_at` 时间戳）。
   - **防误导强化（注入指令追加两条）**：① 基于快照回答时鼓励自然带出数据时间（如「根据您 14:02 的查询结果……」），让用户感知该结论来自快照；② 涉及变更动作（付款、改单、发货、状态更新等）的执行前提判断必须先重新查询最新数据，快照仅用于描述性回答。
   - **同参数去重**：注入前按 `tool + params（参数摘要）` 去重，同一查询条件的多份快照只保留 `queried_at` 最新的一份，避免「同条件多版本结果并存」误导模型判读事实、也避免重复 token 消耗；不同查询条件（不同时间范围/店铺等）的快照正常共存。
   - 无快照时行为与现状完全一致（不注入任何内容）；不构造任何 `role="tool"`/`ToolMessage` 历史，规避配对硬约束。
4. **配置**
   - `app/core/config.py` 新增：
     - `tool_snapshot_max_chars`：单条工具结果快照的文本预算，默认 8000；
     - `tool_snapshot_total_chars`：每轮全部快照的合计预算，默认 20000（与宿主工具同轮回填上限对齐），超出时丢弃最旧条目并保留计数提示；
     - `tool_snapshot_max_entries`：每轮快照条数上限，默认 20，超出丢弃最旧；
     - `tool_snapshot_retention_seconds`：快照可注入回放的时间窗，默认跟随 `conversation_history_window_seconds`（3600s）；需要更长记忆（如按天）时单独调大，历史读取窗口取两者较大值，普通消息与快照各自按自己的窗口过滤回放。
   - 窗口说明：3600s 是**现有整体历史回放窗口**（对所有 user/assistant 消息生效，并非快照专属 TTL）；快照随 assistant 消息行落库后长期保留，仅超过保留期后不再注入模型上下文。
5. **测试（`apps/backend/tests/conversation/`）**
   - 单测：快照构造（成功/失败/等待确认不落）、单条与条数截断上限、`build_history_messages` 注入文本组装、无快照时零注入、窗口外消息不注入。
   - 链路用例：构造两轮消息（第一轮 assistant 带快照 metadata），断言第二轮 `history` 转换产物含快照 SystemMessage 且不含伪造的 `tool_calls`/`ToolMessage` 配对。
   - 回归基线：现有 `tests/conversation`、`tests/gateway` 全绿，ruff 无新增错误。

5. **上下文预算与超限处理（护栏）**
   - 现状：仓库不存模型上下文窗口、组装消息前无总预算校验；超限时 provider 报错，仅被统一 re-raise 为“模型生成失败”，无裁剪与友好兜底。
   - 模型窗口来源（**跟随智能体版本**）：`agent_versions` 新增可空列 `context_window_tokens`（Integer，需 alembic 迁移；`NULL` = 未显式声明）。理由：对话运行时主模型本就取自 `AgentVersion`（`agent/services.py:build_chat_model(version)`，`model_name/base_url/api_key/temperature/model_options` 全部在版本上），窗口与模型同层配置、运行时同源读取；`model_registry`（`PlatformModel`/`AgentModelBinding`）是 embedding 等辅助角色的绑定，主对话不走该链路，窗口放注册表会引入双源。不用 `model_options` JSON 承载窗口：该字段会被 `**model_options` 直接展开传给 ChatOpenAI，混入护栏字段易出错。
   - 窗口决策优先级：① 版本显式设置 `context_window_tokens` > ② 可选内置「模型名 → 已知窗口」小映射 > ③ 均未命中则不启用护栏（保持现状，仅保留超限错误友好兜底）。
   - **DeepSeek 模型名映射首批条目（2026-09-03 按官方 news260424/news250821 核对）**：`deepseek-v4-pro` / `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` → 1,000,000 token；`deepseek-chat` / `deepseek-reasoner`（V3.1/V3.2 时代别名）→ 128,000 token，且官方已于 2026-07-24 15:59 UTC 退役，仅对自有镜像/代理兼容（映射表保留其窗口用于护栏，另在运维提示中提醒迁移）。映射表只收录已知别名；其余模型须在版本上显式填写 `context_window_tokens`。
   - 组装预算：护栏启用时，输入预算 = 窗口 × 0.75（默认预留 25% 给输出；比例可配）；估算按字符数折算 token（`context_estimate_chars_per_token` 默认 1.2，中文保守估算），实际偏差用已记录的 `prompt_tokens` 用量在验证阶段校准。系数初始值**宁保守勿乐观**（估少了会漏裁、滑向降级重试，代价大于多裁一点旧历史）；实现时在组装与模型调用处打 debug 级结构化日志（估算 token、各裁剪层丢弃量、注入快照数、实际 `prompt_tokens`），验证阶段用 DeepSeek 实录对照后把校准系数回写默认值。
   - 超预算裁剪顺序（从可牺牲到不可牺牲）：最旧历史 user/assistant 消息 → 工具快照条目（丢最旧留最新，与 `tool_snapshot_total_chars` 预算叠加生效）→ 知识引用（在检索层已由 `knowledge_context_max_chars` 限量，不单独进入运行时裁剪）→ 系统提示与当前用户消息不可裁剪。裁剪发生在组装后、模型调用前；若有快照被裁剪，注入文本注明「部分工具快照因上下文限制未保留」，引导模型在需要时重新查询。系统提示+当前消息仍超预算（如超大粘贴文本）时护栏记录告警，交由下方超限兜底降级重试处理。
   - 超限兜底（裁剪后仍命中的动作链）：
     1. 识别：DeepSeek/OpenAI 兼容报错文本 `This model's maximum context length is <N> tokens. However, you requested <M> tokens (...)`，或错误码 `context_length_exceeded`；
     2. **自动降级重试一次**（可配置开关，默认建议开启）：仅保留系统提示 + 当前用户消息，并在用户消息文本附注「此前对话与工具查询结果因超过模型上下文上限未纳入本次计算，需要时可重新查询」，让模型诚实回答或主动重查，而不是给用户一个错误页；
     3. 降级仍失败或未开启降级：返回友好文案「对话或本次查询结果超过模型上下文上限，请缩小查询范围或开启新对话」，记录日志与错误 payload，不再裸抛内部错误。
   - 实际触发场景：V4 的 1M 窗口下主要是单轮工具迭代累积（最多 20 次 × 每条回填上限）与长历史叠加；128K 旧别名更易触发，护栏默认裁剪即可覆盖绝大多数情况。
   - 生效链路：与快照一样位于对话运行时公共路径，REST 与 embed WebSocket 同享。

### 生效链路说明

- REST 与 embed WebSocket 都经由 `conversation/runtime.py` 的图执行与 `build_history_messages` 回放，本次改动两链自动同享，无需改对外协议。
- 前端与 ai-sdk：零改动（快照存 `message_metadata`，不进可见 `content`/`content_blocks`，前端按既有渲染逻辑展示）。

## 非目标

- 不做「完整原生重放」：不落库中间 assistant(带 `tool_calls`) 与 `role="tool"` 消息行，不把工具调用链整链回放（记录为远期演进方向，需先升级消息存储模型）。
- 不做快照语义摘要（调用 LLM 压缩）：本轮仅按长度截断，避免额外模型调用与成本。
- 不做独立快照 TTL/过期清理：复用 `conversation_history_window_seconds` 时间窗语义。
- 不改 `message_send`/embed WebSocket 协议、不改工具契约、不改工具层白名单行为。
- 不落敏感原文：快照仅取同轮已回填模型的脱敏结果文本（工具层白名单已剔除手机号等隐私字段）并截断。
- 不覆盖「同轮内」的记忆行为（单轮内工具回填已正确，无改动）。
- 不做超大结果的全量持久化与上下文外检索：数据规模超过快照预算时，快照保留概要并引导模型缩小查询条件重新查询；会话级查询结果缓存（同参重查复用）列为远期优化，不在本次范围。
- 不做历史语义压缩（调用 LLM 把旧轮压缩成摘要）与精确 tokenizer 级记账：本版本护栏用可配置字符折算估算 + 用量回测校准；语义压缩与按模型分词器精确统计列为远期优化。

## 风险

- 快照保留不全导致模型误判：大结果只保留部分条目。缓解：结构化分档保留（计数 + 前若干条）+ 快照内显式注明「共 N 条仅保留前 M 条」，注入指令要求信息不足/需要明细时缩小条件重新查询，不允许用不完整快照编造。
- 每轮回放 token 成本：快照在保留期内每轮追问都会重放。缓解：合计预算与条数上限可配置，超预算丢弃最旧；保留期默认跟随历史窗口，避免长会话上下文失控。
- 护栏估算误差：字符折算 token 与实际模型分词不一致，可能过早裁剪或漏裁。缓解：估算系数可配置、窗口与预留比例可配；裁剪只影响旧历史/快照/知识引用，不动当前消息与系统提示；验证阶段用真实 `prompt_tokens` 校准系数。
- 默认关闭护栏的风险：未声明窗口的智能体版本继续依赖 provider 侧报错。缓解：本版本同时提供超限错误友好兜底；建议发布版本时填写 `context_window_tokens`，或维护「模型名 → 已知窗口」小映射。
- 自动降级重试的成本与语义风险：降级会多一次模型调用（成本/延迟翻倍的上限为一次），且回复在无历史上下文下生成。缓解：降级后当前消息附注「此前内容未纳入」，模型会诚实说明或重新查询；开关可关闭，关闭后走友好报错。
- 数据保留面变化：快照文本落 `message_metadata` 后随消息持久化（保留期受消息表生命周期约束），比「仅当轮回填」多出持久化暴露。缓解：只存工具层已脱敏的模型可见文本并截断，与列注释「不保存敏感原文」一致；敏感字段剔除责任保持在工具层白名单。
- 模型误用过期快照：用户要求「最新订单」时模型可能仍用旧快照。缓解：注入文本显式携带查询时间与「需最新数据应重查」指令，验收标准覆盖该行为。
- 回归风险：改动集中在快照构造/落库/回放注入三个纯函数与两个收尾函数；以现有 pytest + ruff 作为回归基线，并在 `verify.md` 记录真实模型联调（两轮对话第二轮不重查）。
- 多模型兼容：注入为纯文本 SystemMessage，不依赖任何模型厂商的工具消息配对语义。

## 停点判断

- 是否涉及架构边界变化：否（不新增外部系统/服务边界，改动在对话运行时内部）。
- 是否涉及数据模型变化：是——`agent_versions` 新增可空列 `context_window_tokens`（需 alembic 迁移）；快照侧仍走 `conversation_messages.message_metadata` 现成 JSON 列，不新增列/消息角色 → 进入实现前需人工确认。
- 是否涉及 API 契约变化：否（REST/WS 协议与工具契约均不变；`message_metadata` 为内部约定）。
- 是否涉及鉴权或权限行为变化：否。
- 结论：进入实现前需人工确认。待确认项：① 采用「脱敏摘要快照」而非「原生重放」；② 快照随 assistant 消息 `message_metadata` 落库（不改表结构、不新增消息角色）；③ 回放注入形式（历史末尾追加 SystemMessage 文本）；④ 默认上限 `tool_snapshot_max_chars=8000`、`tool_snapshot_total_chars=20000`、`tool_snapshot_max_entries=20`，大结果按「计数 + 前若干条 + 未保留提示」分档保留而非纯截断；⑤ 快照保留期独立配置，默认跟随 3600s 历史窗口、可按天调大。⑥ 新增上下文预算护栏：窗口字段 `agent_versions.context_window_tokens`（新增可空列，跟随版本模型；可选模型名小映射兜底，DeepSeek 首批：v4 系列 1M、chat/reasoner 别名 128K），护栏 = 窗口 × 0.75（默认），未命中不启用护栏；超预算按「旧历史 → 快照 → 知识引用」裁剪；
⑦ 上下文超限后的行为：识别 OpenAI 兼容超限错误 → **自动降级重试一次**（仅系统提示 + 当前消息并附注「此前内容未纳入」，默认开启、可关）→ 仍失败返回友好文案。
⑧ 同参数快照回放去重：注入前按 `tool + params 摘要` 去重，同一查询条件只保留 `queried_at` 最新一份，防多版本歧义并省 token；⑨ 注入指令防误导强化：基于快照回答自然带出数据时间；变更动作（付款/改单/发货等）执行前提必须先重新查询，快照仅用于描述性回答；⑩ 护栏估算系数初始值宁保守勿乐观，组装/调用处新增 debug 埋点（估算 token/各裁剪层丢弃量/注入快照数/实际 `prompt_tokens`）用于验证阶段校准回写；⑪ 快照构造与写入收敛为 `runtime.py` 唯一公共 helper，REST/embed WebSocket 两收尾函数仅调用，验收覆盖双链路。

## 验收标准

- [ ] `order_query` 等成功工具查询后，最终 assistant 消息的 `message_metadata["tool_snapshots"]` 含快照条目（工具名/查询时间/参数摘要/结果快照），单条文本、合计与条数均不超配置预算；失败/等待确认的工具不产生快照。
- [ ] 大结果分档用例：构造 `total` 超预算的列表结果，快照含概要（`total`/分页等）与「共 N 条，仅保留前 M 条，其余未保留」提示，且快照文本不超预算。
- [ ] 第二轮 `load_recent_history` + `build_history_messages` 产物在历史末尾包含快照 SystemMessage（含时效指令与逐条快照文本），且不包含伪造的 `tool_calls`/`ToolMessage` 配对；无快照时产物与现状一致。
- [ ] 配置项 `tool_snapshot_max_chars`/`tool_snapshot_total_chars`/`tool_snapshot_max_entries`/`tool_snapshot_retention_seconds` 生效；默认保留期跟随历史窗口，普通消息与快照各自按窗口过滤（窗口边界有单测覆盖）。
- [ ] 护栏用例：版本声明 `context_window_tokens`（或命中模型名映射）后，组装预算超限时按「旧历史 → 快照」顺序裁剪且系统提示/当前消息不被裁剪；知识引用在检索层由 `knowledge_context_max_chars` 限量；被裁快照在注入文本中有「因上下文限制未保留」提示；系统提示+当前消息仍超预算时记录告警并交由超限兜底；未命中窗口来源时行为与现状一致。
- [ ] 超限兜底用例：模拟 DeepSeek/OpenAI 兼容超限错误文本，开启降级时仅保留系统提示 + 当前消息（含「此前内容未纳入」附注）并重试一次；关闭降级或降级仍失败时返回友好文案而非裸抛内部错误（错误识别映射与开关均有单测覆盖）。
- [ ] 去重用例：同一查询条件（`tool+params` 相同）的多份快照跨消息/同消息并存时，回放注入只保留最新一份；不同查询条件的快照正常共存。
- [ ] 注入指令用例：注入文本包含「带出数据时间」「变更动作执行前需重新查询」语义（单测断言关键短语存在）。
- [ ] 护栏埋点用例：组装/模型调用路径存在 debug 级预算日志（估算 token、各裁剪层丢弃量、注入快照数、实际 `prompt_tokens`），`verify.md` 用 DeepSeek 实录对照记录校准结果。
- [ ] 单测通过：快照构造、截断上限、历史注入组装、无快照零注入、窗口外不注入；REST 与 embed WebSocket 链路均有覆盖（`poetry run pytest tests/ -k "snapshot or tool_snapshot" -q` 等，具体命令以仓库现有测试入口为准）。
- [ ] 相关既有测试无回归（`tests/conversation`、`tests/gateway` 等），ruff 无新增错误。
- [ ] 人工联调（记录在 `verify.md`）：真实/实录模型两轮对话——第一轮问订单并查询成功，第二轮同范围追问不触发 `order_query` 而能基于快照回答；用户要求最新数据或变更日期区间时触发重新查询。
- [ ] 文档闭环：`meta.json` 阶段与状态一致，`tools/harness/audit.py` 无新增 ERROR。

## 变更记录

### 2026-09-03 第 8 次变更（bugfix：快照未接收平台工具真实成功态 completed）

- 变更原因：用户反馈「并没有把工具里的数据发送给模型」。核查发现平台工具成功态状态词并非 `succeeded`：`ToolInvocationOutcome`/`BuiltinToolOutcome` 的成功态均为 `completed`（`mcp/services.py`、`builtin_tool/services.py`、`skill_runner/services.py`、`gateway/dispatcher.py` 宿主工具均如此），原快照过滤器只认 `succeeded`，导致真实工具结果全部被丢弃、第二轮无快照可注入。
- 变更内容：快照过滤器改为接收 `completed` 与 `succeeded` 双状态词（`_is_successful_outcome`），并跳过拒绝/过期/失败与带 `error` 载荷的结果；新增回归测试（宿主工具 `completed` 成功态落快照、completed+error/rejected 载荷不落）。
- 影响章节：范围（快照生成）、验收标准、verify
- 是否触发人工确认：否（bugfix，修复后行为与 spec 目标一致）

### 2026-09-03 第 7 次变更（实现对齐：知识引用裁剪边界）

- 变更原因：实现护栏时确认知识引用文本内嵌于系统提示（`build_system_prompt` 拼段），运行时无法安全切分其与宿主工具说明的边界；其字符预算本就在检索层由 `knowledge_context_max_chars`（默认 24000）限制。
- 变更内容：裁剪顺序明确为「最旧历史 → 工具快照 →（知识引用已在检索层限量，不单独进入运行时裁剪）→ 系统提示与当前消息不可裁」；系统提示+当前消息仍超预算时记录告警并交由超限兜底降级重试。验收标准同步措辞。
- 影响章节：范围（护栏裁剪顺序）、验收标准
- 是否触发人工确认：否（纯实现对齐说明，不改变护栏整体行为与已批准边界）

### 2026-09-03 第 6 次变更（评审补强四项：去重/防误导/估算校准埋点/双链路唯一 helper）

- 变更原因：用户询问「还有什么需要优化」，评审后提出四项补强，用户回复「可以」采纳
- 变更内容：
  - 同参数去重：回放注入前按 `tool + params 摘要` 去重，同一查询条件多份快照只保留最新一份，防「同条件多版本结果并存」误导模型并省 token；不同查询条件快照正常共存（范围第 3 节）；
  - 注入指令防误导强化：基于快照回答自然带出数据时间；变更动作（付款/改单/发货等）执行前提必须先重新查询，快照仅用于描述性回答（范围第 3 节）；
  - 护栏估算与校准埋点：系数初始值宁保守勿乐观；组装/调用处新增 debug 级预算日志（估算 token、各裁剪层丢弃量、注入快照数、实际 `prompt_tokens`），验证阶段用 DeepSeek 实录对照后回写校准系数（范围第 5 节）；
  - 双链路一致性：快照构造与写入收敛为 `runtime.py` 唯一公共 helper，REST/embed WebSocket 两个 `_finish_*` 收尾函数仅做调用方（范围第 2 节）。
- 影响章节：范围（第 2/3/5 节）、待确认项（新增 ⑧–⑪）、验收标准、meta
- 是否触发人工确认：是（四项补强随整体设计待用户最终确认后进入实现）

### 2026-09-03 第 5 次变更（达到上限怎么办 + DeepSeek 窗口事实）

- 变更原因：用户追问「如果达到了最大上下文限制应该怎么办」，并说明常用模型是 DeepSeek
- 变更内容：
  - 按官方公告核对 DeepSeek 事实（2026-09-03）：V4 预览（deepseek-v4-pro/flash/vision-exp）上下文 1M、最大输出 384K；旧别名 deepseek-chat/deepseek-reasoner（V3.1/V3.2 时代）为 128K，官方已于 2026-07-24 15:59 UTC 退役，仅镜像/代理兼容；
  - 「达到上限怎么办」落地为三层动作链：组装前护栏裁剪（旧历史 → 快照 → 知识引用）→ 裁剪后仍命中则识别 OpenAI 兼容超限错误并**自动降级重试一次**（仅系统提示 + 当前消息，附注「此前内容未纳入」，可配置开关）→ 仍失败返回友好文案（缩小查询范围/新开对话）；
  - 模型名映射首批条目按 DeepSeek 现状写入；运维提醒：仓库若仍配置 deepseek-chat/reasoner 别名且直连官方 API 需迁移到 V4 名称。
- 影响章节：范围（第 5 节）、风险、停点判断、验收标准
- 是否触发人工确认：是（自动降级重试策略与 DeepSeek 窗口事实待用户确认）

### 2026-09-03 第 4 次变更（窗口字段落点：智能体版本）

- 变更原因：用户建议「最大上下文限制加在智能体版本里、跟着配置的模型走」，询问是否合适
- 变更内容：
  - 核实调用链：对话运行时主模型来自 `AgentVersion`（`agent/services.py:build_chat_model(version)`：`model_name/base_url/api_key/temperature/model_options` 全在版本上）；`model_registry`（`PlatformModel`/`AgentModelBinding`）是 embedding 等辅助角色绑定，主对话不走该链路；
  - 采纳用户建议：窗口字段定为 `agent_versions.context_window_tokens`（新增可空 Integer 列，需 alembic 迁移），与模型同层配置、运行时同源读取，不引入 model_registry 双源；
  - 不使用 `model_options` JSON 承载：该字段会被 `**model_options` 展开传给 ChatOpenAI，混入护栏字段易出错；
  - 决策优先级：版本显式设置 > 可选内置「模型名 → 已知窗口」小映射 > 未命中不启用护栏（仅保留超限错误兜底）。
- 影响章节：范围（第 5 节模型窗口来源）、风险、停点判断（数据模型变化：是）、验收标准、meta
- 是否触发人工确认：是（agent_versions 加列属数据模型变化，仍待用户确认）

### 2026-09-03 第 3 次变更（上下文上限与超限处理）

- 变更原因：用户追问「每次最大上下文限制是多大、有没有上限、超过怎么办」
- 变更内容：
  - 核实并记录现状：仓库不存模型上下文窗口、组装消息前无总预算校验；provider 超限错误仅被统一 re-raise 为“模型生成失败”，无裁剪与友好兜底；
  - 新增「上下文预算护栏」：模型窗口随智能体版本声明（`agent_versions.context_window_tokens`，新增可空列），护栏 = 窗口 × 0.75（可配）；未声明窗口默认不启用护栏（行为不变），可选模型名小映射兜底；
  - 超预算裁剪顺序：旧历史 → 工具快照（丢旧留新）→ 知识引用，系统提示与当前消息不可裁；快照被裁时注入文本注明「因上下文限制未保留」；
  - 仍超限时识别 `context_length_exceeded` 类错误并返回友好文案，不再裸抛内部错误；
  - 估算用字符折算 token（默认 1.2 字符/token，可配），验证阶段用 `prompt_tokens` 用量校准；
  - 非目标补充：历史语义压缩与精确 tokenizer 记账列为远期。
- 影响章节：范围（新增第 5 节）、非目标、风险、停点判断、验收标准
- 是否触发人工确认：是（护栏启用策略与窗口约定仍待用户确认）

### 2026-09-03 第 2 次变更（保留期与大结果预算修订）

- 变更原因：用户对初始方案提出两点疑问——①「3600s 就失效了吗」②「只上线 2000 字符？查询很大的数据怎么办」
- 变更内容：
  - 澄清 3600s 为**现有整体历史回放窗口**（对所有消息生效，非快照专属 TTL）；新增独立配置 `tool_snapshot_retention_seconds`，默认跟随历史窗口，可按天调大，普通消息与快照各自按窗口过滤；
  - 默认预算上调：`tool_snapshot_max_chars=8000`、`tool_snapshot_total_chars=20000`（与宿主工具同轮回填上限对齐）、`tool_snapshot_max_entries=20`；
  - 大结果改为**结构化分档保留**：列表结果保留概要（`total` 等）+ 预算内条目 + 「共 N 条仅保留前 M 条」提示，非列表按长度预算截断并同样提示；不做无脑长度截断，模型不得用不完整快照编造；
  - 非目标补充：不做超大结果全量持久化与上下文外检索，会话级查询结果缓存列为远期优化。
- 影响章节：范围（快照生成/配置）、非目标、风险、停点判断、验收标准
- 是否触发人工确认：是（方案参数与大数据策略修订，仍待用户确认后进入实现）

### 初始版本

- 时间：2026-09-03
- 变更原因：用户确认按仓库流程落地「后端智能体工具查询结果跨轮记忆」（原始问题：使用 tools 查询出的数据每次追问是否都要重新查询）。
- 变更内容：完成业界调研（OpenAI Agents SDK Session / running-agents、LangGraph persistence、Dify、tool 消息配对硬约束）与仓库现状核对；确定采用「脱敏摘要快照」方案：快照随最终 assistant 消息 `message_metadata` 落库，`build_history_messages` 在下一轮回放时以 SystemMessage 文本注入；表结构零迁移，前端零改动。
- 影响章节：目标、范围、非目标、风险、停点判断、验收标准（全部）。
- 是否触发人工确认：是（数据契约变化：`conversation_messages.message_metadata` 新增「工具结果快照」承载约定；方案选型需用户确认后进入实现）。
