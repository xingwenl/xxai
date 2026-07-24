# 设计说明

## 目标

第一期实现多平台可配置 Agent 后端：平台隔离、Agent 配置与发布、文件/网页知识库、配置式 Skill、远程 Streamable HTTP MCP，以及 HTTP JSON/SSE 对话接口。

## 范围

- 使用现有 JWT，平台管理员只能管理所属平台。
- Agent 使用 LangGraph，聊天模型使用 OpenAI 兼容配置。
- 知识库支持 txt、md、pdf、docx 和网页 URL；异步解析、切片、embedding、pgvector 检索和引用。
- embedding 模型、base URL、密钥和维度归知识库；修改后增加索引版本并重新索引。
- Skill 只支持名称、描述、指令模板和能力绑定。
- MCP 只支持远程 Streamable HTTP，工具白名单；有副作用工具必须确认。
- 第一阶段只提供后端 API，不实现管理后台、JS SDK、WebSocket、脚本 Skill、本地 MCP 和数据库连接器。

## 数据与 API

新增平台、Agent、AgentVersion、KnowledgeBase、KnowledgeDocument、KnowledgeChunk、IngestionTask、Skill、MCP、Conversation 和确认实体。所有实体带 platform_id 或可追溯到平台。

配置 API 位于 `/api/v1/platforms` 和对应资源路径；对话为 `POST /api/v1/agents/{agent_id}/chat`，支持 JSON 和 SSE 事件：`message_delta`、`citation`、`tool_call`、`confirmation_required`、`tool_result`、`message_completed`、`error`。

## 安全与验收

- 密钥使用 Fernet 加密，不返回、不写普通日志。
- URL 抓取拒绝非 HTTP、凭证、回环、私有、链路本地和云元数据地址，并限制大小、重定向和超时。
- Agent 只使用当前平台已发布且绑定的能力。
- 知识库答案必须返回来源；没有充分依据时明确标记为非知识库内容。
- 验收覆盖平台隔离、版本发布/回滚、导入状态、向量维度、引用、MCP 白名单和副作用确认。

## 停点判断

本任务涉及架构、数据模型、API 和鉴权行为，进入实现前需人工确认。当前用户已确认采用成熟库、平台隔离、知识库拥有 embedding 配置和上述首期范围。

## 变更记录

### 初始版本

- 时间：2026-07-24
- 变更原因：恢复持久化 worktree 中的 request 文档。
- 变更内容：恢复已确认的第一期设计边界。
- 是否触发人工确认：是，沿用用户已确认方案。
