# Phase 2C 生产核心增强设计说明

## 目标

为 Phase 2A/2B 的 FastAPI WebSocket 网关和 `apps/ai-sdk` 增加可上线的生产核心能力：多租户资源配额、结构化可观测指标、协议版本兼容门禁，以及 ESM/UMD/CDN 可验证发布产物。关键决策记录在同 request 的 `research.md`，采用 Redis 原子固定窗口、Prometheus + 结构化日志、`ai-agent.v1` 主版本/能力协商和 Vite 双格式构建。

## 范围

- 新增后端独立 quota store，按平台、Embed Client、Agent、平台最终用户维度隔离连接、消息、token 签发和模型消费限制；本阶段默认值由环境配置提供。
- 在 token exchange、WebSocket 连接和消息生命周期接入配额检查，返回稳定错误并记录拒绝原因。
- 新增 Prometheus metrics 暴露与结构化关联日志，覆盖连接、认证、重连/恢复、消息延迟、工具耗时、错误和配额拒绝。
- 扩展 auth/session_ready 的 SDK 与后端版本/能力字段，增加主版本不兼容拒绝和同主版本向后兼容测试。
- 调整 SDK 包入口和 Vite 构建校验，产出 ESM 与 UMD，验证 `exports`、类型入口、npm 包内容和 CDN script 加载。
- 补充中文兼容矩阵、环境变量说明、运行手册、测试和 Harness 验证记录。

## 非目标

- 不新增配额管理后台 API、账单结算系统或计费用余额扣减语义。
- 不引入完整 OpenTelemetry SDK、Socket.IO、独立网关服务或滑动窗口限流。
- 不实现多标签页协调、离线队列、可访问性、国际化、主题治理、会话保留/删除/导出。
- 不开发 React/Vue 包装层，不上传到外部 CDN；只验证可供 CDN 使用的 UMD 文件。

## 风险

- Redis 故障会阻止受保护操作；必须返回 `quota_unavailable`，不静默放开限制。
- 指标不能使用 requestId、conversationId 或最终用户 ID 作为高基数标签；这些只进入脱敏结构化日志。
- 当前运行时可能无法稳定取得模型 token usage；缺失时不伪造 token 消费量，也不写入 `model_usage_records` 明细。
- 老 SDK 只发送既有 auth 字段时必须保持协议主版本 1 的兼容；不支持的主版本要在认证前稳定拒绝。
- 构建产物若暴露调试日志或敏感配置，会扩大 SDK 发布风险。
- `model_usage_records` 是模型返回 usage 后的事实明细，不替代 Redis 窗口配额；若真实模型未返回 usage，只能通过 completed 事件缺失 usage 识别。

## 停点判断

- 是否涉及架构边界变化：是，新增 quota/observability 运行时模块，但不拆部署服务。
- 是否涉及数据模型变化：是，2026-07-30 已按用户确认新增独立 `model_usage_records` 模型用量明细表。
- 是否涉及 API 契约变化：是，增加 auth/session_ready 版本和能力字段，并新增 `/metrics`。
- 是否涉及鉴权或权限行为变化：是，连接、消息和 token exchange 增加配额门禁。
- 结论：已于 2026-07-29 获得人工确认，允许进入 spec 和 plan；实现前沿用本确认，不扩大到后台配置或计费语义。

## 验收标准

- 不同平台、Client、Agent、最终用户的配额计数互不影响；并发检查不会超过配置上限。
- token 签发、连接建立、消息发送和模型消费分别受对应配额约束，超限返回稳定 code、retryable 和必要 details。
- Redis 不可用时受保护操作失败并产生可查询指标，日志不包含 token、secret、工具参数或最终用户身份。
- `/metrics` 可返回连接数、认证结果、恢复结果、消息延迟、工具耗时、错误和配额拒绝样本，标签集合保持低基数。
- SDK 发送版本声明，服务端返回版本/能力信息；不兼容主版本被稳定拒绝，同主版本未知可选字段不阻断处理。
- SDK 构建产生 ESM、UMD 和类型入口，`package.json exports` 与 `npm pack --dry-run` 结果一致，UMD 可由最小 HTML script 加载。
- SDK 发布 tarball 必须包含所有被公共类型入口引用的声明文件；Node.js 的 ESM 和 CommonJS 消费者都必须获得公共导出，CSS 必须通过稳定包子路径访问；发布命令必须先重建并执行包验证。
- 模型返回 usage 时，后端写入独立 `model_usage_records` 明细，字段覆盖平台、Agent、AgentVersion、Embed Client、最终用户、conversation、assistant message、requestId、模型名和 `prompt_tokens/completion_tokens/total_tokens`。
- 后端定向测试、全量 pytest、Ruff、Black 检查、Poetry check，以及 SDK type-check/test/build 全部通过；真实命令和结果写入 `verify.md`。

## 变更记录

### 2026-08-04 修复：聊天过程日志与 embedding 密钥脱敏

- 变更原因：用户反馈聊天时难以判断知识库上下文是否真正进入检索与 prompt，且运行时日志存在 embedding API Key 明文输出风险。
- 变更内容：为 conversation / gateway / knowledge 运行时补充分阶段结构化日志，覆盖上下文加载、引用检索、系统 prompt 构造、聊天开始与完成；同时移除 embedding API Key 明文日志，仅记录是否存在密钥。
- 影响章节：风险、验收标准、实施方式。
- 是否触发人工确认：否；仅属于既有 observability 闭环内的日志增强与脱敏修复，不改变 API、数据模型或权限行为。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-07-31 修复：npm 发布包消费者契约

- 变更原因：发布前审查发现 CommonJS 入口导出为空，类型声明依赖的子目录未进入 tarball，CSS 没有可访问的包子路径，且发布流程不会自动重建产物。
- 变更内容：修正 UMD/CommonJS 文件扩展名和 `exports`，发布完整 `dist` 声明，增加 CSS 子路径和发布前构建验证，补充真实 tarball 消费者测试；移除未实现的 SSE 公开声明。
- 影响章节：范围、风险、验收标准。
- 是否触发人工确认：否；属于已确认的 SDK ESM/UMD/类型/npm 发布治理闭环内的 bug 修复，不改变后端协议和权限行为。
- 关联计划更新：已同步更新 `plan.md`。

### 初始版本

- 时间：2026-07-29。
- 变更原因：Phase 2A/2B 已完成，开始 Phase 2C 生产核心增强。
- 变更内容：建立配额、可观测性、协议兼容和发布治理的独立 request。
- 影响章节：全部。
- 是否触发人工确认：是，用户已于 2026-07-29 确认范围与技术设计。

### 增量：模型用量明细表

- 时间：2026-07-30。
- 变更原因：真实模型 usage 已可见，需要从 completed 事件扩展为可查询、可审计的独立明细。
- 变更内容：新增 `model_usage_records` 表，仅在模型供应商返回标准 usage 时写入明细；Redis quota 继续只负责窗口限制。
- 影响章节：范围、非目标、风险、停点判断、验收标准。
- 是否触发人工确认：是，用户明确要求按“独立 model_usage_records 用量明细表”的方案推进。
