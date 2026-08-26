# AI SDK 文件附件与会话缓存规格

## 目标

为 AI SDK 增加图片和文档附件能力。用户上传文件后，系统在当前会话内保存原文件、解析结果和切块；后续消息可以直接引用已处理内容。图片对支持视觉的模型保留原生输入，文档在模型不支持原生文件时使用解析文本或向量检索结果。

关键调研结论见 `research.md`：采用原文件、派生文本、chunks、可版本化 embedding 的分层方案，复用现有 `ConversationAsset`、`llama-index-readers-file` 和 pgvector，不引入独立向量数据库。

## 范围

- AI SDK 输入框支持图片、PDF、DOCX、XLSX、TXT、Markdown 附件。
- 上传接口返回 `assetId` 和处理状态；SDK 发送文本及附件引用，不发送 Base64 文件内容。
- 附件只允许当前会话和当前主体访问，不跨会话共享。
- 后端异步执行文件解析、切块和缓存；处理状态可查询并可通过实时事件通知。
- 图片保存原文件并生成 `image` 内容块；OpenAI-compatible 和 Qwen-VL adapter 可转换为原生图片输入。
- 文档默认抽取为文本/Markdown；模型支持原生文件输入时由 adapter 选择原文件，否则使用 chunks。
- 第二期接入可配置 embedding 和 pgvector 检索，embedding 记录模型、维度和版本。
- 增加稳定错误码、大小/MIME/数量限制、失败重试和会话级清理策略。

## 非目标

- 不做跨会话、跨用户或跨 Agent 文件复用。
- 不在第一期实现完整的文档管理后台、知识库导入 UI 或永久文件中心。
- 不强制 DeepSeek 支持图片；DeepSeek 默认使用文本解析结果，视觉描述作为后续能力。
- 不把 `text-embedding-v3` 写死为唯一 embedding；具体模型由配置决定。
- 不在第一期实现复杂表格计算、Office 原样渲染、视频和音频理解。

## 输入与交互

输入框包含附件按钮、拖拽区和粘贴图片入口。附件列表显示缩略图/文件图标、文件名、大小、上传进度、解析状态和删除操作。存在 `processing` 附件时允许保存草稿但禁止发送依赖该附件的消息；用户可以移除失败附件后发送纯文本。

SDK 发送协议：

```json
{
  "type": "message_send",
  "payload": {
    "text": "请总结附件",
    "attachments": [
      {
        "assetId": "asset_xxx",
        "filename": "report.pdf",
        "mimeType": "application/pdf",
        "size": 238912
      }
    ]
  }
}
```

后端必须重新查询并校验 asset，不能信任客户端传来的文件名、状态、权限或解析内容。

## 后端接口

```text
POST /embed/conversations/{conversation_id}/assets
GET  /embed/conversations/{conversation_id}/assets/{asset_id}
DELETE /embed/conversations/{conversation_id}/assets/{asset_id}
```

上传响应至少包含：`assetId`、`filename`、`mimeType`、`size`、`status`、`createdAt`。状态包括 `uploaded`、`processing`、`ready`、`failed`、`unsupported`。

消息请求中的 `attachments` 每项只允许引用当前会话 asset。资产尚未 ready 时，返回 `asset_not_ready`；处理失败时返回 `asset_processing_failed`；模型不支持附件时返回 `model_attachment_not_supported`，并保留可重试语义。

## 数据模型

现有 `ConversationAsset` 保留原始文件和下载权限。新增或扩展以下实体，所有 SQLAlchemy 字段必须添加中文 `comment`：

- `ConversationAssetProcessing`：asset、解析器名称/版本、状态、抽取文本存储键、错误信息、开始/完成时间。
- `ConversationAssetChunk`：asset、处理版本、序号、文本、页码/定位信息、token 数量。
- `ConversationAssetEmbedding`：chunk、embedding provider、模型、维度、版本、向量。

每个实体都必须带 `conversation_id` 或通过 asset 可严格回溯到会话。查询必须同时过滤 `conversation_id`、主体和 asset_id。处理版本由文件内容 hash、parser 版本、chunk size/overlap、OCR 配置组成；embedding 版本额外包含 provider、model、dimension。

## 处理与模型数据流

1. SDK 上传文件，后端校验大小、MIME、扩展名和会话权限，写入受控存储。
2. 后端创建处理记录并投递异步任务，立即返回 `processing`。
3. Worker 解析文本、PDF、DOCX 或 Markdown，生成规范化文本和 chunks；图片只保存原图，OCR/视觉描述按能力配置执行。
4. 第二期 Worker 按 embedding 配置批量生成向量并写入 pgvector。
5. 消息发送时，后端加载当前会话可见附件；图片交给视觉 adapter，文档优先原生 file input，失败或不支持时检索/注入 chunks。
6. 模型上下文明确标记文件内容为不可信外部内容，避免把文档中的指令当作系统指令。

