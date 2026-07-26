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

任务 6 新增 `AgentKnowledgeBase` 绑定实体、`Conversation` 和 `ConversationMessage`。绑定时校验 Agent 与知识库属于同一平台；运行时只使用启用绑定。Conversation 以平台、Agent、用户为隔离边界，消息角色仅允许 `user`、`assistant`、`tool`，引用保存为结构化 JSON。

对话入口为 `POST /api/v1/agents/{agent_id}/chat`，请求体包含 `message`、可选 `conversation_id` 和 `stream`。JSON 返回 `conversation_id`、`message_id`、`content`、`citations`、`knowledge_grounded`、`pending_confirmation_id`。SSE 使用 `text/event-stream`，事件名称固定为 `message_delta`、`citation`、`tool_call`、`confirmation_required`、`tool_result`、`message_completed`、`error`，每条事件信封含递增 `sequence`、会话 ID、消息 ID 和结构化 payload。

任务 6 不引入 LangGraph checkpointer；Graph State 仅服务于单次运行，Conversation/Message 是对外持久化状态。模型无知识库依据时可以使用通用知识，但必须返回 `knowledge_grounded=false` 且不生成引用。

配置 API 位于 `/api/v1/platforms` 和对应资源路径；对话为 `POST /api/v1/agents/{agent_id}/chat`，支持 JSON 和 SSE 事件：`message_delta`、`citation`、`tool_call`、`confirmation_required`、`tool_result`、`message_completed`、`error`。

## 安全与验收

- 密钥使用 Fernet 加密，不返回、不写普通日志。
- URL 抓取拒绝非 HTTP、凭证、回环、私有、链路本地和云元数据地址，并限制大小、重定向和超时。
- Agent 只使用当前平台已发布且绑定的能力。
- 知识库答案必须返回来源；没有充分依据时明确标记为非知识库内容。
- 对话用户只能读取和继续自己的会话；未发布 Agent、跨平台 Agent、未绑定知识库、未启用 Skill/MCP 工具均不可使用。
- MCP 只读工具自动执行；副作用工具只能创建 `confirmation_required`，不得在对话 Graph 中直接执行。
- SSE 事件序号严格递增，正常结束发送 `message_completed`，业务错误发送结构化 `error`，客户端断开后停止后续生成和工具调用。
- 验收覆盖平台隔离、版本发布/回滚、导入状态、向量维度、引用、MCP 白名单和副作用确认。

## 任务 6 验收标准

- Conversation、ConversationMessage、AgentKnowledgeBase 迁移可生成当前 head，且绑定唯一约束和平台外键正确。
- 只有当前用户所属平台的已发布 Agent 可以对话；会话不能跨平台或跨用户读取。
- Skill 按 `sort_order` 合并到 system prompt，缺少模板参数沿用 `BadRequestException`。
- 检索仅覆盖 Agent 已绑定且启用的知识库；有依据返回 Citation 和 `knowledge_grounded=true`，无依据不伪造 Citation。
- 只读 MCP 工具通过 `invoke_tool()` 执行并返回工具事件；副作用 MCP 返回确认 ID 且 executor 未被调用。
- JSON 与 SSE 共享运行逻辑；SSE 事件顺序稳定、序号递增、正常结束有 `message_completed`、错误有 `error`。
- 定向测试、Ruff、Black、Poetry 检查和 Alembic history 通过；真实迁移因数据库密码问题仍需明确记录为未完成。

## 停点判断

本任务涉及架构、数据模型、API 和鉴权行为，进入实现前需人工确认。当前用户已确认采用成熟库、平台隔离、知识库拥有 embedding 配置和上述首期范围。

## 变更记录

### 初始版本

- 时间：2026-07-24
- 变更原因：恢复持久化 worktree 中的 request 文档。
- 变更内容：恢复已确认的第一期设计边界。
- 是否触发人工确认：是，沿用用户已确认方案。
