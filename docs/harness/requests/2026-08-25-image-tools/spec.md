# 图片生成与读取工具规格

## 目标

为 Agent 增加 `image_generate` 和 `image_read` 两个内置工具。工具结果持久化到现有会话资源，最终助手消息通过 `image` 内容块交给 AI SDK 展示，并支持前端缓存消息在页面重载后重新加载图片。

## 范围

### 包含

- 后端读取 OpenAI Images API 配置并调用异步图片生成接口。
- `image_generate`：根据提示词生成一张或多张图片。
- `image_read`：读取公开 HTTPS 图片 URL，或读取当前会话已有 `asset_id`。
- 生成/读取图片统一持久化到 `ConversationAsset`。
- 图片工具结果转换为消息 `content_blocks`，不改变文本消息行为。
- AI SDK 对受保护图片资源进行带 token 的 Blob 加载、缓存和释放。
- builtin tool catalog、Agent 绑定、运行时执行和相关测试。

### 不包含

- 图片编辑、局部重绘、批量任务队列。
- 新增数据库表或修改 `ConversationAsset` 表结构。
- 浏览器端直接调用 OpenAI API。
- 图片永久公开 URL；资源仍受现有主体和会话权限约束。

## API/工具契约

### `image_generate`

输入 JSON：

```json
{
  "prompt": "一只戴红围巾的猫",
  "model": "gpt-image-1",
  "size": "1024x1024",
  "quality": "auto",
  "n": 1
}
```

除 `prompt` 外字段可选；后端对白名单校验模型、尺寸、质量和数量，并使用配置默认值。输出包含 `kind: image`、生成数量和每张图片的 `asset` 信息。

### `image_read`

输入必须且只能提供 `url` 或 `asset_id`：

```json
{"url": "https://example.com/image.png"}
```

公开 URL 经过现有 SSRF 防护、重定向、媒体类型和大小限制；asset_id 只允许读取当前会话和主体可见的图片资源。输出格式与 `image_generate` 相同。

### 消息内容块

每个图片资产转换为：

```json
{
  "id": "image_<asset_id>",
  "type": "image",
  "status": "completed",
  "assetId": "<asset_id>",
  "url": "/api/v1/assets/<asset_id>",
  "mimeType": "image/png",
  "size": 12345,
  "alt": "生成图片"
}
```

## 数据流

1. Agent 模型选择 builtin tool。
2. 后端执行器校验参数和 Agent 绑定。
3. 生成工具从 OpenAI 收到 base64，读取工具从公开 URL 或既有 asset 取得字节。
4. 字节写入临时目录，经 `persist_asset` 关联当前平台、Agent、会话和主体。
5. 运行时从工具结果收集图片资产，和 Markdown 文本块一起保存并通过 REST/SSE/WebSocket 的 `message_completed` 下发。
6. SDK 收到图片块后，若为外部 URL 直接展示；若为 assetId，则通过 AgentClient token 获取 Blob URL，失败时展示稳定 fallback。

## 错误与安全

- 未配置 `OPENAI_API_KEY`：`image_generation_not_configured`。
- 上游超时、拒绝或响应格式异常：`image_generation_failed`，不返回异常原文。
- 图片超过配置上限：`image_too_large`。
- asset 不存在、不是图片或不属于当前会话主体：`asset_not_found`。
- 所有图片输出使用现有 asset 权限；OpenAI key 只在后端配置层读取。

## 配置

- `OPENAI_API_KEY`：必填密钥。
- `OPENAI_BASE_URL`：可选兼容网关地址。
- `OPENAI_IMAGE_MODEL`：默认 `gpt-image-1`。
- `IMAGE_GENERATION_TIMEOUT_SECONDS`、`IMAGE_MAX_BYTES`、`IMAGE_MAX_COUNT`：资源和调用限制。

## 验收标准

- builtin catalog 能列出两个工具，Agent 可启用/禁用。
- `image_generate` 在替身 OpenAI 客户端下能持久化图片并返回 asset 元数据。
- `image_read` 能拒绝非法 URL、读取图片并持久化；不能越权读取其他会话资源。
- 工具结果最终产生可渲染 `image` 内容块，REST、SSE、WebSocket 字段一致。
- AI SDK 能展示外部图片和受保护 asset 图片；页面重载后缓存消息可重新加载。
- OpenAI 未配置、上游失败、超限和资源不存在均返回稳定错误码。

## 风险与停点判断

- 本次不改数据模型，但新增 builtin tool 和消息内容块使用约定，属于 API 契约变化。
- 本次不改变登录校验语义；图片请求继续使用现有 Bearer token。
- 用户已确认采用 OpenAI Images API、持久化 assetId 和 SDK 鉴权加载方案，可进入实现。

## 变更记录

### 2026-08-25 第 1 次变更

- 变更原因：新增图片生成、读取和 AI SDK 展示需求。
- 变更内容：增加两个 builtin tool、OpenAI 配置、图片内容块和受保护资源加载。
- 影响章节：范围、API/工具契约、数据流、错误与安全、验收标准。
- 是否触发人工确认：是，用户已确认方案。
- 关联计划更新：同步写入 `plan.md`。

### 2026-08-25 第 2 次变更（缺陷修复）

- 变更原因：图片生成失败结果中的 `error` 为嵌套对象，触发运行时预算判断的类型异常并覆盖真实错误。
- 变更内容：预算错误码判断安全提取嵌套 `error.code`，仅对字符串值进行匹配，并增加回归测试。
- 同步补充：图片生成对外保持稳定错误码，对 OpenAI 上游异常和响应格式异常写入后端日志（不记录提示词或密钥）。
- 影响章节：错误与安全、验收标准。
- 是否触发人工确认：否，属于原 API 契约内的兼容性缺陷修复。
