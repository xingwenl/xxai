# Agent SDK 生产增强运行手册

## 配置

- `QUOTA_ENABLED`：生产默认开启，开发环境默认关闭。
- `QUOTA_WINDOW_SECONDS`：固定窗口秒数，默认 `60`。
- `QUOTA_TOKEN_ISSUE_LIMIT`、`QUOTA_CONNECTION_LIMIT`、`QUOTA_MESSAGE_LIMIT`、`QUOTA_MODEL_TOKENS_LIMIT`：各资源默认上限。
- `METRICS_ENABLED`：是否暴露 `/metrics`，默认开启。
- `SDK_MINIMUM_VERSION`：后端允许接入的最低 SDK 版本。

配额计数只存在 Redis，key 带窗口 TTL；不要将 Redis 计数当作账单事实。当前实现不提供后台配置 API。

## 观测

抓取 `GET /metrics`，重点关注：

- `agent_gateway_authentication_total`
- `agent_gateway_connections_total`
- `agent_gateway_recovery_total`
- `agent_gateway_message_latency_seconds`
- `agent_gateway_tool_duration_seconds`
- `agent_gateway_errors_total`
- `agent_gateway_quota_rejections_total`

指标标签必须保持低基数。requestId、conversationId、外部用户标识和工具参数只能用于受控日志关联，不能新增为 Prometheus 标签。

## Redis 故障

Redis 不可用时，配额保护操作返回 `quota_unavailable` 并保持失败关闭；检查 Redis 连接、应用错误指标和网关日志。恢复 Redis 后重新建立连接或重试可重试请求，不清理其他业务数据。

## 发布

在 `apps/ai-sdk` 执行：

```bash
npm run test -- --run
npm run type-check
npm run build
npm run verify-package
npm_config_cache=/tmp/ai-sdk-npm-cache npm pack --dry-run
```

发布前确认包只包含 dist、README、package.json 和公共类型入口；UMD 文件可通过 CDN script 加载。发生兼容回归时，回滚 SDK 包版本和后端发布版本，不需要数据库迁移。
