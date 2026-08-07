# 内置 HTTP GET 工具业界调研

## 调研问题

- 如何让 Agent 以结构化工具调用方式访问公开的 HTTP/HTTPS GET 资源，同时支持 JSON、文本、图片和普通文件？
- 如何避免 Agent 可控 URL 引入 SSRF、内网探测、云元数据访问、无限重定向和超大响应风险？
- 文本响应与二进制响应应如何进入模型上下文和平台存储？
- 该能力应复用 MCP，还是建立平台原生的内置工具边界？

## 功能复杂度

- 级别：核心功能。
- 选择理由：该工具让模型主动访问外部网络，并新增 Agent 能力绑定、通用资源存储和下载权限，涉及架构、数据模型、API 契约及鉴权行为。
- 最低调研要求：覆盖官方 HTTP 客户端实践、SSRF 安全规范、成熟 Agent 工具设计，并分析安全、存储、可观测性和生产部署风险。

## 参考依据

### 来源 1：OWASP SSRF 防护指南

- 类型：权威安全规范。
- 名称：OWASP Server-Side Request Forgery Prevention Cheat Sheet。
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- 版本或发布日期：在线持续维护版本，页面访问日期 2026-08-07。
- 调研日期：2026-08-07。
- 核心做法：优先使用目标允许列表；无法使用允许列表时，仅开放必要协议，解析并校验域名对应的全部 IPv4/IPv6 地址，阻止非公网地址和云元数据目标，谨慎处理或关闭自动重定向，并补充网络层出口限制。
- 对本项目的启发：工具输入只保留 URL，不开放任意 Header、Cookie 或认证信息；仅允许 HTTP/HTTPS；应用自行逐跳处理重定向并重复 URL、DNS 和 IP 校验；生产环境仍需出口防火墙作为纵深防御。

### 来源 2：HTTPX 官方文档与源码

- 类型：官方文档与官方源码。
- 名称：HTTPX Async Support、Streaming Responses、AsyncClient.stream。
- 链接：https://www.python-httpx.org/async/ ，https://github.com/encode/httpx/blob/master/docs/async.md
- 版本或发布日期：项目当前锁定 HTTPX 0.28.1；官方在线文档访问日期 2026-08-07。
- 调研日期：2026-08-07。
- 核心做法：使用 `AsyncClient.stream()` 和 `aiter_bytes()` 流式消费响应，避免一次性载入内存；通过异步上下文确保响应关闭；显式配置超时和重定向上限。
- 对本项目的启发：文本与二进制统一流式读取，在读取过程中累计原始字节并执行硬上限；禁用 HTTPX 自动重定向，由业务代码逐跳验证目标并限定最多 3 次。

### 来源 3：LangChain Requests Toolkit

- 类型：成熟开源 Agent 工具案例。
- 名称：LangChain `RequestsToolkit`、`RequestsGetTool`、`RequestsGetToolWithParsing`。
- 链接：https://reference.langchain.com/python/langchain-community/agent_toolkits/openapi/toolkit/RequestsToolkit
- 版本或发布日期：LangChain Community 在线参考文档，访问日期 2026-08-07。
- 调研日期：2026-08-07。
- 核心做法：通用网络请求能力默认视为危险能力，需要显式 `allow_dangerous_requests=True` 才能启用；GET 工具对模型暴露明确工具定义；带解析版本设置响应长度上限，避免整份响应无界进入模型。
- 对本项目的启发：`http_get` 不能成为所有 Agent 的隐式默认能力，必须通过 Agent 绑定显式启用；工具返回必须有固定 Schema，文本/JSON 内容需要截断标志和模型上下文上限。

### 来源 4：仓库现有知识库抓取实现

- 类型：本项目成熟实现基线。
- 名称：`knowledge.runtime.fetch_web_text` 与 `validate_fetch_target`。
- 链接：`apps/backend/app/modules/knowledge/runtime.py`、`apps/backend/app/modules/knowledge/services.py`。
- 版本或发布日期：仓库 `main` 分支，调研时 HEAD `31482b9`。
- 调研日期：2026-08-07。
- 核心做法：仅允许 HTTP/HTTPS，拒绝凭证、回环和非公网目标；解析域名全部地址；关闭自动重定向并逐跳检查；流式读取并执行大小限制。
- 对本项目的启发：新工具应抽取或复用这套安全语义，但不能直接复用只面向 HTML 文本抽取的 `fetch_web_text`；通用响应需要媒体类型分流、临时文件和资源权限模型。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：直接使用 Tavily 等远程 MCP | 接入快，搜索和提取能力成熟，现有 MCP 绑定与白名单可复用 | 工具契约和可用性受第三方控制；普通 URL 与内容会发送给第三方；不能建立平台统一的通用文件资源边界 | 适合 `web_search`，不适合作为平台原生通用 GET 的唯一实现 |
| 方案 B：平台原生内置工具、Agent 显式绑定、二进制进入受控资源存储 | 工具契约稳定；可统一权限、审计、限额和错误；文本与文件均形成闭环；未来可以复用安全 HTTP 客户端 | 需要新增工具绑定、资源模型、下载 API 和运行时分发，实施与验证成本较高 | 高，满足已确认的长期内置工具方向 |
| 方案 C：全部响应直接内联到工具结果 | 数据模型和下载接口改动少 | Base64 和大文本会占用模型上下文、消息存储和带宽；客户端无法稳定复用文件 | 低，不适合生产环境 |
| 方案 D：二进制只返回原始 URL 和元数据 | 改动最小，不需要资源存储 | 工具没有真正托管图片或文件；外链可能失效；无法执行平台归属与下载权限 | 仅适合一次性演示，不满足完整闭环 |

## 最终决策

- 选择方案：方案 B。
- 选择原因：该方案把模型工具、网络访问和文件资源拆成独立边界，符合仓库现有 Agent 绑定、统一工具循环和平台隔离模式；能够在不向模型内联二进制的前提下支持 JSON、文本、图片和普通文件。
- 不选择其他方案的原因：MCP 保留用于搜索及第三方能力，但不替代平台通用 GET；内联二进制存在明显上下文风险；只返回外链不能形成可控资源闭环。
- 对后续 spec、plan 或人工确认的影响：需要新增 `builtin_tool` 与 `asset` 模块，增加数据表、管理 API、资源下载 API、运行时工具分发和权限校验。架构、数据模型、API 和鉴权均发生变化，进入实现前必须人工确认。

## 生产约束与剩余风险

- 应用层 DNS 校验与客户端真实连接之间存在时间窗口，不能单独证明彻底消除 DNS rebinding；生产部署必须增加网络出口策略，阻止访问私网、链路本地和云元数据网段。
- 首期不提供域名允许列表配置，只采用非公网地址拒绝策略。对于高敏感平台，后续应增加平台级域名允许列表。
- 首期不做恶意文件扫描。文件只通过鉴权下载，并强制 `attachment` 与 `nosniff`；在允许在线预览或进入知识库前必须增加内容安全处理。
- `Content-Type` 可能错误或恶意。未知类型统一按 `application/octet-stream` 下载，不根据远端声明直接启用浏览器内联执行。
- 资源保留期和清理任务不在本 request 内实现；首期资源随会话归属持久保存，后续需根据存储成本补充生命周期策略。
