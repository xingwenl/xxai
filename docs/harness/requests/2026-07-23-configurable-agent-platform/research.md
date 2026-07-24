# 业界调研记录

## 调研问题

规划一个多平台可配置 AI Agent，覆盖 Agent 编排、知识库、配置式 Skill、远程 MCP、SSE 对话和后续 SDK。

## 参考依据

- LangGraph：https://langchain-ai.github.io/langgraph/，用于有状态 Agent 编排、工具调用和人工确认。
- LlamaIndex：https://docs.llamaindex.ai/，用于文档解析、切片、embedding 和检索。
- MCP 规范：https://modelcontextprotocol.io/specification/，远程工具统一使用标准协议。
- Dify：https://docs.dify.ai/，作为成熟配置化 Agent 平台的功能边界参考。
- pgvector：https://github.com/pgvector/pgvector，复用 PostgreSQL 保存向量。
- Celery：https://docs.celeryq.dev/，处理异步导入、重试和任务状态。
- OWASP SSRF：https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html，指导网页抓取安全。
- SSE：https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events，指导流式事件传输。

调研日期：2026-07-23。当前环境无法稳定抓取外部网页，以上来源需要在依赖实现前做版本兼容验证。

## 方案比较

| 方案 | 优点 | 限制 | 决策 |
|---|---|---|---|
| 自研 Runtime | 完全可控 | 重复实现状态、RAG、协议和重试 | 不采用 |
| 深度改造 Dify | 控制面完整、上线快 | 受其数据模型、权限和升级方式约束 | 作为参考或独立集成 |
| 自有控制面 + LangGraph + LlamaIndex + MCP SDK | 复用成熟库，同时掌握租户、权限、API 和 SDK 边界 | 需要验证多库版本兼容 | 采用 |

## 最终决策

采用模块化 FastAPI 单体：LangGraph 负责 Agent 流程，LlamaIndex 负责知识库，官方 MCP SDK 负责远程 MCP，PostgreSQL + pgvector 保存切片和向量，Celery + Redis 处理异步任务。embedding 配置归知识库所有，避免不同 Agent 使用不同向量维度访问同一索引。

## 剩余风险

需要验证 Python 3.12、pgvector 扩展、第三方库异步接口、密钥加密主密钥、Worker 公网访问和网页抓取 SSRF 防护。
