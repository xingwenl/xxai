---
id: 2026-10-16-run-event-model-unification
tier: A
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-16
  grantedBy: 用户
  grantedNote: 用户确认「两个都开工」，本 spec 与 ADR 0007 定稿后进入实现。
  why: ["API 契约变化：SSE 事件字段与 payload 键名变化", "架构边界变化：事件模型横跨 conversation、gateway、agent_runtime 与 apps/ai-sdk"]
---

## 目标与范围

- 把「一次 Agent 运行的出站事件」收敛成唯一模型 `RunEvent`（形状取 `apps/ai-sdk/src/core/protocol.ts:56-65` 的 `ProtocolEvent`），事件构造与映射只写一份；WebSocket 与 SSE 各自只做传输编码。
- 已有基础（不是从零开始）：**内部事件源已经统一** —— `apps/backend/app/modules/agent_runtime/contracts.py:116-124` 的 `AgentEvent` 由 `agent_runtime/runtime.py:167-266` 的 `emit` 经 `hooks.py:32 on_event` 发出，SSE 与 WS 两侧都经 `agent_runtime/conversation_adapter.py:15` 与 `event_adapters.py:37 event_to_legacy` 消费。**分叉只在出站组装**：SSE 内联在 `conversation/services.py:824-1011` 与 `conversation/router.py:161-259`，WS 集中在 `gateway/events.py`。
- 不对称清单（现状，逐条可核对）：SSE 独有 `tool_call`（payload `{tool,toolCallId}`）与 `tool_result`（payload `outcome.model_dump()` 全蛇形）；WS 独有 `host_tool_call`/`question_required`/`session_ready`/`pong` 与 `message_completed.usage`；同名事件字段不一致——`message_completed` 蛇形 `knowledge_grounded` 对驼峰 `knowledgeGrounded`，`confirmation_required` 两侧字段集几乎不相交；信封 SSE 无 `id/protocolVersion/timestamp/requestId`、`sequence` 从 0 起（WS 从 1 起），异常分支还硬编码 `"sequence": 1`（`conversation/router.py:250-259`）。
- 无消费者的证据（决定能否直接对齐形状）：SSE 的 `confirmation_required` 发的是 `outcome.model_dump()`（含 `resume_token`/`call_id`/`audit_id`），但 `conversation/router.py` 只有 `/{agent_id}/chat` 一个路由，**没有 REST 确认端点**，`resume_token` 全仓库只出现在 `agent_runtime/contracts.py:80`/`:94`、`agent_runtime/adapters.py:35`/`:45` 与 `tests/agent_runtime/test_tools.py:61`/`:75` ⇒ 这些蛇形字段当前没有任何消费者。
- 给谁用：后台控制台与第三方嵌入方（WS + `xxai-agent`），以及没有 SDK 的服务端调用方（REST SSE）。
- 不做：不改 SSE 鉴权（`conversation/router.py:121`）；不给 SSE 加断线续传或 Redis 回放；不给 SSE 新增确认回路（REST 确认端点）；不动配额、工具执行与无人值守审批；不引入第三方线协议；不改控制台 UI 行为（工具事件是否上屏见「变更点」）。
- 分档说明：命中「跨服务边界重构」——同一契约同时约束 REST 传输、网关传输与 SDK（第三方契约方），按 A 档补 ADR 与拷问。

## 来源与方案比较

- 官方/成熟案例一：AG-UI 1.0，https://docs.ag-ui.com/concepts/events ，调研日期 2026-10-16（HTTP 200）。要点：**单一事件流**、事件分族（lifecycle / text message / tool call / state / activity / special）、协议**传输无关**（默认 SSE），另有 `/migrating-to-1-0` 迁移说明。
- 成熟案例二（本机源码）：Pi `/Users/lixingwen/xw/git/pi`，调研日期 2026-10-16。要点：**单一事件模型 + 多订阅端只做投影**——`packages/agent/src/types.ts:429-444` 判别联合 `AgentEvent`，`agent-loop.ts:26` `AgentEventSink`、`:38/:70` 返回 `EventStream<AgentEvent, AgentMessage[]>`，`agent.ts:175/:250` 订阅集合；消费端各自投影（`coding-agent/src/core/agent-session.ts:144`/`:402`/`:643`、`modes/rpc/rpc-mode.ts:355`、`server/src/sessions.ts:233`）而不重写 payload；**Pi 没有 SSE**，服务端走 `packages/protocol` 的 framing/codec，且版本只在协议层（`protocol/src/schemas.ts:3` `PROTOCOL_VERSION = 1`、`codec.ts:170-171` `isSupportedProtocolVersion`）。
- 本仓库既有事实标准：`apps/ai-sdk/src/core/protocol.ts:56-65` 的 `ProtocolEvent{id,type,protocolVersion,sequence,timestamp,payload,conversationId?,requestId?}` 与 `:4-22` 的 17 类事件，产出点是 `apps/backend/app/modules/gateway/router.py:910-932` 的 `envelope()`。
- 方案 A（选）：以 `ProtocolEvent` 为唯一出站模型，构造器下沉到 `apps/backend/app/modules/agent_runtime/events.py`，SSE 与 WS 共用构造器与 `to_wire()`；SSE 补 `usage`/`protocolVersion`/`id`/`timestamp`/`requestId`，payload 统一 camelCase；传输特有事件（`session_ready`/`pong`）留在传输层。
- 方案 B：保留两套构造，只写一张字段映射表把 SSE 输出改成 camelCase。
- 方案 C：让 SSE 复用网关会话层（embed token 握手 + Redis 回放）。
- 选择理由：A 用「一个模型 + 两个薄编码器」换掉「两套映射各自漂移」，且不需要升协议版本；AG-UI 与 Pi 分别从协议侧和实现侧支持「单一事件流 + 多消费端投影」，且 Pi 证明版本号该留在协议层而不是内部事件上。

