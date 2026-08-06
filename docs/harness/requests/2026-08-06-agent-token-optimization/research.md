# Agent 对话 Token 优化调研

## 调研问题

在现有 FastAPI、pgvector、LangChain/LangGraph 和技能包运行时中，如何减少知识库与技能注入造成的输入 Token，同时保持召回质量和技能可用性。

调研日期：2026-08-06。

## 参考方案

### 相似度阈值与 Top K

- LangChain `ScoreThresholdRetriever`（官方文档，2025，https://python.langchain.com/docs/how_to/similarity_score_threshold_retriever/）：支持相似度阈值、最大返回数和逐步扩大召回数量。适合“没有可靠命中时返回 0”的场景。
- LlamaIndex 向量检索配置（官方文档，2025，https://docs.llamaindex.ai/en/stable/module_guides/querying/node_postprocessor/）：将 `similarity_top_k` 与相似度过滤分开，说明 Top K 是上限而不是相关性判断。

### 技能渐进式加载

- Model Context Protocol specification（官方规范，2025，https://modelcontextprotocol.io/specification/2025-06-18）：工具和资源采用名称、描述与按需读取的渐进式披露方式，避免把所有详细内容放入初始上下文。
- LangChain tool calling 文档（官方文档，2025，https://python.langchain.com/docs/concepts/tool_calling/）：模型可通过受控工具请求额外上下文，工具边界需要由服务端校验。

## 方案比较

| 方案 | 收益 | 限制 | 决策 |
|---|---|---|---|
| 固定 Top K | 实现简单 | 低质量结果也会注入，无法返回 0 | 不采用 |
| 阈值 + Top K | 控制相关性和上下文上限，改动可控 | 阈值需要按模型分布调优 | 采用 |
| 查询改写 + 重排 + 自适应检索 | 质量上限高 | 增加模型调用、延迟、运维和评估成本 | 第一阶段不采用 |
| 所有技能完整注入 | 技能立即可用 | 初始 Prompt 随技能数量线性增长 | 不采用 |
| 技能元数据常驻 + 按需加载 | 显著降低初始 Token，保持完整能力 | 需要新增受控加载工具和一次工具调用 | 采用 |

## 最终决策

第一阶段采用“每知识库相似度阈值 + 每知识库 Top K + 全局上下文预算 + 技能元数据常驻/按需加载”。检索使用 cosine similarity 语义，不直接暴露 cosine distance；数据库查询先取候选并计算相似度，再过滤阈值、限制 Top K、跨知识库去重和全局截断。暂不实现按内容类型的独立阈值、查询改写、重排模型和自适应检索。

## 剩余风险

- 不同 Embedding 模型的分数分布不同，默认阈值 0.5 需要通过日志和人工样本校准。
- 按知识库配置阈值不能覆盖同一知识库内的代码、文档、FAQ差异，后续可基于现有 `source_type` 增加覆盖配置。
- 技能按需加载会增加一次工具调用延迟；核心技能可在后续增加始终加载标记。
