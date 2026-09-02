# 业界调研记录：智能体接入店铺运营项目（查询我的店铺）

## 调研问题

- 本次要解决什么问题？
  - 在 `ai-base` 智能体上新增「店铺运营项目」能力：用户在对话中提问（如「查询我的店铺」），智能体通过工具调用获取店铺运营平台（花伴·店铺运营平台）中的店铺信息并组织回答。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 数据来源与接入形态：ai-base 业务工具直连运营平台 HTTP API，还是运营平台新增面向 AI 的网关接口，还是数据同步落库，还是 MCP Server；
  - 鉴权方式：运营平台登录 JWT（含验证码）复用，还是新增独立的 API Key 只读鉴权；
  - 「我的店铺」身份语义：平台级只读账号（MVP）还是用户级店铺绑定（需要数据模型）；
  - 是否需要新增数据模型（本方案评估为不需要）；
  - ai-base 侧新增业务工具契约与错误语义，是否需要动前端展示层。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及跨仓库（ai-base 与店铺运营平台 fastapi_vue3_project/backend）集成、外部系统鉴权、工具契约与权限边界，且「查询我的店铺」属于只读业务数据查询，必须明确暴露面与安全边界。
- 最低调研要求：官方/权威来源 + 成熟开源案例 + 企业生产实践（工具鉴权与网关模式）。

## 背景结论（先回答：连接外部业务系统的主流做法是什么）

- 业界把「Agent 连接外部系统」总结为两类接入形态：
  1. 自定义 Function Calling / 业务工具：用 JSON Schema 把任意本地函数（内部通常会去调用外部 API）暴露给 LLM，模型自主决定调用时机，鉴权、授权、副作用控制都在工具执行体内完成（OpenAI Agents SDK、LangChain 等主流框架一致做法）；
  2. MCP（Model Context Protocol）：开放标准，把外部数据源、工具、工作流封装成 MCP Server，AI 应用作为 MCP Client 接入，实现「一次构建、处处接入」（Claude、ChatGPT、Cursor 等均已支持）。
- 企业生产实践强调三点：
  1. 访问企业内部系统（ERP/CRM/业务后台）时，**必须通过网关/适配层暴露白名单只读接口**，不要把页面登录态、管理员 Token 直接交给 Agent 链路；
  2. 工具契约要有明确 JSON Schema / OpenAPI，错误对模型可见且稳定（错误码），避免把内部异常泄漏给 LLM；
  3. 先只读后写、先最小能力闭环，权限与副作用在工具内部强制，不能只靠提示词约束模型。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenAI Agents SDK - 工具（Tools）指南
- 链接：https://openai.github.io/openai-agents-js/zh/guides/tools/
- 版本或发布日期：核对于 2026-09-02（持续更新）
- 调研日期：2026-09-02
- 核心做法：
  - 函数工具（function tools）用 JSON Schema 封装任意本地函数，模型按 description 与 schema 自主调用；
  - 工具的典型用途就是「获取数据、调用外部 API、执行代码」；
  - 鉴权与授权必须在 `execute` 内强制实施，不能依赖模型层（`isEnabled` 无法替代参数级/资源级授权）；
  - 工具设计指南：说明简短明确、输入严格校验、错误处理返回对模型有帮助的字符串、单一职责、可组合。
- 对本项目的启发：`ai-base` 现有业务工具机制（`app/modules/tools/business/` + `registry.py`）与官方推荐模式一致；新增店铺查询应遵循同一范式：JSON Schema 输入契约、工具内完成鉴权与数据清洗、稳定错误码、单一职责（只做店铺查询）。

### 来源 2

- 类型：官方文档 / 标准规范
- 名称：Model Context Protocol 官方文档（2026-07-28 规范）
- 链接：https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro.md
- 版本或发布日期：2026-07-28（spec 快照），调研日期 2026-09-02
- 核心做法：
  - MCP 是连接 AI 应用与外部系统的开放标准，支持数据源、工具、工作流的接入；
  - 典型场景包括「企业聊天机器人连接多个组织内部数据库/API，让用户用对话分析数据」；
  - MCP Server 通过 JSON-RPC 暴露工具，Client 在宿主应用内连接。
