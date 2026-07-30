# 业界调研记录

## 调研问题

本 request 需要为 Phase 2C 建立可上线的生产核心能力：按平台、Client、Agent、最终用户维度限制连接/消息/token/model 消费，提供网关和 SDK 的可观测性，明确协议与版本兼容边界，并让 SDK 具备可验证的 ESM、UMD 和 CDN 构建产物。

调研重点是选择不会破坏现有 `ai-agent.v1` WebSocket、Redis Stream 恢复和 Vite SDK 构建的增量方案，同时避免在 Phase 2D 之前引入后台配置页面或完整计费系统。

## 功能复杂度

- 级别：核心功能
- 选择理由：影响 WebSocket 运行时、Redis 状态、SDK 发布契约和线上运维；错误的限流或兼容策略可能造成跨租户资源争用、协议升级中断或指标不可用。
- 最低调研要求：官方协议/标准资料、成熟开源或生产实践案例，并覆盖安全、性能、可观测性和发布兼容性。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenTelemetry Metrics and semantic conventions
- 链接：https://opentelemetry.io/docs/specs/otel/metrics/
- 版本或发布日期：在线规范，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：使用 Counter、Histogram 等稳定度量类型；属性用于维度筛选，但应控制属性基数和命名一致性。
- 对本项目的启发：网关指标使用连接数、认证结果、消息处理时延、恢复结果、工具耗时等低基数标签；`requestId`、最终用户 ID 和完整错误文本进入结构化日志关联字段，不作为 Prometheus 标签。

### 来源 2

- 类型：官方文档
- 名称：Prometheus instrumentation best practices
- 链接：https://prometheus.io/docs/practices/instrumentation/
- 版本或发布日期：在线文档，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：指标名称表达业务含义，标签数量受控；延迟使用 Histogram；服务通过标准 metrics endpoint 暴露数据。
- 对本项目的启发：后端增加统一指标注册和 `/metrics` 暴露，按 `agent_id`、结果类别等有限维度统计，避免直接暴露敏感内容。

### 来源 3

- 类型：成熟开源项目/官方文档
- 名称：Redis INCR、EXPIRE 与 Lua 脚本原子操作
- 链接：https://redis.io/docs/latest/commands/incr/；https://redis.io/docs/latest/develop/programmability/eval-intro/
- 版本或发布日期：Redis 7.x 在线文档，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：短窗口计数使用带 TTL 的 key；多维度扣减需要在 Redis 脚本中保持检查与写入的原子性，避免并发请求超发。
- 对本项目的启发：配额检查封装为独立 Redis quota store，一次请求同时检查连接、消息、token 签发和模型消费预算；Redis 不可用时返回明确的 `quota_unavailable`，不静默放开限制。

### 来源 4

- 类型：官方规范
- 名称：Semantic Versioning 2.0.0
- 链接：https://semver.org/
- 版本或发布日期：2.0.0，在线规范，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：主版本变化表示不兼容 API 变化；次版本增加向后兼容能力；补丁版本只修复兼容问题。
- 对本项目的启发：线协议主版本仍固定为 1；SDK 包版本遵守 SemVer，协议事件只新增可忽略字段或能力，不用 SDK 包版本替代协议版本。

### 来源 5

- 类型：官方文档
- 名称：Node.js package `exports` 与条件导出
- 链接：https://nodejs.org/api/packages.html#conditional-exports
- 版本或发布日期：Node.js 在线文档，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：通过 `exports` 明确 import/require/types 入口，避免消费者绕过公共入口访问内部文件；浏览器/CDN 场景可使用 UMD/IIFE 等构建产物。
- 对本项目的启发：保留 ESM 为主入口，明确 `import`、`require` 和类型入口，补充可直接由 CDN 加载的 UMD 产物和 `npm pack --dry-run` 验证。

### 来源 6

- 类型：成熟生产实践
- 名称：Envoy Global Rate Limit Service
- 链接：https://www.envoyproxy.io/docs/envoy/latest/configuration/other_features/global_rate_limiting
- 版本或发布日期：Envoy 在线文档，2026-07-29 访问
- 调研日期：2026-07-29
- 核心做法：限流策略与业务请求分离，网关在请求进入关键资源前执行统一检查；多实例通过共享限流服务保持全局一致。
- 对本项目的启发：将 quota store 放在 gateway/runtime 外的独立服务模块中，连接建立、消息发送和 token exchange 共享同一检查接口，Redis 作为多实例共享状态。

