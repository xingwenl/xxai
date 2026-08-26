# AI SDK 文件附件与会话缓存实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AI SDK 增加当前会话范围内的文件上传、解析、切块缓存和多供应商附件适配能力。

**Architecture:** SDK 通过上传接口获得 `assetId`，消息只携带附件引用；后端用受权限保护的 `ConversationAsset` 保存原文件，用异步 Worker 生成解析结果和 chunks，provider adapter 按能力选择图片/原生文件/文本检索输入。第二期复用现有 pgvector 保存会话级 chunk embedding。

**Tech Stack:** Vue/TypeScript AI SDK、FastAPI、Pydantic、SQLAlchemy/Alembic、Celery Worker、LlamaIndex file readers、PostgreSQL pgvector、现有 WebSocket/SSE 协议。

## 增量计划：独立 HTTP `baseUrl`

1. 在 `AgentClientOptions` 暴露可选 `baseUrl`，并集中由 `_httpBaseUrl` 读取；显式值优先，缺省时从 `endpoint` 推导以保持兼容。
2. 让 `loadAsset`、`uploadAsset`、`getAssetStatus`、`deleteAsset` 统一使用该根路径，移除调试输出并规范尾部斜杠处理，避免 URL 拼接产生双斜杠或路径串接。
3. 更新 README、Demo 初始化示例，明确 `endpoint` 仅用于 WebSocket，`baseUrl` 用于 HTTP API。
4. 增加 SDK 单测，覆盖显式 `baseUrl` 和缺省推导两种情况，验证请求地址不包含 `/ws/agents/...`。

本增量涉及 SDK 公共 API 契约，进入实现前需人工确认；不涉及后端数据模型、权限或路由变更。

---

## 变更文件地图

- `apps/ai-sdk/src/core/types.ts`、`client.ts`：附件类型、上传状态和 `sendMessage` 协议。
- `apps/ai-sdk/src/ui/components/ChatWidget.vue` 及输入框组件/样式：附件选择、预览、进度和删除。
- `apps/backend/app/modules/asset/`：上传、状态查询、会话权限和文件生命周期。
- `apps/backend/app/modules/conversation/`：消息附件 schema、当前会话 asset 校验和上下文组装。
- `apps/backend/app/modules/asset_processing/`：解析、切块、状态机和 Worker 任务（必要时按现有模块命名模式落位）。
- `apps/backend/app/modules/agent/`：OpenAI-compatible、Qwen、DeepSeek 的附件能力矩阵和输入转换。
- `apps/backend/app/modules/knowledge/`：第二期复用 embedding 构建和 pgvector 检索。
- `apps/backend/migrations/versions/`：处理记录、chunk、embedding 表迁移；每个字段补中文 comment。
- `apps/ai-sdk/src/**/__tests__`、`apps/backend/tests/`：协议、权限、状态机、缓存和 provider 回归测试。

## Phase 1: 上传和缓存解析结果

### Task 1: 先写协议与状态机测试

**Files:**
- Create: `apps/backend/tests/asset/test_asset_processing.py`
- Modify: `apps/backend/tests/gateway/test_connection.py`
- Create: `apps/ai-sdk/src/core/__tests__/attachments.test.ts`

- [ ] Step 1: 添加上传成功、非法 MIME、超限、跨会话 asset、重复引用 ready asset 的失败测试。
- [ ] Step 2: 添加 `message_send.attachments` 序列化和缺失附件字段校验测试。
- [ ] Step 3: 运行 `poetry run pytest tests/asset/test_asset_processing.py tests/gateway/test_connection.py -q`，确认新断言在实现前失败。
- [ ] Step 4: 运行 `pnpm --dir apps/ai-sdk test -- attachments.test.ts`，确认 SDK 新测试失败。

### Task 2: 扩展 asset 上传和处理数据模型

**Files:**
- Modify: `apps/backend/app/modules/asset/models.py`
- Create: `apps/backend/app/modules/asset_processing/models.py`
- Create: `apps/backend/migrations/versions/20260825_0025_conversation_asset_processing.py`
- Modify: `apps/backend/migrations/env.py`

- [ ] Step 1: 为处理记录、chunk 和 embedding 定义字段、索引、级联关系，并为每个字段设置中文 `comment`。
- [ ] Step 2: 增加 `conversation_id`、`asset_id`、处理版本和状态的唯一约束，确保同一 asset/版本不会重复处理。
- [ ] Step 3: 生成 Alembic migration，升级和降级均可执行。
- [ ] Step 4: 运行 `poetry run pytest tests/builtin_tool/test_models.py tests/asset/test_asset_processing.py -q`，确认模型字段 comment 和约束通过。

