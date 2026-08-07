# 内置 HTTP GET 工具规格

## 目标

- 为已发布 Agent 提供可显式绑定的第一方 `http_get` 工具，使模型能够读取公开 HTTP/HTTPS GET 资源。
- 对 JSON、文本、图片和普通文件提供稳定、可审计、受大小限制的结构化结果。
- 对二进制响应建立平台资源存储和鉴权下载闭环，不向模型上下文写入 Base64。
- 以本 request 建立后续 `web_search`、图片生成等第一方工具可复用的内置工具注册、绑定和执行边界。
- 方案依据 `research.md`：采用代码注册表、Agent 显式绑定、安全流式 GET、媒体类型分流和受控资源存储。

## 调用方与使用边界

- 调用方是后台对话、SSE 对话和 Embed Gateway 中运行的已发布 Agent。
- 工具由模型在对话工具循环中调用，最终用户不能通过新增公共 HTTP API 直接代理任意 URL。
- 管理员必须为指定 Agent 显式启用 `http_get`；未绑定、已停用或跨平台 Agent 不加载该工具。
- 工具绑定归属 Agent，不归属 AgentVersion。Agent 发布或回滚版本不会隐式改变联网权限，管理员停用后下一轮对话立即生效。

## 架构与模块边界

### `builtin_tool`

- 维护代码级工具注册表，工具至少包含稳定名称、中文说明、输入 JSON Schema、副作用等级和执行器标识。
- 持久化 Agent 与工具名称的启用绑定；运行时只装载注册表存在、绑定启用且 Agent 属于当前平台的工具。
- 提供统一执行分发，向 `conversation` 与 `gateway` 返回现有工具循环可消费的 `ToolOutcome`。
- 首个注册工具固定为 `http_get`，副作用等级为 `none`。

### `http_get`

- 只负责 URL 校验、DNS/IP 校验、HTTP GET、逐跳重定向、响应流读取、媒体类型分类和结构化错误映射。
- 不依赖 FastAPI Request/Response，不直接查询 Agent 权限，不直接拼接聊天事件。
- 与现有知识库抓取保持相同安全语义；首期不重构知识库导入链路，避免扩大回归范围。

### `asset`

- 负责二进制临时文件、原子落盘、资源记录、存储键生成、归属校验和鉴权下载。
- 资源必须可追溯到平台、Agent、Conversation 和且仅一个会话主体：后台用户或 Embed 最终用户。
- 下载接口只根据公开资源标识定位资源，不暴露宿主绝对路径和内部 `storage_key`。

### `conversation` 与 `gateway`

- 在 `RuntimeContext` 中增加 `builtin_tools`，并与 Skill、MCP、Host Tool 一起绑定给模型。
- 统一调用入口根据工具 `kind=builtin` 分发到内置工具执行器，保留现有 `tool_started`、`tool_completed`、Agent Loop step 和错误事件语义。
- 后台非流式、后台 SSE、Embed Gateway 三条路径使用相同的授权与执行服务。

## 数据模型

### Agent 内置工具绑定

新增绑定实体，至少包含：

- 主键。
- `platform_id`：所属平台，用于查询和隔离。
- `agent_id`：所属 Agent。
- `tool_name`：代码注册表中的稳定工具名。
- `is_enabled`：是否启用。
- 创建与更新时间。
- `(agent_id, tool_name)` 唯一约束。

数据库不持久化工具描述和输入 Schema，避免代码定义与数据库副本漂移。所有 ORM 字段必须添加中文 `comment`。

### 会话资源

新增资源实体，至少包含：

- 内部主键与不可枚举的公开 `asset_id`。
- `platform_id`、`agent_id`、`conversation_id`。
- `user_id` 与 `platform_end_user_id`，数据库约束保证且仅一个非空。
- `storage_key`，只保存相对存储键。
- 安全化后的 `filename`、受控 `content_type`、`size_bytes`。
- `source_url` 的脱敏形式，不保存查询参数和片段。
- 创建时间。

所有 ORM 字段必须添加中文 `comment`。删除会话时资源记录级联删除；物理文件清理失败记录日志，不影响数据库事务完成。跨数据库与文件系统无法建立原子事务，实施计划需明确补偿清理顺序。

## 管理与下载 API

新增以下 API 契约：