## 风险

- 大文件、OCR 和 embedding 会增加任务延迟、成本和存储占用。
- 解析文本可能包含提示词注入；必须隔离为用户内容并限制可影响的工具权限。
- 不同供应商和具体模型能力不同，不能只按 provider 名称判断。
- 删除会话时必须级联删除派生文本、chunks、向量和原文件。
- 修改解析器、chunk 或 embedding 配置后必须生成新版本，禁止混用旧向量。

## 停点判断

- 架构边界变化：是，新增文件处理 Worker 与 provider adapter 责任边界。
- 数据模型变化：是，新增处理、chunk、embedding 实体或字段。
- API 契约变化：是，新增上传/状态接口并扩展 `message_send.attachments`。
- 鉴权或权限行为变化：是，新增当前会话 asset 的访问校验。
- 进入实现前需人工确认：已于 2026-08-25 确认，范围为当前会话复用、分期实现、OpenAI-compatible/Qwen/DeepSeek 适配。

## 验收标准

- SDK 可以上传图片和指定文档类型，并展示进度、状态、失败和删除操作。
- `message_send` 可携带附件引用；后端拒绝不存在、未完成或不属于当前会话的 asset。
- 同一会话第二次引用 ready 文件时，不重复执行解析和切块。
- 图片在支持视觉的 OpenAI-compatible/Qwen 模型中按图片内容块传递；DeepSeek 返回明确不支持或使用文本描述兜底。
- 文档解析结果、chunks 和处理版本可查询；第二期向量包含模型和维度信息。
- 删除会话或附件后，原文件和派生缓存不再可访问。
- 后端测试覆盖权限隔离、状态机、缓存命中、失败重试和 provider 降级；SDK 测试覆盖上传状态、协议序列化和输入框交互。

## 变更记录

### 2026-08-26 第 10 次变更（增量）

- 变更原因：Phase 1 实现把 PDF、DOCX、XLSX 统一交给 `SimpleDirectoryReader` 解析，但后端运行环境缺少 Word/Excel 的底层解析库，导致这两种格式解析必然失败。
- 变更内容：新增运行时依赖 `docx2txt`（DOCX）与 `openpyxl`（XLSX，多 sheet 内容全部抽取）；PDF 依赖 `pypdf` 已存在；新增 `tests/asset/test_load_file_text.py`，用真实 PDF/DOCX/XLSX 样例断言 `load_file_text` 能抽取文本。Excel 支持属于原规格"文档默认抽取为文本"的既有目标，本次补齐实现与验证。
- 影响章节：范围、处理与模型数据流、验收标准。
- 是否触发人工确认：否，不改变 API 契约、数据模型或权限规则，仅补齐既有解析路径的运行依赖与测试。
- 关联计划更新：落实 Phase 1 Task 4 的文档解析步骤（TXT、Markdown、PDF、DOCX 与 Excel 统一解析）。

### 2026-08-26 第 9 次变更（fix）

- 变更原因：提交前全量验证发现两个实现缺陷：`app/__init__.py` 的 `conversation_router` 导入遮蔽导致 `/agents` 聊天路由未注册且 asset 路由重复注册；SDK `_httpBaseUrl` 在显式 `baseUrl` 后重复追加 `/api/v1` 产生双前缀地址。
- 变更内容：后端改用 `asset_conversation_router` / `asset_upload_router` 别名注册新路由，恢复原 conversation 路由注册；SDK 直接使用完整 `baseUrl` 根路径并移除调试输出。
- 影响章节：后端接口、SDK 初始化参数、验收标准。
- 是否触发人工确认：否，均为实现层面的缺陷修复，不改变 API 契约、数据模型或权限规则。
- 关联计划更新：落实 Phase 1 Task 5 与 Task 6 的提交前校验。

### 2026-08-26 第 8 次变更（fix）

- 变更原因：发送后的用户消息虽然包含图片内容块，但受保护资源的即时下载失败会被组件吞掉，导致聊天内容中看不到已发送图片。
- 变更内容：图片附件在当前页面优先使用本地 Blob 预览地址即时显示，预览失效时回退到携带 Embed token 的资源下载；本地预览地址不发送到后端协议。
- 影响章节：输入与交互、验收标准。
- 是否触发人工确认：否，属于现有消息图片展示的局部修复，不改变 API、数据模型或权限规则。
- 关联计划更新：落实 Phase 1 Task 5 的图片缩略图与消息展示要求。

### 2026-08-26 第 7 次变更（fix）

