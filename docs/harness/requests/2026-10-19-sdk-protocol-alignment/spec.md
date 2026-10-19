---
id: 2026-10-19-sdk-protocol-alignment
tier: B
risk: medium
approval:
  required: true
  granted: true
  grantedAt: 2026-10-19
  grantedBy: 用户
  grantedNote: "停点确认：按 ④ 范围实现；capabilities 取「删除双向声明」；/api/agent-token 无鉴权与 demo secret 泄漏另立 request 排在 ④ 之后。"
  why: ["API 契约变化：REST 错误响应新增 error_code 字符串字段；WS 版本不兼容路径从「裸关闭」变为「先发结构化 error 事件再关闭」；session_ready 不再返回 capabilities", "鉴权或权限行为变化：auth 帧缺失 protocolVersion/sdkVersion 由默认放行改为拒绝", "协议契约收敛：删除 gateway/schemas.py 运行时未使用的出站协议模型，test_protocol.py 与 test_question_flow.py 的引用需重写"]
---

# SDK 协议 / 错误码 / 版本协商对齐

## 目标与范围

目标：让「协议不兼容」「REST 业务错误」「SDK 错误回调」三条出口都能被调用方**程序化判断**；把散落的字符串错误码收成单一登记表；让契约文档、共享 golden 与运行时形状一致。

范围外：不提升协议主版本（主版本 2 不在本轮）；不改 `ApiResponse.code` 的 int 语义；不改 WS/SSE 事件形状（仅补 session_ready 夹具字段与错误码引用）；不做 ③b 的 SSE/REST 待确认恢复；不动提示器（thinking）与工具事件载荷。

受影响面：`apps/backend/app/modules/gateway/**`、`apps/backend/app/modules/agent_runtime/{events,errors}.py`、`apps/backend/app/modules/conversation/runtime.py`、`apps/backend/app/shared/{exceptions,responses}.py`、`apps/ai-sdk/src/core/**`、`docs/design/agent-sdk-phase-2c-compatibility-matrix.md`。

## 来源与方案比较

本机 Pi（`/Users/lixingwen/xw/git/pi`，HEAD `4e69b0c`，调研日期 2026-10-19）第一手事实：

- 版本号是单一整数：`packages/protocol/src/schemas.ts:3` `PROTOCOL_VERSION = 1 as const`；校验为精确相等、无 min/max 区间（`packages/protocol/src/codec.ts:170-172 isSupportedProtocolVersion`）。
- **不兼容也要发结构化错误帧**：客户端首帧 `hello{version}`（`packages/protocol/src/schemas.ts:384-389`）；服务端不兼容时先回 `hello_error{code:"version", message:"Unsupported protocol version X; expected 1"}`（`packages/server/src/server.ts:221-228`），再由 `failProtocol` 作为最后一帧发出并关闭（`packages/server/src/server.ts:315-328`）。
- 错误码是单一联合类型：`packages/protocol/src/schemas.ts:269-284` `"version"|"busy"|"session_locked"|"not_found"|"invalid_request"|"not_implemented"|"internal_error"`；服务端唯一归一化点 `packages/server/src/server.ts:351-369 toProtocolError`；内部错误的 cause「retained for reporting but never serialized」（`packages/server/src/errors.ts:52-57`）。
- 协议层**没有** `retryable` 字段、**没有** code→retryable 映射；重试判断留在调用方（`packages/ai/src/utils/provider-retry.ts:23-38`：`x-should-retry` 头，或 status ∈ {408,409,429,≥500}）。
- 协议层**没有** capabilities 协商（`grep -rni capabilit packages/protocol/src packages/server/src packages/client/src` 零命中）。
- Pi 是严格模式：所有 schema `additionalProperties: false`，未知事件抛错并断连，且自述无兼容保证（`packages/protocol/README.md:69`）。

本仓现状（HEAD `9efe4cf` 第一手）：