- 对本项目的启发：`ai-base` 已具备 MCP 客户端与管理能力（`apps/backend/app/modules/mcp/`，支持 streamable HTTP 客户端、加密鉴权头、按智能体绑定工具），因此「店铺运营项目」的远期演进可以把运营平台能力包装为 MCP Server；但 MVP 不必引入完整 MCP 链路，先走更可控的业务工具 + 只读网关。

### 来源 3

- 类型：生产实践（企业架构厂商博客）
- 名称：Enterprise MCP Strategy: Be Agent-Ready Without the Rebuild（MuleSoft）
- 链接：https://blogs.mulesoft.com/agentic-perspectives/enterprise-mcp-strategy/
- 版本或发布日期：2026-03-02，调研日期 2026-09-02
- 核心做法：
  - 不要为 Agent 重建一套系统，而是把**既有的、稳定的 REST API 作为接口层（interfacing layer）暴露给 Agent**，并补充 Agent 需要的语义元数据（工具描述、参数契约）；
  - 通过接口层控制暴露面、鉴权与可观测性。
- 对本项目的启发：店铺运营平台已有成熟后端（FastAPIAdmin `api/v1/shop_v2.py` 提供店铺列表/详情/统计），不应在 ai-base 里复制业务逻辑，而是复用其 `ShopLogic` 在运营平台侧增加一层「面向 AI 的只读接口」，ai-base 只做工具封装与结果组织。

### 来源 4

- 类型：生产实践（MCP 协议企业落地指南）
- 名称：MCP 协议生产实践：AI Agent 工具调用标准化落地指南（腾讯云/阿里云开发者社区转载）
- 链接：https://cloud.tencent.com.cn/developer/article/2721396
- 版本或发布日期：2026-08-04，调研日期 2026-09-02
- 核心做法：
  - 企业通常通过自定义 Function Calling、API Gateway 暴露内部能力，并逐步向 MCP 标准化演进；
  - 权限控制、上下文传递、工具发现是三大核心问题；
  - 内部 API、数据库、知识库等能力封装为工具/Server 时都要先解决「谁能调、调什么、调了留痕」。
- 对本项目的启发：店铺查询工具的权限边界必须明确——只读、白名单接口、调用方（ai-base）使用独立 API Key，不直接复用运营平台页面账号体系。

### 来源 5

- 类型：生产实践（企业 AI 代理与内部 API 集成）
- 名称：Integración de agentes de IA con APIs internas enterprise（entia.systems）
- 链接：https://entia.systems/knowledge/es/ia-y-agentes/integracion-agentes-apis-internas-enterprise-ia/
- 版本或发布日期：2026-06-12，调研日期 2026-09-02
- 核心做法：
  - 把 ERP/CRM/数据平台作为**可调用工具**接入，必须具备鉴权、授权、可追踪性与副作用限制；
  - 模式：OpenAPI 作为契约来源；对系统注册（system of record）必须走统一网关；工具目录要有分层与归属管理。
- 对本项目的启发：运营平台是「system of record」，ai-base 不应直连其数据库或页面登录接口，应新增一个只读网关接口作为唯一入口，并在网关层做 API Key 鉴权与字段白名单（剔除 token/cookie 等敏感字段）。

### 来源 6

- 类型：仓库内成熟先例（内部实践）
- 名称：ai-base 内置业务工具 knowledge_search 的实现与调研（request 2026-08-31-knowledge-search-tool）
- 链接：docs/harness/requests/2026-08-31-knowledge-search-tool/research.md
- 版本或发布日期：2026-08-31，调研日期 2026-09-02
- 核心做法：
  - 新增业务工具遵循固定范式：`tools/business/<name>.py` 用 `@business_tool` 注册，声明 name/description/input_schema；
  - 权限在工具内部基于 `BusinessToolContext`（platform_id / agent_id / user_id）执行，错误用 `BusinessToolError` 稳定 code；
  - 注册到 `tools/business/registry.py`，由内置工具目录自动派生。
