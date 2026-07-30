# Phase 2C 生产核心增强设计

## 背景

Phase 2A 已完成短期 Embed Token、`ai-agent.v1` WebSocket、Redis Stream 有限恢复和 SDK 真实流式聊天；Phase 2B 已完成宿主工具三重白名单、确认状态机、幂等执行和独立审计。Phase 2C 首个 request 聚焦生产核心，不提前实现管理后台和完整客户端体验治理。

## 目标

为现有网关和 SDK 增加多租户资源配额、运行指标、协议兼容门禁和可发布的双格式 SDK 产物，使本地验证能够证明资源隔离、故障降级、版本协商和包入口均有明确行为。

## 方案

### 配额

新增独立 quota store，使用 Redis 固定窗口计数和原子 Lua/事务语义完成检查与递增。key 包含维度类型及稳定 ID，避免不同平台、Client、Agent、最终用户之间共享计数。配额通过后端环境配置提供默认值，覆盖 token 签发、连接、消息和模型消费四类资源；本阶段不引入后台配置 API、长期用量事实表或账单系统。

Redis 不可用时返回稳定的 `quota_unavailable` 错误，并记录指标和日志；不允许因为限流存储不可用而静默放开生产限制。

### 可观测性

新增统一 metrics 模块，使用 Counter 和 Histogram 暴露连接数、认证结果、重连/恢复结果、消息计数、消息延迟、工具耗时、错误率和配额拒绝。指标标签仅使用有限枚举或受控 Agent 维度；requestId、conversationId 等仅进入结构化日志关联字段。`/metrics` 输出不包含 token、secret、工具参数和最终用户信息。

### 协议兼容

保持 `ai-agent.v1` 和协议主版本 1。SDK 在 `auth` 中发送 SDK 版本与协议版本；网关校验支持范围，主版本不兼容时在认证前返回稳定错误。`session_ready` 增加服务端版本、最低 SDK 版本和能力集合。相同主版本允许忽略未知可选字段，新增能力通过 capability 名称协商。兼容矩阵作为中文发布文档和协议测试的一部分维护。

### SDK 发布

保留 Vite library mode，ESM 为主入口，UMD 作为 CDN/script 入口；`package.json exports` 明确 import、require 和 types 路径。构建后使用 TypeScript、Vitest、`npm pack --dry-run` 和浏览器/Node 最小加载检查，确保 dist 内没有 token、secret 或调试日志残留。不在本 request 新增 React/Vue 包装层或外部 CDN 上传。

## 组件边界

- 后端 `quota` 只负责配额策略读取、Redis key、原子检查和稳定异常，不感知 WebSocket 业务细节。
- 后端 `observability` 只负责指标定义、关联日志字段和 metrics 暴露，不把业务数据写入指标。
- `gateway` 负责在业务生命周期边界调用 quota/metrics，并保持原有认证、恢复和消息语义。
- SDK `protocol` 负责版本和能力解析；`websocket` 负责发送版本声明并处理不兼容错误；构建配置负责公共入口和产物验证。

## 风险与降级

- Redis 故障会阻止受保护操作，必须可识别并可告警。
- 模型供应商未返回 token usage 时，模型消费配额只能记录请求级 fallback，不伪造 token 数；该限制写入验收风险。
- 指标标签必须防止最终用户和 requestId 高基数扩散。
- 老 SDK 只发送 Phase 2A auth 字段时，若协议主版本仍为 1，网关保持向后兼容；只有声明了不支持的主版本才拒绝。

## 验证策略

后端使用 pytest 覆盖配额原子性、维度隔离、Redis 异常、指标样本和协议协商；SDK 使用 Vitest 覆盖版本字段、能力解析、拒绝/降级事件和构建入口；执行 Ruff、Black 检查、Poetry check、SDK type-check/test/build、npm pack 产物检查和 git diff --check。
