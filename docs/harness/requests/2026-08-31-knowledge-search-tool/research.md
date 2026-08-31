# 知识库检索工具 knowledge_search 调研

## 调研问题

当前 Agent 的知识库内容只通过 `build_system_prompt` 的 Top-K 注入（`conversation/runtime.py`），
没有独立检索工具；模型误用 `attachment_search` 检索知识库，得到空结果。调研重点是：
为"知识库"这种独立数据源提供检索工具的最佳实践、工具描述与契约设计、权限边界和返回结构。

## 功能复杂度

- 级别：核心功能（新增独立内置工具）
- 选择理由：涉及 API 契约（模型可见工具列表）、权限行为（模型可主动检索 Agent 绑定知识库）、
  运行时检索链路和存量 Agent 工具启用迁移，属于策略 B（复杂/架构级变更）。

## 参考方案

### 方案一：为不同数据源拆分独立检索工具（业界主流）

- Azure Agentic RAG 指南明确建议"为不同数据源拆分检索工具"，并指出工具描述决定模型
  的工具选择精度；检索结果建议返回 top-3~5 个 chunk 并携带元数据。
- OpenAI Agents SDK 提供内置 `FileSearchTool`，支持 `max_num_results`、过滤器等参数，
  作为知识库检索工具开箱即用。
- 结论：数据源（会话附件 vs 知识库）不同、权限模型（会话内 asset vs Agent-KB 绑定）不同、
  返回结构（文件名/页码 vs 文档标题/知识库）不同，应拆分工具而不是复用。

### 方案二：复用 attachment_search，按数据源分流

- 在 `attachment_search` 内加 `source` 参数区分附件与知识库。
- 收益：少一个工具，模型选择面小。
- 限制：两个数据源权限模型不同（会话 asset 权限 vs Agent 知识库绑定），混在一个工具里
  会模糊权限边界；契约和错误码复杂化；与 Azure"为不同数据源拆分工具"的实践相悖。
- 不采用：工具选择是模型行为，契约模糊正是本次误用根因，不应把模糊延续到新工具。

### 方案三：复用已有注入链路，不新增工具

- 只提高 `retrieval_top_k` / `knowledge_context_max_chars`，让注入覆盖更多内容。
- 收益：改动最小。
- 限制：注入有上下文预算上限，无法覆盖全部知识库内容；大知识库下依然存在"未注入部分
  模型无法主动获取"的问题，与 `attachment_search` 增量解决附件问题的思路一致。
- 不采用：治标不治本，知识库越大越不可靠。

## 方案比较

| 维度 | 拆分独立工具（方案一） | 附件工具内分流（方案二） | 只提高注入量（方案三） |
| --- | --- | --- | --- |
| 工具选择精度 | 高，契约清晰 | 低，依赖模型理解 source 参数 | 不涉及工具 |
| 权限边界 | 清晰，沿用 Agent-KB 绑定 | 混合，易混淆 | 沿用现有 |
| 覆盖面 | 全量知识库可按需检索 | 同左 | 受注入预算限制 |
| 改动面 | 新增工具 + 迁移 + 测试 | 改既有工具契约 | 最小 |
| 业界依据 | Azure/OpenAI/LangChain 一致推荐 | 与推荐相悖 | 无 |

## 最终选择

采用方案一：新增独立内置业务工具 `knowledge_search`。

- 检索范围：当前 Agent 已启用绑定的知识库（`KnowledgeRepository.list_enabled_for_agent`），
  可选 `knowledge_base_id` 限定单一知识库。
- 检索方式：沿用 `retrieve_citations` 的向量检索链路（`build_embedding_model(base)` +
  `knowledge_repo.search` 余弦相似度 + `retrieval_threshold` 过滤），知识库本身依赖
  embedding 索引，不做词法兜底。
- 返回结构：参考 `attachment_search` 的结构化 `results`，字段改为
  `knowledge_base_id / knowledge_base_name / document_id / title / source_url / position / content / score`。
- 契约分离：`knowledge_search` 描述明确"检索知识库，与会话附件无关"；
  `attachment_search` 描述补充"仅检索会话附件，知识库请使用 knowledge_search"，
  双向往模型澄清边界。
- 启用方式：沿用 `agent_builtin_tools` 绑定 + 迁移为存量 Agent 启用（参照 `20260828_0030`）。

## 调研来源

| 来源 | 链接 | 调研日期 |
| --- | --- | --- |
| Azure Agentic RAG 指南（工具拆分与描述设计） | https://learn.microsoft.com/zh-tw/azure/architecture/ai-ml/guide/rag/rag-agentic | 2026-08-31 |
| OpenAI Agents SDK tools（FileSearchTool 参数与用法） | https://openai.github.io/openai-agents-python/tools/ | 2026-08-31 |
| OpenAI file search 指南（返回 403，引用标题与摘要结论） | https://developers.openai.com/api/docs/guides/tools-file-search | 2026-08-31 |
| LangChain create_retriever_tool（检索器封装为工具） | https://reference.langchain.com/python/langchain-core/tools/retriever/create_retriever_tool | 2026-08-31 |
| LlamaIndex QueryEngineTool（查询引擎封装为 Agent 工具） | https://docs.llamaindex.ai/en/v0.10.19/module_guides/deploying/agents/usage_pattern.html | 2026-08-31 |

## 剩余风险

- OpenAI file search 官方指南正文无法抓取（403），仅采用其公开标题/摘要结论；
  核心方案已由 Azure Agentic RAG 与 OpenAI Agents SDK 文档支撑，不影响方案定稿。
- 知识库 embedding 为远程模型端点（OpenAI-compatible/本地 ollama），单测必须 mock，
  不能打真实 API。
- 服务器数据库中的真实知识库检索验证需人工在服务端执行（本地沙箱无 DB 访问权限）。
