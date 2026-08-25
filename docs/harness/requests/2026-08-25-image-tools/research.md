# 图片生成与读取工具调研

## 调研问题

本需求需要在后端 Agent 内置工具中增加图片生成、图片读取能力，并让 AI SDK 能稳定展示图片。调研重点是 OpenAI Images API 的返回方式、图片资源的持久化策略、现有工具体系的复用边界，以及浏览器在 Bearer 鉴权下加载图片的方式。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及外部模型调用、文件持久化、现有工具执行循环、消息内容块协议和前端鉴权加载，且会影响历史消息恢复。
- 最低调研要求：官方 API/SDK 资料、成熟工具/资源实现、至少两种返回方案比较，并记录安全与缓存风险。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenAI Images API - Create image
- 链接：https://platform.openai.com/docs/api-reference/images/create
- 版本或发布日期：在线文档，调研日期 2026-08-25
- 调研日期：2026-08-25
- 核心做法：图片创建接口接受 prompt、model、n、size、quality 等参数；响应可返回 URL 或 base64 JSON。URL 适合短期展示，base64 适合服务端立即接管数据。
- 对本项目的启发：后端应请求 `b64_json` 并立即写入现有资源存储，避免把上游临时 URL 写入长期消息。

### 来源 2

- 类型：官方 SDK 文档/源码
- 名称：OpenAI Python SDK Images API
- 链接：https://github.com/openai/openai-python/tree/main/src/openai/resources/images
- 版本或发布日期：openai-python 2.x，调研日期 2026-08-25
- 调研日期：2026-08-25
- 核心做法：官方 Python 客户端提供异步 `client.images.generate(...)`，返回对象中的 `data[*].b64_json` 或 `data[*].url` 与 API 响应一致。
- 对本项目的启发：直接使用后端异步客户端，统一超时、异常和配置，不在路由层拼接 HTTP 请求。

### 来源 3

- 类型：成熟开源实现（本仓库已有）
- 名称：`builtin_tool/http_get.py` 与 `asset` 模块
- 链接：仓库内 `apps/backend/app/modules/builtin_tool/http_get.py`、`apps/backend/app/modules/asset/services.py`
- 版本或发布日期：当前主干，调研日期 2026-08-25
- 调研日期：2026-08-25
- 核心做法：公开 URL 校验 DNS/IP 防 SSRF、限制超时和字节数、将文件写入临时目录，再通过 `persist_asset` 关联平台、Agent、会话和主体；资源下载接口继续执行 Bearer 鉴权。
- 对本项目的启发：`image_read` 复用 URL 校验和资源持久化，图片生成也复用同一 asset 生命周期和权限边界，不新增表。

### 来源 4

- 类型：成熟前端实现（本仓库已有）
- 名称：AI SDK `ImageContent.vue` 与 `MessageContentBlock`
- 链接：仓库内 `apps/ai-sdk/src/ui/components/ImageContent.vue`、`apps/ai-sdk/src/core/types.ts`
- 版本或发布日期：当前主干，调研日期 2026-08-25
- 调研日期：2026-08-25
- 核心做法：消息支持 `type=image` 内容块，但当前组件只接受公开 HTTPS URL，且没有处理受保护资源。
- 对本项目的启发：新增 `assetId` 资源加载器，用 AgentClient 的 token 通过 `fetch` 获取 Blob URL；缓存消息只保存 assetId 和后端路径，页面重载后可重新加载。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 返回 OpenAI 临时 URL | 实现少、首屏快 | URL 会过期，历史消息恢复不可靠，外部读取 URL 也可能失效 | 低 |
| 返回 base64/data URL | 不需要图片鉴权请求 | WebSocket、数据库和浏览器内存膨胀，无法复用现有资源权限模型 | 中 |
| 持久化 assetId，SDK 鉴权加载 | 可长期缓存、复用现有权限和清理策略，协议负载小 | SDK 需要新增资源加载器和 Blob URL 生命周期管理 | 高 |

## 最终决策

- 选择方案：后端统一将生成和读取的图片持久化为 `ConversationAsset`，消息内容块保存 `assetId`、受保护下载路径、媒体类型和大小；AI SDK 在展示时带 Bearer token 获取 Blob URL。
- 选择原因：避免 OpenAI 临时 URL 过期；不把凭证放进图片 URL；复用现有资源表、下载权限和会话隔离；前端缓存消息可通过 assetId 在重载后恢复。
- 不选择其他方案的原因：临时 URL 不满足长期缓存；base64 会造成消息和数据库负载不可控。
- 对后续 spec、plan 或人工确认的影响：新增 builtin tool 输入/输出契约、OpenAI 配置项和 SDK 资源加载行为；不新增数据库表，但属于 API 契约与服务边界变更，已获得用户确认。

## 剩余风险

- 资料时效性：OpenAI 图片模型、尺寸和质量枚举可能随 API 更新，需要通过配置和白名单隔离。
- 与本项目上下文的差异：现有 ChatOpenAI 主要用于文本模型，图片 API 需单独客户端和超时配置。
- 尚未验证的假设：部署环境的 OpenAI 网络连通性、资源清理策略、SDK token 刷新回调是否始终可用；实现中需加入明确错误码和测试替身。