## 被否决的选项

- **只加一张字段映射表（方案 B）**：两处映射仍在，第三个消费端还要再抄一遍；SSE 漏 `usage` 是「漏字段」而非「名字不同」，映射表治不了。
- **删掉 SSE 流式分支、统一走 WS**：控制台实时对话已走 WS（`apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx:27`），但 SSE 是无 SDK 的服务端/脚本唯一的流式 REST 入口（仓库内唯一调用者是 `apps/backend/app/modules/wechat_bot/chat_client.py:39`，且用 `stream:false`），删掉等于砍对外契约。
- **把 SSE 并入网关会话层（方案 C）**：SSE 没有 embed token 与子协议握手、没有 Redis 回放（`gateway/replay.py`，TTL 900s），并入后要么伪造会话要么处处分支，还会让 conversation 反向依赖 gateway。
- **直接把内部 `AgentEvent` 当线格式**：`agent_runtime/contracts.py:12-22` 的事件是内部语义（`message_delta`/`thinking_delta`/`tool_started`/`tool_completed`…），缺 `id/protocolVersion/sequence/timestamp`，且 `conversation_adapter.py:25-65` 会把一个 `tool_started` 展开成多条；把它当协议会把内部重构暴露成契约破坏。Pi 也是内部 `AgentEvent` 与协议层 `ServerEvent` 两层。
- **一次性升 `protocolVersion` 到 2**：`apps/ai-sdk/src/core/protocol.ts:71-124` 只接受 v1，`apps/backend/app/modules/gateway/auth.py:29-35` 会直接拒掉旧客户端；本次是补字段而非改语义，不需要新版本。
- **采用 AG-UI 1.0 作为线格式**：宿主工具回传、确认/提问等待、配额不在 AG-UI 语义内，且要重写 SDK 与前端。
- **只定义抽象接口、两处各自实现**：接口不阻止漏字段，只有共享 golden 文件（验收标准 2）能。
- **顺手让 WS 也发 `tool_call`/`tool_result`**：会激活 SDK 里的现有死分支（`apps/ai-sdk/src/core/client.ts:337-341`）并改变控制台浮窗行为（从此会显示工具卡片），把验收面从「字段一致」扩到「UI 显示」，本轮目标被稀释。
- **在 `session_ready.capabilities` 里声明传输能力子集**：多出一处必须与后端 `apps/backend/app/modules/gateway/auth.py:10` 和 SDK `apps/ai-sdk/src/core/websocket.ts:186` 同时维护的字段，而本轮没有任何客户端会用它做分支决策；差异改为写进 `docs/adr/0007-run-event-model-unification.md` 的 Consequences。

## 停点判断

- 是否涉及架构边界变化：是（出站事件模型横跨 `modules/conversation`、`modules/gateway`、`modules/agent_runtime` 与 `apps/ai-sdk`）
- 是否涉及数据模型变化：否（不动表结构、不新增迁移）
- 是否涉及 API 契约变化：是（SSE 事件字段、payload 键名与 `tool_call`/`tool_result` 形状变化，`protocolVersion` 仍为 1）
- 是否涉及鉴权或权限行为变化：否
- 命中任一项即 `approval.required: true`，进入实现前必须获得人工确认。

## 变更点

