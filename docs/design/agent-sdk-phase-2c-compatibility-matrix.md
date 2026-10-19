# Agent SDK Phase 2C 兼容矩阵

## 当前版本

| 项目 | 当前值 | 来源 |
|---|---|---|
| WebSocket 子协议 | `ai-agent.v1` | `apps/backend/app/modules/gateway/auth.py` 的 `PROTOCOL_SUBPROTOCOL` |
| 线协议主版本 | `1` | `PROTOCOL_SUBPROTOCOL` 与 `apps/ai-sdk/src/core/protocol.ts` 的 `PROTOCOL_VERSION` |
| 后端版本 | `0.1.0` | `apps/backend/app/modules/gateway/auth.py` 的 `SERVER_VERSION` |
| 后端最低 SDK 版本 | `0.1.0` | `apps/backend/app/modules/gateway/auth.py` 的 `MINIMUM_SDK_VERSION` |
| SDK 版本 | `0.2.0` | `apps/ai-sdk/package.json` 的 `version`（SDK 运行期读取，非硬编码） |

## 兼容规则

- 握手帧（`auth`）必须同时携带 `protocolVersion` 与 `sdkVersion`；缺任一字段按协议主版本不匹配处理，**不再回落默认值**。
- 主版本不匹配在 token 解码前拒绝，稳定错误码 `unsupported_protocol_version`；SDK 版本低于后端最低版本时拒绝，稳定错误码 `unsupported_sdk_version`（不可重试）。
- 两种不兼容都先下发一条 `error` 事件（payload 带 `code`/`message`/`retryable` 与 `details{serverVersion, minimumSdkVersion, supportedProtocolVersion}`），随后以 close code `4406` 关闭连接。SDK 侧统一以 `AgentError` 暴露：`agent.on('compatibility_error')`、`onError` 与 `connect()` 的 reject 拿到的是同一个对象。
- 同一主版本允许新增可选 envelope 字段；客户端必须忽略未知可选字段。**协议能力声明（`capabilities`）已双向删除**：后端不再在 `session_ready` 返回，SDK 不再在 `auth` 上报。原因是两端取值命名空间不一致（后端曾是传输能力 `replay`/`host_tools`/`cancellation`，SDK 曾是交互能力 `questions`）且无消费者。若将来确需能力协商，应在新 request 中定义一份双方共享的能力清单，而不是恢复这两个字段。
- `session_ready` 返回 `serverVersion`、`minimumSdkVersion`，SDK 可据此判断自身是否落后；不再返回能力集合。
- REST 响应体在 HTTP 状态码之外提供稳定业务码 `error_code`（`code` 仍是 HTTP 状态码）；SDK 的 `AgentError.code` 取自 `error_code`。
- token 不进入 URL、日志、错误对象或发布包。

## 升级顺序

1. 先部署能兼容旧 SDK 的后端（旧 SDK 的 `auth` 帧已带 `protocolVersion`/`sdkVersion`，无需改造即可通过握手）。
2. 再发布使用新错误形状的 SDK。
3. 新能力稳定后再纳入接入方使用范围。
4. 需要提升协议主版本时，先建立新的子协议和独立兼容窗口。

## 弃用窗口

Phase 2C 当前只承诺协议主版本 1 内兼容；新增字段至少经过一个 SDK 发布周期后才能成为必填字段。主版本 2 不在本 request 内实现。