- `GET /api/v1/platforms/{platform_id}/builtin-tools`：返回代码注册表中的工具目录，不返回秘密配置。
- `GET /api/v1/platforms/{platform_id}/agents/{agent_id}/builtin-tools`：返回指定 Agent 的工具绑定状态。
- `PUT /api/v1/platforms/{platform_id}/agents/{agent_id}/builtin-tools/{tool_name}`：请求体为 `{ "is_enabled": true | false }`，创建或更新绑定。
- `GET /api/v1/assets/{asset_id}`：鉴权下载资源。后台用户使用现有用户 JWT；Embed 最终用户使用现有 Embed 身份，且主体、平台和会话必须匹配。

管理 API 仅允许所属平台管理员调用。资源接口返回 `Content-Disposition: attachment` 与 `X-Content-Type-Options: nosniff`，不提供目录列表、内部路径或匿名访问。

## 工具契约

### 输入

工具名为 `http_get`，首期输入仅包含：

```json
{
  "url": "https://example.com/data"
}
```

- `url` 必填，最大 2048 字符。
- 不接受自定义 Header、Cookie、Token、Basic Auth、请求体、请求方法或独立查询参数对象。
- URL 可以自带公开查询参数，但日志与资源记录不得保存查询参数原文。

### 成功结果

所有成功结果包含：

```json
{
  "kind": "json | text | image | file",
  "status_code": 200,
  "content_type": "application/json",
  "final_url": "https://example.com/data",
  "size_bytes": 1024,
  "truncated": false,
  "content": null,
  "asset": null
}
```

- `application/json` 与带 `+json` 后缀的媒体类型解析后通过 `content` 返回 JSON 值。
- `text/*` 及明确允许的文本媒体类型通过 `content` 返回字符串。
- JSON 解码失败时降级为 `text`，保留远端 `content_type`，`kind` 返回 `text`。
- 图片和其他二进制响应通过 `asset` 返回 `asset_id`、文件名、受控媒体类型、大小和下载 API 路径；`content` 为 `null`。
- 未知或不可信媒体类型保存为 `application/octet-stream`，`kind` 返回 `file`。
- `final_url` 只返回协议、主机、端口和路径，移除查询参数、片段及用户信息。

### 稳定错误

- `invalid_url`
- `target_not_public`
- `invalid_redirect`
- `too_many_redirects`
- `request_timeout`
- `response_too_large`
- `unsupported_content_encoding`
- `upstream_http_error`
- `storage_failed`

错误结果不得包含堆栈、内部路径、DNS 详情、响应正文或秘密配置。远端非 2xx 状态映射为 `upstream_http_error`，可返回状态码但不保存和不回传响应体。

## 网络与内容安全

- 仅允许 `http` 和 `https`，拒绝 URL 中的用户名、密码、缺失主机、非标准编码主机和不受支持协议。
- 初始目标及每次重定向目标都解析全部 IPv4/IPv6 地址；任一地址不是公网全局地址则拒绝请求。
- HTTP 客户端关闭自动重定向，最多人工处理 3 次重定向；缺失或非法 `Location` 返回 `invalid_redirect`。
- 整个工具调用的总时间预算为 30 秒，覆盖 DNS、全部重定向、响应读取和文件写入；HTTP 客户端还需为连接、读取、写入和连接池分别设置不超过总预算的阶段超时。
- 文本与 JSON 最多读取 1 MiB，最多向模型返回 100,000 个字符；字符截断时 `truncated=true`。
- 图片和普通文件最多读取 25 MiB。无 `Content-Length` 时仍按实际流式字节累计；超过上限立即中止并删除临时文件。
- 响应解压后的字节数必须受同一上限约束，防止压缩炸弹绕过 `Content-Length`。
- 文件名只能来自安全化后的 `Content-Disposition` 或最终 URL 末段；缺失或非法时生成随机名称。
- 日志只记录脱敏后的域名、状态、内容类型、字节数、耗时和错误码，不记录 URL 查询参数、响应正文或文件内容。
- 生产部署必须通过网络出口策略阻止访问私网、链路本地和云元数据网段；应用层校验不能替代网络层纵深防御。

## 文件写入与失败处理

- 二进制先写入存储根目录内的随机临时文件，写入完成并校验大小后再原子移动到最终 `storage_key`。
- 只有物理文件落盘成功后才创建资源记录；数据库写入失败时执行补偿删除。
- 超时、取消、客户端断开、上游错误、大小超限和写入异常均关闭响应流并清理临时文件。
- 同一工具调用不会自动重试 GET，避免重复下载和增加外部请求压力；模型可以在后续轮次主动决定是否重试。

## 非目标