- `apps/backend/app/modules/gateway/auth.py:28-35` 算出 `unsupported_protocol_version` / `unsupported_sdk_version`，但 `apps/backend/app/modules/gateway/router.py:958-965` 只读 `.allowed`，随后 `close(4406)` —— **这两个稳定码线上从不出现**（死字段）；缺字段时默认 `1` / `"0.1.0"` 即放行。
- SDK 反而有消费分支：`apps/ai-sdk/src/core/websocket.ts:241-255` 收到这两个码会 emit `compatibility_error`，但 `apps/ai-sdk/src/core/client.ts:149-177` 未订阅它 → 使用者只能看到笼统的 `agent_connection_failed`；`websocket.ts:314-334 handleClose` 也不识别 4406，会无意义退避重试 5 次。
- 字符串错误码散落在十余处字面量；`apps/backend/app/shared/exceptions.py:11-22` 的 `AppException` **没有** `error_code`，`:54-63` handler 把 HTTP 状态码填进 `code`（int）⇒ REST 通路丢失全部字符串码（全仓唯一设置 `error_code` 的 `ChatModelUnavailable` 只在流式/事件通道可见）。
- SDK 结构在传输层被保留、在易用回调层被丢弃：`client.ts:511` 把 `code` 折进展示文案，`:558` `onError?.(new Error(errorText))`，而 `:559` `emit('error', errorPayload)` 是裸对象 → 同一失败两种形状；7 处 REST 辅助函数抛 `new Error("…: ${status}")`。
- 契约存在三份且互相矛盾：运行时由 `apps/backend/app/modules/agent_runtime/events.py:70-91 to_wire` 的裸 dict 决定；`apps/backend/app/modules/gateway/schemas.py:73/82-92/116-130` 的 pydantic 模型运行时不引用；`docs/design/agent-sdk-phase-2c-compatibility-matrix.md:10` 仍写 SDK `0.1.0`（实际 `0.2.0`），而共享 golden 的 `session_ready` payload 只有 `{"protocolVersion": 1}`。

结论：可借鉴 Pi 的「不兼容也发结构化错误帧」与「错误码单一登记表 + 一个归一化点 + 内部 cause 绝不序列化」；不可照搬 Pi 的严格模式（本仓主版本 1 内承诺前向兼容，见 ADR 0007）。

## 被否决的选项

1. **提升协议主版本到 2 并新建子协议**：本轮全部变更为主版本 1 内的可选字段与新增事件，兼容矩阵「弃用窗口」已明确主版本 2 不在范围；成本远大于收益。
2. **照搬 Pi 的严格 schema（未知字段/事件即断连）**：与 ADR 0007「同一主版本允许新增可选 envelope 字段」相反，会打断在用的 SDK 0.2.0。
3. **把 REST `ApiResponse.code` 从 int 改成字符串业务码**：破坏 `apps/front` 消费与 `apps/backend/tests/workflows/test_routes.py:110`/`:210` 的既有断言；同一收益可由**新增** `errorCode` 字段零破坏获得。
4. **为 `retryable` 再建一套 code→退避策略表**：Pi 的经验是重试策略属调用方；平台只应给出 `retryable` 布尔与 `retryAfterSeconds`，不替调用方决定退避曲线。
5. **让子协议缺失路径也发 error 事件**：该分支（`router.py:914-917`）发生在 `websocket.accept()` **之前**，此时发不出 WS 帧；改成「先 accept 再发帧关闭」会改变所有非 SDK 客户端的握手语义，得不偿失。
6. **补全 `gateway/schemas.py` 的 pydantic 模型并让运行时改用它**：`events.py` 的裸 dict 编码是 ADR 0007 定下的唯一出站实现，再造第二套会加剧双源；应反向收敛。
7. **删掉 `CompatibilityResult.retryable`**：它恒为 False 且无人读，但与 SDK `ErrorPayload` 的字段一一对应关系有价值；保留字段、由调用方给值成本更低。
8. **本轮一并处理 `/api/agent-token` 无鉴权与 demo 页 `client_secret` 泄漏**：属独立安全面且命中「鉴权行为变化」；已按用户决定另立 request（排在 ④ 之后）。
9. **保留 `capabilities` 双向声明并补消费**：后端那份是传输能力、SDK 那份是交互能力，两个命名空间对不上（后端不发 `questions`，SDK 无法据此门控提问 UI）；要让它成立需先设计语义。用户已选「删除双向声明」，回到 ADR 0007:19 的既有决定。

## 停点判断

- 架构边界变化：否（不新建模块目录、不改服务边界；错误码登记表放既有模块内）。
- 数据模型变化：否（不碰 `**/models.py`、不新增迁移）。
- API 契约变化：**是**（REST 错误响应新增 `error_code`；WS 版本不兼容路径新增 error 事件；`session_ready` 不再返回 `capabilities`；删除 `gateway/schemas.py` 出站协议模型会重写 `tests/gateway/test_protocol.py` 与 `tests/gateway/test_question_flow.py:19`/`:270` 的引用）。
- 鉴权或权限行为变化：**是**（auth 帧缺 `protocolVersion`/`sdkVersion` 从默认放行改为拒绝）。
- 判定：`approval.required: true`，已获用户确认（2026-10-19）。

