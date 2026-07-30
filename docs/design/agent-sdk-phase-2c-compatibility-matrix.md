# Agent SDK Phase 2C 兼容矩阵

## 当前版本

| 项目 | 当前值 |
|---|---|
| WebSocket 子协议 | `ai-agent.v1` |
| 线协议主版本 | `1` |
| 后端版本 | `0.1.0` |
| SDK 版本 | `0.1.0` |
| 后端最低 SDK 版本 | `0.1.0` |

## 兼容规则

- 主版本不匹配在 token 解码前拒绝，稳定错误码为 `unsupported_protocol_version`，WebSocket close code 为 `4406`。
- SDK 版本低于后端最低版本时拒绝，稳定错误码为 `unsupported_sdk_version`，不可重试。
- 同一主版本允许新增可选 envelope 字段和 capability；客户端必须忽略未知可选字段。
- `session_ready` 返回 `serverVersion`、`minimumSdkVersion` 和 `capabilities`，SDK 保存并暴露能力集合。
- token 不进入 URL、日志、错误对象或发布包。

## 升级顺序

1. 先部署能兼容旧 SDK 的后端。
2. 发布包含新 capability 处理的 SDK。
3. 新能力稳定后再把 capability 纳入接入方使用范围。
4. 需要提升协议主版本时，先建立新的子协议和独立兼容窗口。

## 弃用窗口

Phase 2C 当前只承诺协议主版本 1 内兼容；新增字段至少经过一个 SDK 发布周期后才能成为必填字段。主版本 2 不在本 request 内实现。