## 方案比较

### 配额与限流

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 应用进程内计数 | 实现简单、无额外依赖 | 多实例不一致，进程重启丢失，无法保证租户公平性 | 低 |
| Redis 固定窗口计数 | 复用现有 Redis，性能高，行为易验证 | 窗口边界可能产生突发流量 | 中高，适合 Phase 2C 默认配额 |
| Redis Lua 滑动窗口/令牌桶 | 并发原子性好，突发控制更平滑 | 实现和运维复杂度更高，需要更多压测 | 中，作为后续精细化策略 |

最终采用“Redis 原子固定窗口 + 独立 quota store 抽象”。本阶段通过环境变量定义各维度默认限制，预留策略注入接口；不增加后台配额管理 API，也不把短期 Redis 计数当作长期计费事实。

### 可观测性

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 仅结构化日志 | 接入成本低，适合排查单次请求 | 无法直接聚合延迟、错误率和恢复率 | 中低 |
| Prometheus metrics + 结构化日志 | 依赖少，查询和告警成熟，适配当前 FastAPI | 需要控制标签基数，不提供完整分布式 trace | 高 |
| 全量 OpenTelemetry trace/metrics/logs | 跨服务关联能力强 | 依赖和部署成本明显增加，当前只有单体后端 | 中，留作后续演进 |

最终采用 Prometheus exposition 加结构化日志，暂不引入完整 OpenTelemetry SDK。

### 协议与发布兼容

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 仅依赖 WebSocket subprotocol | 握手简单 | 无法表达 SDK/后端最低版本和能力差异 | 低 |
| 主版本门禁 + 能力声明 + SemVer 包 | 与现有 `ai-agent.v1` 兼容，升级边界清晰 | 需要维护兼容矩阵和测试 | 高 |
| 引入 Socket.IO/托管协议 | 自带部分恢复和兼容能力 | 改变现有协议和依赖，破坏 Phase 2A/2B 边界 | 低 |

最终采用现有原生 WebSocket 协议：主版本不兼容时在认证前拒绝；同一主版本内未知可选事件字段忽略；`session_ready` 返回服务器版本和能力；SDK/后端发布矩阵写入文档并由测试覆盖。

### SDK 发布格式

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 仅 ESM | 现代构建简单，tree-shaking 好 | 旧式 script/CDN 和 CommonJS 无法直接使用 | 中 |
| ESM + UMD + `exports` | 覆盖现代 bundler、CommonJS 和 CDN，沿用现有 Vite library mode | 包体和发布验证略复杂 | 高 |
| 同时开发 React/Vue 包装层 | 覆盖更多框架 | 扩大公共 API 和维护面，不是生产核心必需 | 低 |

最终采用 ESM + UMD + `exports`，不新增 React/Vue 包装层；CDN 仅提供可验证的 UMD 文件，不在本 request 接入外部 CDN 发布服务。

## 最终决策

- 选择方案：Redis 原子固定窗口配额、Prometheus + 结构化日志、`ai-agent.v1` 主版本/能力协商、Vite ESM/UMD 双产物与 `package.json exports` 发布验证。
- 选择原因：最大程度复用 2A/2B 已有 Redis、FastAPI、协议和 SDK 构建结构，能覆盖生产核心验收，同时不提前引入后台管理、计费事实表或新协议栈。
- 不选择其他方案的原因：进程内限流无法支持多实例；全量 OpenTelemetry 和滑动窗口需要额外部署与压测证据；Socket.IO 会破坏现有协议；React/Vue 包装层和数据合规页面超出本 request。
- 对后续 spec、plan 或人工确认的影响：配额策略采用环境配置而非后台 API；Redis 状态只用于短期限制，不能作为账单数据；本 request 仍涉及网关运行时和 SDK 公共发布契约，进入实现前需要用户确认正式 spec。

## 剩余风险

- 资料时效性：官方在线文档在 2026-07-29 访问，具体实现版本仍需以项目 lockfile 和部署镜像为准。
- 与本项目上下文的差异：Prometheus/Envoy 的生产部署规模大于当前单体 FastAPI，需通过本地集成和并发测试验证降级行为。
- 尚未验证的假设：Redis 连接异常时是否允许只读/继续聊天；模型 token usage 是否能从当前 runtime 稳定获得；UMD 在无构建工具的浏览器中是否可直接执行。