- 变更原因：首次上传自动创建会话后，只更新了 `AgentClient` 的会话 ID，没有同步 WebSocket transport，导致紧接着发送的图文消息进入另一新会话并返回 `attachment_not_found`。
- 变更内容：上传响应或服务端事件确定会话 ID 时，同时同步 Client、WebSocket transport 和本地持久化状态。
- 影响章节：输入与交互、处理与模型数据流、验收标准。
- 是否触发人工确认：否，属于同一 SDK 内部会话状态同步缺陷，不改变 API、数据模型或权限规则。
- 关联计划更新：落实 Phase 1 Task 5 的首次上传与消息发送会话一致性。

### 2026-08-26 第 6 次变更（fix）

- 变更原因：部分 OpenAI-compatible 模型仅接受文本内容，收到 `image_url` 后返回 `messages.content.type` 非法并中断消息流。
- 变更内容：视觉输入被上游明确以“仅支持 text”错误拒绝时，自动使用同一条文字消息重试一次；支持视觉的模型仍保留原生图片输入。
- 影响章节：处理与模型数据流、风险、验收标准。
- 是否触发人工确认：否，属于既有 provider 降级要求的错误兼容，不改变协议、数据模型或权限规则。
- 关联计划更新：落实 Phase 2 Task 7 的非视觉模型降级路径。

### 2026-08-26 第 5 次变更（fix）

- 变更原因：SDK 上传附件时始终调用自动创建会话路由，已有会话中的后续附件会被错误归入新会话。
- 变更内容：存在当前 `conversationId` 时调用 `/embed/conversations/{conversationId}/assets`；仅首次无会话时调用 `/embed/assets`。
- 影响章节：输入与交互、验收标准。
- 是否触发人工确认：否，仅修复 SDK 对既有上传路由的选择，不改变 API 契约、数据模型或权限规则。
- 关联计划更新：落实 Phase 1 Task 5 中当前会话附件引用要求。

### 2026-08-26 第 4 次变更（fix）

- 变更原因：附件上传和协议发送成功后，SDK 用户消息未保留附件内容块，且后端只校验附件引用、未将图片传入模型。
- 变更内容：SDK 用户消息生成受保护的图片/文件内容块；后端按平台、Agent、最终用户和会话重新校验图片资源，读取为 data URL 并以多模态用户消息传给模型，同时持久化图片引用内容块。
- 影响章节：处理与模型数据流、验收标准。
- 是否触发人工确认：否，属于已确认附件规格中“图片原生输入”和“消息展示”的缺失实现，不新增 API、数据模型或权限规则。
- 关联计划更新：落实 Phase 1 Task 6 与 Phase 2 Task 7 中已有的图片输入要求。

### 2026-08-26 第 3 次变更（fix）

- 变更原因：上传成功后 `createdAt` 为 `datetime` 对象，直接交给 `JSONResponse` 导致响应序列化失败并返回 500。
- 变更内容：上传响应使用 Pydantic `model_dump(mode="json")` 输出 ISO 8601 时间字符串；移除同文件中的未使用导入。
- 影响章节：验收标准、风险。
- 是否触发人工确认：否，不改变接口字段，仅修复既有响应的序列化实现。
- 关联计划更新：采用上传接口响应处理的局部 bugfix，无需改变整体计划。

### 2026-08-26 第 2 次变更（fix）

- 变更原因：上传接口在临时目录 `/tmp` 与持久化目录 `/app/storage` 属于不同文件系统时，`os.replace` 抛出 `EXDEV` 并返回 500。
- 变更内容：持久化文件遇到跨设备错误时改用复制后删除临时文件；其他操作系统错误继续原样抛出。
- 影响章节：风险、验收标准、回滚说明。
- 是否触发人工确认：否，不改变 API、数据模型、权限或模块边界。
- 关联计划更新：采用原附件持久化步骤的局部 bugfix，无需改变整体计划。

### 2026-08-26 第 1 次变更（增量）

- 变更原因：AI SDK 的附件 HTTP 请求不应依赖 WebSocket endpoint 推导，避免生成 `/api/v1/ws/agents/{id}/api/v1/embed/assets` 等混乱路径。
- 变更内容：为 `AgentClientOptions` 增加可选 `baseUrl`，作为上传、状态查询、删除和资源下载的 HTTP API 根路径；未提供时保留从 `endpoint` 推导的向后兼容行为。
- 影响章节：SDK 初始化参数、后端接口调用地址、验收标准。
- 是否触发人工确认：是，属于 SDK 公共 API 契约变更；不改变后端接口路径、数据模型、鉴权语义。
- 关联计划更新：已同步更新 `plan.md`。

### 初始版本

- 时间：2026-08-25
- 变更原因：首次创建文件附件与会话缓存 request
- 变更内容：确定图片原生输入、文档解析、当前会话缓存和分期向量检索方案
- 影响章节：全部
- 是否触发人工确认：是，已确认