用户已定：capabilities 取「删除双向声明」；`/api/agent-token` 无鉴权与 demo 页 `client_secret` 泄漏**不并入本轮**，另立 request 排在 ④ 之后。

## 变更点

1. `gateway/auth.py`：`CompatibilityResult` 增 `details: dict[str, str]`（`serverVersion`、`minimumSdkVersion`、`supportedProtocolVersion`）；`check_client_compatibility` 对缺失/非法 `protocol_version`/`sdk_version` 返回不兼容而不是默认放行。
2. `gateway/router.py`：`:958-965` 在 `close(4406)` **之前**调用 `_send_protocol_error(code=compatibility.code, retryable=False, details=compatibility.details)`；`:914-917` 子协议分支保持裸 4406 并在 ADR 记明原因。
3. 新增 `agent_runtime/error_codes.py`：`ErrorCode(StrEnum)` 收拢现有字符串码（`embed_token`、`request_id_required`、`request_in_progress`、`invalid_conversation_id`、`invalid_attachments`、`text_required`、`invalid_thinking`、`invalid_host_tools`、`context_length_exceeded`、`agent_upstream_unavailable`、`agent_request_failed`、`agent_request_cancelled`、`host_tool_failed`、`tool_not_available`、`invalid_arguments`、`host_tool_execution_failed`、`host_tool_expired`、`host_tool_execution_timeout`、`request_failed`、`quota_exceeded`、`quota_unavailable`、`chat_model_unavailable`、`unsupported_protocol_version`、`unsupported_sdk_version`）；`gateway/router.py`、`gateway/dispatcher.py`、`conversation/runtime.py`、`agent_runtime/errors.py` 的裸字符串改为引用它（线上取值不变）。
4. `shared/exceptions.py` + `shared/responses.py`：`AppException` 增可选 `error_code: str | None`；`error_response` 透传；`ApiResponse` 增 `error_code: str | None = None`（REST 出参沿用既有 snake_case 约定，与 `data` 里的 `page_no`/`page_size` 一致；**不用** `errorCode`）。`code: int` 语义与现有断言不变。
5. `model_registry/resolver.py`：`ChatModelUnavailable` 只改基类接入，使 `chat_model_unavailable` 能在非流式 REST 出现（409 + `error_code`）。
6. 新增 `apps/ai-sdk/src/core/errors.ts`：`interface AgentError extends Error { code?: string; retryable?: boolean; requestId?: string; details?: Record<string, unknown> }`（**接口而非子类**：跨包边界 `instanceof` 不可靠，用 `name === 'AgentError'` 标记）+ `isAgentError(value)` + `agentError(input, fallbackMessage?)`（已归一化则原样返回；`Error` 实例就地改 `name` 并返回同一对象）+ `agentErrorFromResponse(response, fallbackMessage)`（读 `error_code`，兼容旧响应的字符串 `code`，缺失时回落 `http_<status>`；`retryable` 按 5xx/429 推断）。
7. `apps/ai-sdk/src/core/client.ts`：`onError` 类型改 `(error: AgentError) => void`；`:511`/`:558` 改为构造 `AgentError`（`message` 文案与今日逐字一致）；`:559` 改 emit 同一 `AgentError`；订阅 transport 的 `compatibility_error` 并归一到同一形状；`:145`/`:722`/`:757`/`:780`/`:817`/`:898`/`:916` 七处 REST 抛错改走 `agentErrorFromResponse`（位于新文件 `core/errors.ts`；读 body 的 `error_code`，兼容旧响应的字符串 `code`，`retryable` 按 5xx/429 推断）。
8. `apps/ai-sdk/src/core/websocket.ts`：`handleClose` 把 4406 视为**终态**、不再进入退避重试；若此前已由 error 事件上报过（字段 `_compatibilityFailure`）则只置 `state='error'`，否则以兜底码 `protocol_negotiation_failed` 走 `emitCompatibilityError`（`retryable: false`）。子协议缺失时服务端在 `accept()` 之前关闭，发不出 error 帧，正是靠这条兜底路径。
9. `apps/ai-sdk/src/core/protocol.ts`：`ProtocolPayload` 的确认变体 `toolType` 联合补 `'builtin_tool'`（③a 已产出该取值）。
10. `apps/ai-sdk/src/index.ts`：re-export `PROTOCOL_VERSION`、`SDK_VERSION`（当前未从包根导出，接入方无法读取自己所说的协议版本）。
11. `gateway/schemas.py`：删除运行时不引用的出站协议模型（`_WireModel`、`EmptyPayload`、`MessageDeltaPayload`、`CitationPayload`、`ToolStatePayload`、`HostToolCallPayload`、`ConfirmationRequiredPayload`、`QuestionOption`、`QuestionRequiredPayload`、`ErrorPayload`、`ProtocolPayload`、`ProtocolEventType`、`ProtocolEnvelope`），保留入站仍在用的 `AttachmentRef`/`MessageSendPayload`，并注释指向 `agent_runtime/events.py`；`tests/gateway/test_protocol.py` 重写为对真编码路径（`to_wire`/`format_sse_event`）的断言，`tests/gateway/test_question_flow.py:19`/`:270` 改断言真出站帧。
12. **capabilities 删除双向声明**（用户已定）：后端 `auth.py:10` 去掉 `CAPABILITIES` 常量、`router.py:1087` 的 `session_ready.payload.capabilities` 去掉；SDK `websocket.ts:186` 不再上报 `capabilities`，`websocket.ts:213-219`/`:90-92`/`:50` 的 `_serverCapabilities` 读取与 getter 删除。理由：零消费者、两端取值命名空间不一致（后端是传输能力 `replay`/`host_tools`/`cancellation`，SDK 是交互能力 `questions`），且 ADR 0007:19 本就决定不把传输能力子集写进 `capabilities`。
13. 共享 golden 与夹具对齐：`apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json` 的 `session_ready` payload 改为含 `serverVersion`/`minimumSdkVersion`（不再含 `capabilities`），`apps/backend/tests/gateway/test_event_parity.py` 同步剧本。
14. `docs/design/agent-sdk-phase-2c-compatibility-matrix.md`：更新 SDK 版本为 0.2.0，补「不兼容时先发 error 事件再关闭 4406」「REST `error_code`」两节，并把 capabilities 一行改为「已删除，见 ADR 0007」。
15. 不在本轮：`/api/agent-token` 无鉴权与 `apps/ai-sdk/demo/index.html:105-106` 的 `client_secret` 泄漏，另立 request。

