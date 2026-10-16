# 统一运行事件模型：一个 `RunEvent` 与两个传输编码器

## Status

accepted

关联 Harness request：`2026-10-16-run-event-model-unification`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-16-run-event-model-unification/`）。术语（运行事件、事件信封、传输能力子集）见 `CONTEXT.md`。

## Decision

**出站事件只保留一个模型 `RunEvent`，形状取 SDK 已对外承诺的线协议。** 取 `apps/ai-sdk/src/core/protocol.ts:56-65` 的 `ProtocolEvent{id,type,protocolVersion,sequence,timestamp,payload,conversationId?,requestId?}` 与 `:4-22` 的 17 类事件，payload 一律 camelCase。理由是它是唯一有第三方契约方的形状——宿主页面嵌 `xxai-agent`、由 `:71-124 parseProtocolEvent` 校验 `protocolVersion` 与必需字段；后端 `gateway/router.py:910-932` 的 `envelope()` 已经在产出它。现状是两条通道共用同一事件源（`agent_runtime/hooks.py:32 on_event`、`contracts.py:116-124 AgentEvent`）却各自组装出站事件，于是 SSE 缺 `usage`（`conversation/services.py:2249` 一线的 `message_completed` 只有 `knowledge_grounded`）、WS 是 `knowledgeGrounded`、`confirmation_required` 两侧字段集几乎不相交、`sequence` SSE 从 0 / WS 从 1，异常分支还硬编码 `"sequence": 1`（`conversation/router.py:250-259`）。

**构造器下沉到 `agent_runtime/events.py`，SSE 与 WS 只做编码。** 出站组装现在分叉在 `conversation/services.py:824-1011` + `conversation/router.py:161-259`（SSE）与 `gateway/events.py`（WS，341 行）。放 `agent_runtime` 是因为两条通道都从那里取事件源，且 `conversation` 不得反向依赖 `gateway`（grep 证明现在二者互不 import）。两个编码器只负责「把 `RunEvent` 变成线上字节」：SSE 写 `id:`/`data:` 行，WS 走既有发送循环。

**SSE 保留存在，并补齐信封与 `usage`；但不改鉴权、不加回放、不加确认回路。** 它是无 SDK 方唯一的流式 REST 出口（仓库内唯一调用者是 `apps/backend/app/modules/wechat_bot/chat_client.py:39`，且用 `stream:false`），删掉等于砍对外契约（方案 B 被否决）。同时明确不做的三件事：不给 SSE 加 Redis 回放（`gateway/replay.py` 的 900s 能力属于网关会话）、不给 SSE 加 REST 确认端点（`resume_token` 目前全仓库只出现在 `agent_runtime/contracts.py:80/:94`、`adapters.py:35/:45` 与测试里，没有消费者）、不把 SSE 收编进网关会话层。

**`tool_call`/`tool_result` 的形状统一为 `{name,input,callId?}` 与 `{name,result,status}`，但 WS 本轮不新增这两类事件。** SDK 声明的是 `{name,status}`，实现读的却是 `name`/`input`/`result`（`client.ts:337-341`），而 WS 链路上这两支从未被触发（死分支）；形状必须唯一，但「让 WS 也开始发工具事件」是新增行为（控制台浮窗会多出工具卡片），与本轮「把两套映射收敛成一套」的目标无关，单独评估。

**传输特有事件留在传输层，且不把传输能力子集写进 `session_ready.capabilities`。** `session_ready`/`pong` 是连接生命周期，`host_tool_call`/`question_required` 依赖宿主回传与用户在场，SSE 没有对应机制；能力子集一旦进 capabilities，就要在后端与 SDK 两处同步维护（现状 `gateway/auth.py:10` 与 `websocket.ts:186` 已经不对齐），本轮只把差异写进本 ADR 的 Consequences。

**`protocolVersion` 保持 1，不提供兼容期；`SDK_VERSION` 改为从 `package.json` 读。** v1 的形状变化只影响内部使用方（控制台浮窗、会话历史 Vue 岛、微信助手用非流式），升版本只会让 `gateway/auth.py:29-35` 与 `parseProtocolEvent` 把旧客户端一并拒掉；而 `protocol.ts:2` 硬编码的 `SDK_VERSION='0.1.0'` 与 `package.json` 的 `0.2.0` 漂移，已经让握手期上报的版本不可信。

## Considered Options

- **只加一张字段映射表把 SSE 输出改成 camelCase**：两处映射仍在，第三个消费端还要再抄一遍；SSE 漏 `usage` 是「漏字段」而非「名字不同」，映射表治不了。
- **删掉 SSE 流式分支、统一走 WS**：控制台实时对话已走 WS，但 SSE 是无 SDK 的服务端/脚本唯一的流式 REST 入口，删掉等于砍对外契约。
- **把 SSE 并入网关会话层（embed token 握手 + Redis 回放）**：SSE 没有子协议握手与回放能力，并入后要么伪造会话要么处处分支，还会让 `conversation` 反向依赖 `gateway`。
- **直接把内部 `AgentEvent` 当线格式**：`agent_runtime/contracts.py:12-22` 是内部语义（`message_delta`/`thinking_delta`/`tool_started`/`tool_completed`…），缺 `id`/`protocolVersion`/`sequence`/`timestamp`，且 `conversation_adapter.py:25-65` 会把一个 `tool_started` 展开成多条；把它当协议会把内部重构暴露成契约破坏。Pi 同样是内部 `AgentEvent` 与协议层 `ServerEvent` 两层。
- **一次性升 `protocolVersion` 到 2**：`parseProtocolEvent` 只接受 v1、`check_client_compatibility` 会拒掉旧客户端；本次是补字段而非改语义。
- **采用 AG-UI 1.0 作为线格式**：宿主工具回传、确认/提问等待、四维配额都不在 AG-UI 语义内，且要重写 SDK 与前端。
- **只定义抽象接口、两处各自实现**：接口不阻止漏字段，只有共享 golden 文件能。
- **顺手让 WS 也发 `tool_call`/`tool_result`**：激活 SDK 现有死分支的同时也改变了控制台浮窗行为，验收面从「字段一致」扩到「UI 显示工具卡片」，与本轮目标不符。
- **在 `session_ready.capabilities` 里声明传输能力子集**：多一处必须与后端、SDK 同时维护的字段，而它描述的差异本轮并不会被任何客户端用来做分支决策。
- **给 SSE 补 REST 确认端点，让 `resume_token` 有消费者**：这是一条新的对外能力（含鉴权、幂等、审计与配额），不是「统一事件模型」的一部分。

## Consequences

- **SSE 出站形状变化是破坏性的**：`message_completed.knowledge_grounded` → `knowledgeGrounded`，`confirmation_required` 的蛇形字段集消失。仓库内没有消费端，所以不留兼容期；但 `docs/handoff/task-6-langgraph-chat-sse.md:83` 与 `:110-124` 的旧字段描述必须同步更新，否则文档会与实现相反。
- **SSE 与 WS 的事件集仍不对称**：SSE 发 `tool_call`/`tool_result`，WS 独有 `session_ready`/`pong`/`host_tool_call`/`question_required`。这一条读起来像「还没统一」，但它是事实：两个传输能承载的事件本来就不同，共同的只是「同一模型、同一字段命名、同一信封」。
- **SSE 上需要确认的工具仍然无法被批准**：客户端只会收到 `confirmation_required`，而没有任何 REST 途径回复。本轮不修，写在这里避免被当成新引入的问题。
- **`SDK_VERSION` 从 `package.json` 读之后，发版必须同步 package.json**，否则漂移换了个方向；SDK 侧需要一条断言把「上报版本 == package.json 版本」固定住。
- **golden 文件是跨语言的规范文件**：`apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json` 同时被 Python 与 TS 测试读取。改事件形状必须同时改两侧，这是本轮唯一的双实现点，且是有意的（共享数据而不是共享代码）。
- **`events.py` 成为事件形状的唯一真相来源**：`conversation/router.py` 与 `gateway/events.py` 内不得再出现事件类型字面量；以防回归，验收标准里有一条以 grep 判定的检查。