- 对本项目的启发：店铺查询工具沿用同一范式，`BusinessToolContext.user_id / platform_end_user_id` 可用于后续「用户 → 店铺」绑定扩展，MVP 先用平台级只读账号。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：ai-base 业务工具直连运营平台现有登录接口（复用 RuoYi JWT） | 不修改运营平台后端；ai-base 内闭环 | 登录接口带验证码、JWT 有生命周期需维护刷新；把管理后台页面账号体系暴露给 Agent 链路；「我的店铺」仍需账号绑定；安全性差 | 低 |
| 方案 B：运营平台新增「AI 只读网关」接口（API Key 鉴权），ai-base 业务工具调用 | 鉴权干净（独立 API Key、只读白名单）；暴露面可控（字段白名单剔除 token/cookie）；复用运营平台 `ShopLogic`，不复制业务逻辑；MVP 改动小、可独立测试；符合「网关作为系统注册入口」的生产实践 | 需要修改并部署运营平台后端（另一个仓库）；两仓库需要约定契约；MVP 不做用户级店铺绑定 | 高（推荐） |
| 方案 C：定时把店铺数据同步到 ai-base 数据库，工具查本地 | 查询快、不依赖外部可用性 | 数据非实时；新增数据模型（触发审批）；同步链路复杂、易失真；违背「system of record 唯一」原则 | 低 |
| 方案 D：把运营平台能力直接做成 MCP Server，ai-base 通过已有 MCP 模块绑定 | 业界标准、工具自动发现、可复用于其他 AI 客户端 | 需要公网可访问的 MCP 端点，暴露面更大；依赖 ai-base MCP 管理后台配置；MVP 周期长 | 中（作为 Phase 2 演进方向） |

## 最终决策

- 选择方案：**方案 B（第一阶段）**：在店铺运营平台 FastAPIAdmin 后端新增「AI 只读网关」接口（`X-Agent-Key` API Key 鉴权、字段白名单、只读），`ai-base` 新增业务工具 `store_ops_query` 调用网关，覆盖「查询我的店铺」（店铺列表 + 店铺详情）。方案 D（MCP Server）作为第二阶段演进，B 的 REST 契约保持稳定，未来可平滑包装为 MCP Server 或升级工具实现。
- 选择原因：
  - 与官方与生产实践一致：内部系统经网关暴露只读接口、工具内强制鉴权、JSON Schema 契约、稳定错误码；
  - 复用运营平台 `ShopLogic`，不在 ai-base 复制业务逻辑；
  - 不新增数据模型、不把页面登录鉴权引入 Agent 链路，安全边界清晰；
  - ai-base 现有业务工具机制可完全复用，改动面最小。
- 不选择其他方案的原因：
  - 方案 A：把带验证码的管理后台登录链路塞给 Agent，token 维护复杂且不安全；
  - 方案 C：数据不同步、需要新增数据模型，MVP 成本高；
  - 方案 D：作为 Phase 2 演进，MVP 不引入完整 MCP 链路（本仓库 MCP 模块存在，但本轮先做最小闭环）。
- 对后续 spec、plan 或人工确认的影响：
  - 触发人工确认（架构边界变化、API 契约变化、鉴权变化）；
  - 需要用户确认运营平台后端可修改/可部署、网络连通方式、MVP 身份语义与输出形态。

## 剩余风险

- 资料时效性：OpenAI Agents SDK 与 MCP 规范迭代较快，本文按 2026-09-02 快照核对；工具范式（JSON Schema + 工具内鉴权）属于长期稳定做法。
- 与本项目上下文的差异：调研来源均为通用企业实践，未覆盖「花伴·店铺运营平台」特有接口（已通过本地源码核对 `shop_v2.py` / `TShop` 模型确认可复用）。
- 尚未验证的假设：
  - 运营平台 FastAPIAdmin 后端可修改、可重启部署（需人工确认）；
  - ai-base 与运营平台后端网络可达（生产地址 `http://81.68.71.41:8068` 为 store-ops-web `.env.development` 中代理目标，实际部署地址需人工确认）；
  - 「我的店铺」MVP 先以平台级只读账号返回其可见店铺，用户级绑定留待 Phase 2（需人工确认）。

