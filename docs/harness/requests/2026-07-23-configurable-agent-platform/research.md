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

## 任务 6 专项调研

调研日期：2026-07-26。当前依赖版本以 `apps/backend/pyproject.toml` 和 `poetry.lock` 为准：LangGraph `1.2.x`、FastAPI `0.139.x`、SQLAlchemy `2.0.x`。

### 参考来源

- LangGraph 官方文档，Graph API、StateGraph 与工具调用：https://langchain-ai.github.io/langgraph/，调研日期 2026-07-26。适合把一次对话拆成加载上下文、模型决策、工具执行和持久化节点；本期不引入 checkpointer。
- FastAPI 官方文档，StreamingResponse 与异步生成器：https://fastapi.tiangolo.com/advanced/custom-response/，调研日期 2026-07-26。适合输出 `text/event-stream`，但断开检测和业务状态仍需由应用层管理。
- MDN Server-sent events：https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events，调研日期 2026-07-26。事件应使用稳定的 `event`/`data` 信封，服务端单向推送并以结束事件明确完成。
- LlamaIndex 检索与 Citation 相关能力：https://docs.llamaindex.ai/，调研日期 2026-07-26。现有代码已经封装 embedding、pgvector 查询和 `Citation` Schema，任务 6 只复用这些能力。
- Dify 文档，对话应用的会话、引用和工具能力边界：https://docs.dify.ai/，调研日期 2026-07-26。成熟配置式 Agent 通常将会话消息、引用和工具事件作为独立结构化数据，而不是只拼接进文本。

### 方案比较

| 方案 | 收益 | 限制 | 决策 |
|---|---|---|---|
| 自研 while-loop 对话运行时 | 实现量小 | 容易重复处理状态、工具循环、确认和错误边界 | 不采用 |
| LangGraph + 自有 Conversation/Message 持久化 | 复用状态图和工具编排，保留现有租户与审计边界；JSON/SSE 可共用运行服务 | 首期不支持跨进程 Graph checkpoint 恢复 | 采用 |
| LangGraph + PostgreSQL checkpointer | 原生支持 Graph 恢复 | 新增 checkpoint 表、线程协议和恢复 API，和现有消息持久化形成双重状态 | 本期不采用 |

### 最终选择与剩余风险

选择“LangGraph + 自有会话消息持久化”。一次请求的 LangGraph State 只保存运行时所需的非敏感字段；Conversation/Message 保存用户消息、最终助手消息、引用、grounded 标志和待确认标识。模型密钥、MCP 认证头和 embedding 密钥不进入 State、事件或普通日志。SSE 客户端断开时取消生成任务并停止后续工具调用。剩余风险是没有真实模型密钥、真实远程 MCP 服务和正确数据库连接时，只能用 fake model、fake embedding、注入 executor 及迁移历史检查完成单元验证。

## 剩余风险

需要验证 Python 3.12、pgvector 扩展、第三方库异步接口、密钥加密主密钥、Worker 公网访问和网页抓取 SSRF 防护。