### Task 3: 实现上传、状态查询和删除接口

**Files:**
- Modify: `apps/backend/app/modules/asset/router.py`
- Create: `apps/backend/app/modules/asset/schemas.py`
- Create: `apps/backend/app/modules/asset_processing/repositories.py`
- Create: `apps/backend/app/modules/asset_processing/services.py`

- [ ] Step 1: 实现 `POST /embed/conversations/{conversation_id}/assets`，执行主体、会话、MIME、扩展名、大小和文件名校验。
- [ ] Step 2: 创建 `ConversationAsset` 与 processing 记录，提交异步任务后返回 `processing`。
- [ ] Step 3: 实现状态查询和删除接口，删除时验证当前会话并清理派生文件、chunks、向量和原文件。
- [ ] Step 4: 为预期错误返回稳定错误码，不暴露内部异常堆栈或存储路径。
- [ ] Step 5: 运行 `poetry run pytest tests/asset -q`，预期全部通过。

### Task 4: 实现解析与切块 Worker

**Files:**
- Create: `apps/backend/app/modules/asset_processing/runtime.py`
- Create: `apps/backend/app/modules/asset_processing/tasks.py`
- Modify: `apps/backend/app/modules/knowledge/runtime.py`
- Modify: `apps/backend/app/core/config.py`

- [ ] Step 1: 复用 `SimpleDirectoryReader` 读取 TXT、Markdown、PDF、DOCX，统一输出规范化文本。
- [ ] Step 2: 使用 `SentenceSplitter` 按配置生成 chunks，保存序号、页码/定位信息和 token 数量。
- [ ] Step 3: 对图片只保存原文件并写入 `ready`；OCR 未配置时记录可读的 `ocr_not_configured` 状态，不阻塞图片发送。
- [ ] Step 4: 使用内容 hash、解析器版本、chunk 参数生成处理版本，命中同版本缓存时直接返回。
- [ ] Step 5: 对超限、解析失败和不支持类型更新状态并支持显式重试。
- [ ] Step 6: 运行 `poetry run pytest tests/asset/test_asset_processing.py tests/knowledge -q`，预期解析、切块、缓存命中和失败重试通过。

### Task 5: 扩展 AI SDK 输入框和消息协议

**Files:**
- Modify: `apps/ai-sdk/src/core/types.ts`
- Modify: `apps/ai-sdk/src/core/client.ts`
- Modify: `apps/ai-sdk/src/ui/components/ChatWidget.vue`
- Modify: `apps/ai-sdk/src/ui/styles/index.css`
- Create or modify: `apps/ai-sdk/src/ui/components/AttachmentList.vue`

- [ ] Step 1: 添加 `AttachmentRef`、`AttachmentUploadState` 和 `sendMessage(text, options)` 类型，保持 `sendMessage(text)` 向后兼容。
- [ ] Step 2: 添加 multipart 上传客户端，使用现有 token 获取方式，支持取消、进度和错误码。
- [ ] Step 3: 在输入框加入图片缩略图、文档卡片、状态徽标、移除按钮、拖拽和粘贴图片处理。
- [ ] Step 4: 仅在附件上传完成后把 `assetId` 写入 `message_send`；处理状态由事件或轮询更新。
- [ ] Step 5: 运行 `pnpm --dir apps/ai-sdk test -- attachments.test.ts`、`pnpm --dir apps/ai-sdk typecheck` 和 `pnpm --dir apps/ai-sdk build`。

### Task 6: 扩展网关和会话运行时的附件校验