---

## 方案修订（2026-09-02，取代上文部分结论）

> 与用户逐点讨论后，需求形态发生变化：用户级绑定、token 时效跟随店铺系统、服务器端工具、新前端 + ai-sdk embedded。本修订记录新的方案比较与决策；上文「方案 B（平台级共享账号 + API Key 网关）」不再适用。

### 新增事实（本地核对）

- 店铺系统为 hua8（RuoYi 风格）：`GET /hua8-api/code`（验证码）→ `POST /hua8-api/auth/login` 返回 `access_token`（JWT，`expires_in=43200`）→ `POST /hua8-api/shop/platform/list`（`Authorization: Bearer`）返回当前用户可见的店铺列表。来源：`apps/shop/docs/login-shop.md`（2026-09-02 核对）。
- ai-sdk（`apps/ai-sdk/README.md`）已支持「宿主工具」（浏览器执行，token 不出浏览器）与「服务器工具」两类执行路径；`message_send` 协议 payload 仅含 `text/conversationId/attachments/systemPrompt`（`apps/backend/app/modules/gateway/schemas.py` `MessageSendPayload`），无自定义字段位。
- ai-sdk 生产接入要求「接入方服务端」代理 `POST /api/v1/embed/tokens`（`client_secret` 不进浏览器），`external_user_id` 必须来自已验证登录态。

### 追加方案比较

| 方案 | 优点 | 限制 | 结论 |
|---|---|---|---|
| 宿主工具（浏览器执行，token 不出浏览器） | 安全（token 不离开浏览器）、协议零改动 | 后续写操作（改价/上下架）不宜暴露在前端；浏览器直连 hua8 有 CORS 问题 | 不选：用户明确后续有大量服务器端操作，需服务器工具 |
| 消息 payload 携带 token（`message_send` 增加 `shopToken` 字段） | 实现直观 | 每条消息带 token：payload 冗余、消息落库/审计记录 token（泄漏面大）；需改 SDK 协议与兼容性矩阵 | 不选：改用会话级注入 |
| **会话级注入 + 服务器业务工具（选定）** | token 建会话时注入一次（Redis，TTL=43200 跟随店铺 token 时效）；工具从 `BusinessToolContext` 读取；`message_send` 协议零改动；服务端执行，后续写操作可平滑扩展；错误天然透传 | ai-base 持有店铺 token（自有系统，可接受）；需防 `shopUserId` 伪造（可用店铺 token 调用户信息接口校验） | **选定** |

### 最终决策（修订）

- 新增 ai-base 接口 `POST /api/v1/shop-agent/session`：浏览器传 `{shopToken, shopUserId}`，服务端将店铺 token 加密存 Redis（TTL=43200）并复用 Embed Token 链路签发 embed access_token（`external_user_id=shopUserId`）。
- 新增业务工具 `store_ops_query`（MVP 仅 `list_my_shops`）：用会话注入的店铺 token 调 hua8 `shop/platform/list`，结果与错误透传。
- 新前端 `apps/shop/`（vite-vue）：登录页（hua8 登录）+ 聊天页（ai-sdk embedded）。
- 不新增数据库表（token 仅存 Redis）；不改 `message_send` 协议；店铺系统零改动。

### 修订后的剩余风险

- `shopUserId` 伪造：MVP 信任前端传入，实现时优先用店铺 token 调 hua8 用户信息接口校验（接口是否存在待确认）。
- 浏览器→hua8 登录接口跨域（CORS/代理）与 ai-base→hua8 服务端连通性需在联调时验证。
- Embed Client 配置（`EMBED_CLIENT_ID/SECRET/AGENT_ID`）与目标 Agent 绑定需就绪。
