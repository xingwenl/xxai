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

## Provider 能力矩阵调研补充（2026-08-27）

### 调研问题

不同模型能力不同：有生成图片的模型、读取图片的模型、纯文本交流模型，而 `agent_versions` 只发布一个主对话模型。需要确定主模型输入端的能力判断方式：主模型支持视觉时图片直接传原生输入，不支持时由主模型自主调用读图工具，避免"先发 `image_url` 报错再重试"的不可靠路径。

### 参考依据

#### 来源 7

- 类型：官方 API
- 名称：OpenRouter Models API
- 链接：https://openrouter.ai/docs/api-reference/models（端点 `https://openrouter.ai/api/v1/models`）
- 版本或发布日期：持续更新；以 2026-08-27 抓取的真实响应为准
- 调研日期：2026-08-27
- 核心做法：`/api/v1/models` 返回每个模型的 `architecture.input_modalities`（取值如 `["text"]`、`["text","image"]`、`["text","file"]`）与 `supported_parameters`（含 `tools`）。真实响应示例：`deepseek/deepseek-v4-flash-vision-exp` 的 `input_modalities: ["text","image"]`。
- 对本项目的启发：能力来源可以直接复用 OpenRouter 模型元数据，运行时按 `model_name` 匹配 `input_modalities`，同时保留显式配置覆盖；这是当前最权威、成本最低的实时探测来源。

#### 来源 8

- 类型：开源项目讨论
- 名称：Ollama `/api/tags` capabilities 字段讨论
- 链接：https://github.com/ollama/ollama/issues/14964
- 版本或发布日期：讨论进行中
- 调研日期：2026-08-27
- 核心做法：Ollama 官方 `/api/tags` 目前不返回 capabilities/输入模态字段，相关能力信息仍在讨论中。
- 对本项目的启发：不能依赖本地 Ollama 标签做能力判断；本地/自建模型需要走显式配置或保守兜底。

#### 来源 9

- 类型：生产代码修复案例
- 名称：gptme 视觉能力探测修复
- 链接：https://github.com/gptme/gptme/commit/bc4803cb0beb43ecc1293d8367b8b66dec7e0985
- 版本或发布日期：2023-03-23 提交
- 调研日期：2026-08-27
- 核心做法：gptme 曾用 `"vision" in modality` 判断视觉能力，但 OpenRouter 返回的 `modality` 是 `text+image->text`、`input_modalities` 是 `["text","image"]`，导致所有视觉模型探测失败。修复为检查 `"image" in input_modalities`。
- 对本项目的启发：能力探测必须解析 `input_modalities` 数组而非匹配 modality 字符串；该案例说明"只看模型名或 modality 字符串"会产生生产事故，需以结构化字段为准并保留兜底。

### 方案比较

能力存储位置：

| 方案 | 优点 | 限制 | 匹配度 |
|---|---|---|---|
| `agent_versions` 增加 `capabilities` JSON 列（推荐） | 与版本同生命周期、语义清晰、可按版本回滚 | 需要一次数据库迁移 | 高 |
| 复用 `model_options` JSON | 零迁移 | 与传给 ChatOpenAI 的参数混在一起，职责不清 | 低 |
| 独立能力表 | 最规范、可扩展 | 对当前单模型发布模式过度设计 | 低 |

能力来源：

| 方案 | 优点 | 限制 | 匹配度 |
|---|---|---|---|
| 实时查 OpenRouter `input_modalities` + 显式配置覆盖（推荐） | 最准、随供应商更新、可解释 | 依赖网络，失败需兜底；未托管在 OpenRouter 的模型无法查询 | 高 |
| 按模型名前缀自动推导 | 无网络依赖、零配置 | 命名规则不可靠，容易误判（gptme 案例） | 中 |
| 纯手动勾选 | 完全可控 | 维护成本高，容易过期 | 中低 |

纯文本主模型遇到图片时的降级路径：

| 方案 | 优点 | 限制 | 匹配度 |
|---|---|---|---|
| 返回 `model_attachment_not_supported` | 简单可靠 | 用户无法获得图片内容，体验差 | 中 |
| 自动调用视觉模型生成描述注入 | 体验好 | 每次都要额外调用模型，延迟和成本不可控 | 中 |
| 主模型自主调用 `image_read` 工具（推荐） | 由模型按需决定，避免强制开销；工具返回受保护资源引用，可扩展描述生成 | 依赖工具注册；纯文本模型拿到引用后需要描述能力才能真正理解图片 | 高 |

### 最终决策