- 不实现 `web_search`、网页正文抽取、爬虫、站点地图或缓存。
- 不支持 POST、PUT、PATCH、DELETE、自定义 Header、认证信息或私有 API 连接器。
- 不允许匿名下载、内联浏览器预览或直接暴露存储路径。
- 不做恶意文件扫描、文档解析、图片理解、文件进入知识库或资源生命周期清理。
- 不重构现有知识库 URL 导入实现；可复用的安全 HTTP 底层在后续 request 统一。
- 不增加平台级域名允许列表；高敏感部署仍需网络出口策略。

## 风险

- 架构风险：新增第一方工具注册/执行边界和通用资源模块，运行时工具类型增加。
- 数据风险：新增 Agent 工具绑定与会话资源表；文件系统和数据库需要补偿式一致性处理。
- API 风险：新增管理和下载 API，前端及 Embed SDK 需要按鉴权方式下载文件。
- 权限风险：启用绑定后 Agent 获得外网读取能力；跨平台、跨用户或跨会话资源泄露必须由服务端拒绝。
- 安全风险：应用层 DNS 校验存在连接前时间窗口，需要生产网络出口策略补强；首期资源不做恶意内容扫描。
- 存储风险：首期未实现资源过期清理，需要监控存储增长并在后续补充生命周期策略。

## 停点判断与确认记录

- 架构边界变化：是，新增 `builtin_tool` 和 `asset` 模块并扩展 Agent Runtime。
- 数据模型变化：是，新增 Agent 内置工具绑定和会话资源实体。
- API 契约变化：是，新增工具管理与资源下载 API。
- 鉴权或权限行为变化：是，新增 Agent 外网读取授权和会话资源下载授权。
- 人工确认：用户于 2026-08-07 逐段确认推荐方案、架构、工具契约、错误行为与验证范围；请求超时由最初建议的 15 秒调整为 30 秒。正式规格仍需用户审阅确认后才能进入实施计划。

## 验收标准

### 工具注册与授权

- 管理员可以查看内置工具目录并按本平台 Agent 启停 `http_get`。
- 未绑定、已停用、未发布或跨平台 Agent 不加载和不能直接调用 `http_get`。
- Agent 发布或回滚版本不改变绑定，停用在下一轮对话生效。

### HTTP 行为

- 公开 JSON、文本、图片和普通文件分别返回符合契约的 `json`、`text`、`image` 和 `file` 结果。
- 工具仅发送无认证信息的 GET；30 秒总预算、最多 3 次重定向、1 MiB 文本/JSON 和 25 MiB 文件上限生效。
- 无 `Content-Length`、压缩后膨胀、分块传输和字符截断场景均不能绕过限制。
- 404、500、超时、非法编码和存储失败返回稳定错误且不暴露响应体或内部异常。

### SSRF 与文件安全

- 回环、私网、链路本地、云元数据、非 HTTP 协议、URL 凭证、解析到任一非公网 IPv4/IPv6 的主机均被拒绝。
- 公开目标重定向到禁止目标时，在发起下一跳请求前被拒绝。
- 文件名经过安全化，未知类型强制为 `application/octet-stream`；下载响应强制 `attachment` 和 `nosniff`。
- 失败、超时、取消和超限不残留临时文件或孤立资源记录。

### 资源隔离

- 资源记录可追溯到平台、Agent、会话和唯一会话主体。
- 后台用户、Embed 最终用户、平台、Agent 或会话不匹配时，下载返回稳定权限错误。
- API、模型工具结果和日志均不暴露内部路径，日志不记录 URL 查询参数与内容原文。

### 工具调用链与工程验证

- 后台非流式、后台 SSE 和 Embed Gateway 均能执行内置工具，并保持现有工具开始、完成、失败和 Agent Loop 事件语义。
- MCP、Skill Script、Skill Instruction 和 Host Tool 的现有行为不回归。
- 数据库迁移、模型约束、服务测试、路由测试、运行时测试、Ruff、Black 和相关回归测试通过。
- `verify.md` 记录真实命令、输出、失败项和生产网络出口未在单元测试中覆盖的剩余风险。

## 变更记录

### 2026-08-07 初始版本

- 变更原因：为后端 Agent 建立首个第一方基础网络工具。
- 变更内容：定义 `http_get` 的注册绑定、安全 GET、媒体类型分流、资源存储、下载权限、错误语义和验证边界。
- 影响章节：全部。
- 是否触发人工确认：是，涉及架构、数据模型、API 和权限行为变化。