**Files:**
- Modify: `apps/backend/app/modules/gateway/connection.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Modify: `apps/backend/app/modules/gateway/schemas.py`
- Modify: `apps/backend/app/modules/conversation/schemas.py`
- Modify: `apps/backend/app/modules/conversation/runtime.py`

- [ ] Step 1: 在协议 schema 中定义附件引用，限制最多附件数、字段长度和 assetId 格式。
- [ ] Step 2: 网关按当前 principal 和 conversation 查询 asset，拒绝跨会话或未 ready 资源。
- [ ] Step 3: 把图片块和文档 chunk 引用传给模型适配层，避免把原始二进制写入消息历史。
- [ ] Step 4: 统一 REST、SSE、WebSocket 的稳定错误 payload 和处理状态事件。
- [ ] Step 5: 运行 `poetry run pytest tests/gateway tests/conversation -q` 和 `poetry run ruff check app tests`。

## Phase 2: Provider 适配和向量检索

### Task 7: 实现 provider 能力矩阵

**Files:**
- Create: `apps/backend/app/modules/attachment/provider.py`
- Modify: `apps/backend/app/modules/agent/services.py`
- Modify: `apps/backend/app/modules/conversation/runtime.py`
- Create: `apps/backend/tests/attachment/test_provider_adapters.py`

- [ ] Step 1: 定义 `ProviderAttachmentCapabilities`，至少包含 image、native_file、text_retrieval 三项能力。
- [ ] Step 2: OpenAI-compatible 视觉模型转换为 image URL/file input；不支持原生文件时返回文本 chunks。
- [ ] Step 3: Qwen-VL 转换为其图片消息格式；普通 Qwen 使用 chunks。
- [ ] Step 4: DeepSeek 默认使用 chunks；图片无视觉描述时返回 `model_attachment_not_supported`。
- [ ] Step 5: 添加能力矩阵和降级路径单测，运行 `poetry run pytest tests/attachment -q`。

### Task 8: 接入 embedding 和会话级 pgvector 缓存

**Files:**
- Modify: `apps/backend/app/modules/asset_processing/tasks.py`
- Modify: `apps/backend/app/modules/knowledge/runtime.py`
- Modify: `apps/backend/app/modules/knowledge/repositories.py`
- Modify: `apps/backend/app/modules/conversation/services.py`
- Create: `apps/backend/migrations/versions/20260825_0026_conversation_asset_embeddings.py`

- [ ] Step 1: 复用 `build_embedding_model`，从配置读取 provider、model、base URL、API key 和 dimension。
- [ ] Step 2: 以 chunk 处理版本和 embedding 配置生成唯一键，批量生成并持久化向量。
- [ ] Step 3: 查询时强制过滤 `conversation_id`、主体和 active processing version，再执行 cosine distance。
- [ ] Step 4: 将 Top-K chunks 以明确的文件上下文注入模型，并返回页码/定位引用。
- [ ] Step 5: 添加向量命中、配置变更重算、维度不匹配和会话隔离测试，运行 `poetry run pytest tests/knowledge tests/conversation -q`。

## Phase 3: 验证和验收

### Task 9: 完成端到端验证记录

**Files:**
- Modify: `docs/harness/requests/2026-08-25-ai-sdk-file-attachments/verify.md`
- Modify: `docs/harness/requests/2026-08-25-ai-sdk-file-attachments/acceptance.md`
- Modify: `docs/harness/requests/2026-08-25-ai-sdk-file-attachments/meta.json`

- [ ] Step 1: 执行后端目标测试、ruff、Alembic migration 检查和 SDK typecheck/build。
- [ ] Step 2: 在本地配置模型的环境中验证图片、PDF、DOCX、DeepSeek 降级和同会话缓存命中。
- [ ] Step 3: 记录真实命令、结果、失败项和未解决的 OCR/供应商联调风险。
- [ ] Step 4: 对照 spec 验收标准逐条填写 acceptance，并把 meta phase 更新为 `acceptance`。

## 测试步骤

- `poetry run pytest tests/asset tests/attachment tests/conversation tests/gateway tests/knowledge -q`
- `poetry run ruff check app tests`
- `poetry run alembic upgrade head`
- `pnpm --dir apps/ai-sdk test`
- `pnpm --dir apps/ai-sdk typecheck`
- `pnpm --dir apps/ai-sdk build`

预期结果：目标测试通过，迁移可升级，SDK 类型检查和生产构建通过；真实供应商联调至少覆盖一个 OpenAI-compatible 视觉模型、一个 Qwen-VL 模型和 DeepSeek 文本降级。

## 回滚说明

先停止新上传入口和 Worker，再回滚应用代码；数据库迁移仅在确认没有新资产或已完成数据清理后执行 downgrade。历史 `ConversationAsset` 图片资源和旧消息协议必须保持可读，删除新表不能影响既有图片展示。

## 人工确认点

- 已确认：仅当前会话复用、允许分期、覆盖 OpenAI-compatible/Qwen/DeepSeek。
- 实现前仍需确认：OCR 服务选择、embedding 默认模型/维度、文件大小与保留时长、是否允许发送 `processing` 附件、生产 Worker 队列和存储挂载配置。