- 新增 `apps/backend/app/modules/agent_runtime/events.py`：`PROTOCOL_VERSION`、`RunEventType`、`RunEvent`、事件构造器（自 `gateway/events.py` 下沉）、`to_wire()`、`format_sse_event()`/`to_sse_block()`、`LoopEventBuilder`、`build_step_payload()`（自 `conversation/runtime.py` 下沉并在原处 re-export），以及把服务层 item 映射为线协议事件的 `run_events_from_stream_item()`。
- `apps/backend/app/modules/gateway/events.py`：**整个文件删除**，内容全部迁入上一行；`INBOUND_PAYLOAD_HANDLERS` 与 `event_to_protocol_payload` 废弃（入站三处改由 `dispatcher.py` 直接产出 `RunEvent`）。
- `apps/backend/app/modules/gateway/router.py:910-932`：`envelope()` 改调 `to_wire()`（签名不变，仍作为回调传给 `_handle_message_send`）；出站队列类型改为 `asyncio.Queue[RunEvent | None]`。
- `apps/backend/app/modules/gateway/dispatcher.py`：`host_tool_call`/`confirmation_required`/`question_required` 三处内联 dict 改为调用构造器（参数原值传入，密钥脱敏统一在构造器内做一次）。
- `apps/backend/app/modules/gateway/runtime.py`：导入与调用点改到新模块（`build_message_started` → `message_started`）。
- `apps/backend/app/modules/conversation/services.py`：不改 yield 站点（服务层 item 仍是内部 seam），只在 tool_call / tool_result / confirmation_required 的 item 上补 `input`/`tool`/`tool_type`/`arguments` 顶层键，供统一映射读取。
- `apps/backend/app/modules/conversation/router.py:152-264`：删掉局部 `emit()` 与全部 `item["type"]` 字面量分支，改为一处 `run_events_from_stream_item()` + `to_sse_block()`；每个 SSE 请求生成稳定 `request_id`，异常分支走同一编码器（不再硬编码 `sequence: 1`）。
- `apps/backend/app/modules/conversation/runtime.py`：`build_step_payload` / `format_sse_event` 改为从新模块 re-export，避免 `agent_runtime` 反向依赖 `conversation`。
- `apps/ai-sdk/src/core/protocol.ts:2` 与 `:31-54`：`SDK_VERSION` 取自 `package.json`；`tool_call`/`tool_result` 的 payload 类型改为与实际读取一致（`client.ts:337-341` 读 `name`/`input`/`result`）。
- 测试：新增 `apps/backend/tests/gateway/test_event_parity.py`；共享 golden `apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json`；`apps/ai-sdk/src/core/__tests__/protocol.test.ts` 增 golden 解析用例；`tests/gateway/{test_chat_flow,test_question_flow,test_host_tool_timeout}.py` 与 `apps/ai-sdk/src/core/__tests__/compatibility.test.ts` 改为断言新类型。
- 验证方式：backend pytest + ai-sdk vitest + `pnpm --dir apps/front build` + 真进程 curl SSE，见验收标准。

## 验收标准

1. 新增 parity 测试：把同一份 `AgentEvent` 流分别喂给 SSE 与 WS 编码器，产出的 `type` 序列一致，且 `message_completed.payload` 逐字段相同（含 camelCase 的 `usage`）。
2. 共享 golden 文件：Python 侧断言两个编码器逐条等于它；TS 侧 `parseProtocolEvent` 对每条返回非 `unknown` 且 `protocolVersion === PROTOCOL_VERSION`。
3. `tool_call`/`tool_result` 的 payload 形状与 SDK 读取一致（`client.ts:337-341` 的 `name`/`input`/`result`），由 golden 断言固定。
4. `apps/backend/.venv/bin/python -m pytest tests/conversation tests/gateway tests/agent_runtime -q` 全绿（改动前基线：`tests/conversation` + `tests/gateway` 为 228 passed / 1 skipped）。
5. `npx vitest run src`（在 `apps/ai-sdk` 内）与 `pnpm --dir apps/front build` 通过。（`pnpm --dir apps/ai-sdk test` 会连带跑 `scripts/verify-package.test.mjs`，该用例在改动前就因 `dist/src/**` 与 `dist/core/**` 的产物布局漂移而失败，见 verify.md 未执行项。）
6. 真进程：经 `:8080` 发 `stream:true` 的 `POST /api/v1/agents/1/chat`，SSE 每条 `data:` 含 `protocolVersion`，且 `message_completed` 带 `usage`。
7. 出站形状只在 `apps/backend/app/modules/agent_runtime/events.py` 组装（以 grep 为准）：`apps/backend/app/modules/gateway/events.py` 不存在；`protocolVersion` 字面量只在该文件；`event_to_protocol_payload` / `INBOUND_PAYLOAD_HANDLERS` 无源码命中；`conversation/router.py` 内不再出现事件类型字面量分支。
