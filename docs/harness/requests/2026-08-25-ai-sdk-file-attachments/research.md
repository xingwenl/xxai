# AI SDK 文件附件与会话缓存调研

## 调研问题

本需求需要为 AI SDK 增加图片和文档上传能力，并让同一会话后续请求复用已解析的文件内容、切块和可选向量。调研重点是多供应商附件输入、文档解析、缓存版本化、向量检索和当前会话权限边界。

## 功能复杂度

- 级别：核心功能
- 选择理由：同时涉及 SDK 输入协议、上传 API、异步文件处理、数据模型、模型适配、向量检索和会话权限；会改变架构边界、API 契约和数据模型。
- 最低调研要求：至少一个模型官方文档、一个通义/DeepSeek 官方来源、一个成熟解析或向量检索实现，并完成方案比较。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenAI PDF and file inputs / Responses API
- 链接：https://platform.openai.com/docs/guides/pdf-files
- 版本或发布日期：持续更新；以调研日期可用版本为准
- 调研日期：2026-08-25
- 核心做法：支持的模型可以把 PDF 作为文件输入；应用需要根据模型能力决定是否使用原生文件输入，不能把该能力假设为所有聊天模型共有。
- 对本项目的启发：统一附件协议必须保留原始 asset，同时由 provider adapter 判断是否走原生文件输入；不支持时使用服务端解析文本。

### 来源 2

- 类型：官方文档
- 名称：OpenAI Embeddings guide
- 链接：https://platform.openai.com/docs/guides/embeddings
- 版本或发布日期：持续更新；以调研日期可用版本为准
- 调研日期：2026-08-25
- 核心做法：文本先转换为 embedding，再用于搜索、聚类和检索增强生成；应用需要管理输入长度和向量维度。
- 对本项目的启发：向量缓存必须记录 embedding 模型、维度和处理版本，不能只按 asset_id 复用。

### 来源 3

- 类型：官方文档
- 名称：阿里云百炼 Qwen-VL 多模态模型
- 链接：https://help.aliyun.com/zh/model-studio/user-guide/qwen-vl-plus
- 版本或发布日期：持续更新；以调研日期可用版本为准
- 调研日期：2026-08-25
- 核心做法：Qwen-VL 系列通过多模态消息接收图片 URL 或图片数据，具体能力随模型和端点变化。
- 对本项目的启发：图片输入应保持独立的 image 内容块，并由通义 adapter 转换为其协议，不应把图片统一降级为文件名或文本。

### 来源 4

- 类型：官方文档
- 名称：DeepSeek Chat Completions API
- 链接：https://api-docs.deepseek.com/api/create-chat-completion
- 版本或发布日期：持续更新；以调研日期可用版本为准
- 调研日期：2026-08-25
- 核心做法：公开聊天接口以文本消息和工具调用为主，不能假设 Chat/Reasoner 端点支持图片或任意二进制文件输入。
- 对本项目的启发：DeepSeek adapter 默认消费解析后的文本 chunks；图片需要独立视觉模型生成描述，或返回稳定的不支持错误。

### 来源 5

- 类型：成熟开源项目官方文档
- 名称：LlamaIndex Ingestion Pipeline
- 链接：https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/
- 版本或发布日期：LlamaIndex 当前稳定文档
- 调研日期：2026-08-25
- 核心做法：文档经过读取、转换、切块和 embedding 后形成可持久化的节点；转换结果和 embedding 可以使用缓存避免重复处理。
- 对本项目的启发：复用现有 `llama-index-readers-file`、`SentenceSplitter` 和知识库 ingestion 结构，新增会话附件来源，而不是另建完全不同的解析体系。

### 来源 6

- 类型：成熟开源项目
- 名称：pgvector
- 链接：https://github.com/pgvector/pgvector
- 版本或发布日期：持续维护；以调研日期可用版本为准
- 调研日期：2026-08-25
- 核心做法：在 PostgreSQL 中保存向量并按距离检索，可与业务条件过滤联合使用。
- 对本项目的启发：当前仓库已有 pgvector 知识库检索，附件向量可沿用 PostgreSQL 和现有 embedding 配置，并强制增加 `conversation_id` 过滤。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 只保存原文件，每次重新解析 | 数据结构简单，初始实现快 | 重复消耗 CPU、OCR 和 embedding 成本，延迟不稳定 | 低 |
| 所有内容强制解析成文本并保存 | 多供应商兼容，DeepSeek 可用 | 图片细节、PDF 版式和表格结构损失；无法充分利用视觉模型 | 中 |
| 原文件 + 解析结果 + chunks + 可版本化 embedding（推荐） | 同时支持视觉输入、文本兜底和会话内复用；供应商差异收敛在 adapter | 需要异步任务、状态机、版本字段和数据清理 | 高 |
| 接入独立外部向量数据库 | 检索能力丰富，扩展规模大 | 引入新基础设施、同步和权限链路；现有 pgvector 能力重复 | 低到中 |

## 最终决策

- 选择方案：当前会话范围内的“原文件 + 解析结果 + 切块 + 可选向量”分层缓存，沿用现有 `ConversationAsset` 和 pgvector 能力。
- 选择原因：满足 OpenAI/Qwen 的图片输入，同时为 DeepSeek 和不支持原生文件的模型提供文本检索；只绑定当前会话，权限边界清晰；解析器和 embedding 版本变化可以通过版本键失效缓存。
- 不选择其他方案的原因：每次重算成本和延迟不可接受；全部文本化损失视觉信息；独立向量库会扩大架构边界且没有当前规模收益。
- 对后续 spec、plan 或人工确认的影响：必须新增文件处理状态、解析结果和 chunk/embedding 关系；必须新增上传、状态查询和消息附件字段；实现前需要人工确认数据模型、API 契约和异步任务边界。

## 剩余风险

- 资料时效性：供应商的视觉/文件能力、模型名称和端点限制可能变化，需要运行时能力配置和联调测试。
- 与本项目上下文的差异：当前网关消息入口只校验 `payload.text`，需要扩展为附件引用；当前 `ConversationAsset` 主要服务图片和资源下载，需要增加文档处理状态。
- 尚未验证的假设：扫描 PDF 的 OCR 引擎、Office 表格解析质量、Celery/Worker 对大文件的吞吐，以及生产环境 pgvector 索引规模。