## 验收标准

1. WS 用 `protocolVersion=2` 连接：收到 `type=error`、`payload.code=unsupported_protocol_version`、`retryable=false`、`details.serverVersion` 与 `details.minimumSdkVersion` 非空，随后 close 4406。
2. WS `sdkVersion=0.0.1` → `unsupported_sdk_version`；**缺** `protocolVersion`/`sdkVersion` → 同样被拒（不再是默认放行），并有用例锁定。
3. 缺子协议 → 服务端在 `accept()` 之前 `close(4406)`（关闭码客户端不可见，实测表现为握手期 `HTTP 403`），且**不**发 error 事件（与今日一致），有用例锁定。
4. 非流式 REST 触发 `ChatModelUnavailable`：HTTP 409、body `code == 409` 不变，且新增 `error_code == "chat_model_unavailable"`。
5. `apps/backend/tests/workflows/test_routes.py:110`/`:210` 等既有 `code` int 断言全部不变。
6. SDK `onError` 收到的对象满足 `isAgentError(...)`（`instanceof Error` 且 `name === 'AgentError'`），`code === "agent_upstream_unavailable"`、`retryable` 为布尔、`message` 与今日逐字一致；`agent.on('error')` 收到**同一个对象**。
7. SDK 遇服务端 close 4406：只 emit 一次 `compatibility_error` 且**不**发起退避重试（不出现第 2 次连接尝试）。
8. SDK REST 辅助函数在 4xx 时抛 `AgentError` 且 `code` 来自响应体；响应体无字符串码时为 `http_<status>`。
9. `PROTOCOL_VERSION` 与 `SDK_VERSION` 可从 `apps/ai-sdk` 包根导入。
10. 错误码登记表为唯一来源：`grep` 断言 `_send_protocol_error` 与 `build_agent_error_payload` 的调用点不再出现裸字符串码字面量。
11. `gateway/schemas.py` 不再含运行时协议模型；`tests/gateway/test_event_parity.py` 与 `apps/ai-sdk/src/core/__tests__/protocol.test.ts` 对同一 golden 全绿。
12. `python3 tools/harness/audit.py` → `ERROR: 0`；`bash tools/harness/verify.sh 2026-10-19-sdk-protocol-alignment` 退出码为 0 或 3（未执行项逐条声明）。
13. capabilities 已双向删除：`session_ready` payload 不含 `capabilities`，SDK auth 帧不含 `capabilities`，`grep -rn "capabilities" apps/backend/app/modules/gateway apps/ai-sdk/src` 无命中。