- 选择方案：`agent_versions.capabilities` JSON 列 + OpenRouter `input_modalities` 实时探测（TTL 缓存）+ 显式配置优先 + 模型名兜底 + 保守默认；纯文本主模型遇图片时注入图片引用文本，主模型自主调用 `image_read` 工具。
- 选择原因：能力与发布版本同生命周期，可按版本回滚；实时探测随供应商更新且可解释；探测失败有兜底不会中断消息流；降级路径由模型自主决策，不强制额外模型调用。
- 不选择其他方案的原因：复用 `model_options` 职责混乱；独立能力表当前过度设计；纯手动配置容易过期；自动注入描述增加不可控延迟与成本。
- 对后续 spec、plan 或人工确认的影响：需要新增 `agent_versions.capabilities` 数据模型字段与迁移；网关组装消息时按能力适配图片输入；实现前需人工确认（用户已于 2026-08-27 确认：1-A 存储、2-C 探测、3-C 自主调工具）。

### 剩余风险

- OpenRouter 探测依赖网络与模型是否托管在 OpenRouter；失败时按模型名兜底，仍可能误判，需保留"仅支持 text"错误重试作为最后防线。
- `image_read` 工具当前返回受保护资源引用；生成图片文字描述需要额外配置视觉模型（`READ_IMAGE_MODEL`），未配置时纯文本主模型只能基于引用作答。

## 2026-08-28 补充调研：大文档内容不全时智能体如何自主获取剩余内容

### 调研问题

当前实现中，大文档（如长 PDF）只向模型注入开头 16,000 字符或按问题检索的 Top-K 4 段；未被注入的内容智能体无法获取，因为没有任何让智能体主动检索附件内容的工具。需要确定业界成熟做法。

### 参考方案

| 方案 | 代表实现 | 优点 | 限制 |
|---|---|---|---|
| 智能体主动检索工具（Tool-Based RAG，推荐） | OpenAI Assistants File Search、Gemini File Search、Azure Agent Service 内置检索工具、LangChain Deep Agents `search_documentation`、Docker RAG Tool | 由模型按需决定何时检索、检索什么，避免一次注入全部内容撑爆上下文；对"只发了部分内容"的提问天然可覆盖 | 依赖模型自主决定调用工具，需要在注入内容里明确提示文档更长；工具需做会话权限校验 |
| 一次性全文注入 | 现有 16,000 字符截断 | 实现简单 | 受上下文长度限制，大文档必然截断，超出部分仍不可达 |
| 检索增强注入（Pre-Contextualized RAG） | 现有 Top-K 注入 | 每轮按问题预检索 | 检索窗口外的内容模型不知道，也不会追问 |
| 混合检索 | Docker RAG Tool（语义 + BM25 关键词）、LlamaIndex 双语文章 | 未配置 embedding 时关键词兜底仍可用 | 中文分词需要额外依赖，词法兜底精度有限 |

### 关键结论

- 业界主流是给智能体一个可自主调用的文档检索工具（File Search 类），与"预注入"互补：预注入保证首轮有上下文，检索工具保证模型需要细节时能自己查（Elastic、OpenAI Community、DevoxxGenie 均描述该模式；Agent 类模型更倾向使用工具而不是依赖被动上下文）。
- 成熟实践同时提供语义检索与关键词检索（hybrid search）；本项目已具备 pgvector 余弦检索（配置 embedding 后启用），缺 embedding 时应提供关键词兜底，保证工具始终可用。
- 工具必须限定在当前会话、当前主体可见的 ready 附件内检索，与既有 `image_read` 工具的权限边界一致。

### 最终决策

- 新增内置业务工具 `attachment_search`：模型可自主传入关键词/问题检索当前会话已解析文档的 chunks；embedding 已配置时走 pgvector 余弦相似度，未配置时用词法匹配分数兜底；返回片段内容、位置、页码与相似度。
- 在注入的文档文本中增加提示：当全文被截断或只注入 Top-K 时，明确告知模型"附件还有其他内容，可调用 attachment_search 工具继续检索"，弥补模型"不知道还有内容"的信息差。
- 启用方式：新工具自动进入内置工具目录；用迁移为现有 Agent 启用（对齐 `http_post` 启用先例），管理界面可随时关闭。
- 不选择一次性全文注入：上下文长度硬约束下无法解决；不选择只做预检索增强：模型无法主动获取检索窗口外内容。

### 来源

- OpenAI Assistants API File Search：https://developers.openai.com/api/docs/assistants/tools/file-search.md
- Azure Architecture Center Agentic RAG：https://learn.microsoft.com/en-ca/azure/architecture/ai-ml/guide/rag/rag-agentic
- Elastic 博客 Search tools for context engineering：https://www.elastic.co/search-labs/blog/search-tools-context-engineering
- DevoxxGenie 博客 Why We Turned RAG Into a Tool：https://genie.devoxx.com/blog/rag-semantic-search-tool
- OpenAI Community：File Search 是 Tool-Based RAG：https://community.openai.com/t/is-openais-file-search-tool-considered-rag/1064183/3
- Docker RAG Tool（混合检索）：https://docs.docker.com/ai/docker-agent/tools/rag/
- LlamaIndex 博客 词法搜索 VS 语义搜索：https://llamaindex.org.cn/blog/is-grep-all-you-need-lexical-vs-sematic-search-for-agents

调研日期：2026-08-28。
