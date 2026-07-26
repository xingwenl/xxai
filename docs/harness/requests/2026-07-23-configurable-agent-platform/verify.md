# 验证记录

## 当前状态

任务 6 已实现并完成单元级验证；真实数据库迁移和外部模型/MCP 联调仍未完成。

## 已执行

- 已确认持久化 worktree 路径和分支。
- 已恢复 research、spec、plan 文档。
- `poetry lock`：通过，成功写入新的依赖锁文件。
- `poetry install --no-root`：通过，安装 136 个锁定依赖。
- `poetry check`：通过。
- `poetry run pytest -q`：通过，`43 passed`。
- `poetry run ruff check .`：通过。
- `poetry run python -c 'import langgraph, llama_index.core, mcp, celery, cryptography, httpx'`：通过。
- `poetry run pytest tests/platform/test_platform_services.py -q`：通过，`2 passed`。
- `poetry run ruff check app/modules/platform app/__init__.py migrations/env.py tests/platform`：通过。
- `poetry run alembic history`：通过，平台迁移 `20260723_0003` 为当前 head。
- `poetry run pytest -q`（任务 2）：通过，`49 passed`。
- `poetry run ruff check app/modules/agent app/__init__.py migrations/env.py migrations/versions/20260723_0004_agent.py tests/agent`：通过。
- `poetry run black --check app/modules/agent tests/agent migrations/versions/20260723_0004_agent.py`：通过。
- `poetry run alembic history`（任务 2）：通过，Agent 迁移 `20260723_0004` 为当前 head。
- OpenAPI 构建检查：通过，生成 Agent 创建、版本创建、发布和回滚 4 个路径。
- `poetry run pytest -q`（任务 3 基础）：通过，`56 passed`。
- `poetry run ruff check app/modules/knowledge migrations/env.py migrations/versions/20260723_0005_knowledge.py tests/knowledge`：通过。
- `poetry run black --check app/modules/knowledge tests/knowledge migrations/versions/20260723_0005_knowledge.py`：通过。
- `poetry run alembic history`（任务 3 基础）：通过，知识库迁移 `20260723_0005` 为当前 head。
- 知识库基础行为测试覆盖 LlamaIndex 切片、embedding 维度校验、非 HTTP URL、凭证 URL、回环地址和云元数据地址拒绝。
- `poetry run pytest -q`（任务 3 完成）：通过，`62 passed`。
- 知识库定向 Ruff 与 Black：通过。
- OpenAPI 构建检查：通过，生成知识库配置、文件导入、URL 导入、文档状态和检索共 6 个路径。
- Celery 注册检查：通过，`knowledge.ingest_document` 已注册。
- embedding 配置变更会增加索引版本，并为已有文档创建新的导入任务。
- `poetry run pytest -q`（任务 4）：通过，`64 passed`。
- Skill 定向 Ruff 与 Black：通过。
- `poetry run alembic history`（任务 4）：通过，Skill 迁移 `20260723_0006` 为当前 head。
- Skill 测试覆盖声明式模板参数渲染和缺失参数拒绝；首期不执行上传脚本。
- `poetry run pytest -q`（任务 5）：通过，`80 passed`。
- `poetry run ruff check .`（任务 5）：通过。
- `poetry run black --check app/modules/mcp tests/mcp migrations/versions/20260725_0007_mcp.py`：通过。
- OpenAPI 构建检查：通过，生成 MCP 配置、工具同步、策略更新、Agent 绑定、工具调用、人工确认和审计查询共 7 个路径。
- `poetry run alembic history`（任务 5）：通过，MCP 迁移 `20260725_0007` 为当前 head。
- MCP 定向测试共 16 个，覆盖工具白名单、JSON Schema 参数校验、只读自动调用、副作用确认、拒绝、确认过期、原子领取防重复执行、审计脱敏、认证头加密、私网目标拒绝和官方 Streamable HTTP 客户端适配。
- MCP 工具首次发现默认禁用且标记为高风险；远端工具 Schema 变化或工具消失时自动撤销已有白名单，要求管理员重新确认。
- 增加显式 `greenlet` 运行依赖，修复 macOS arm64 下 Poetry 未安装 SQLAlchemy 异步运行依赖的问题。
- 任务 6 定向测试：`poetry run pytest tests/conversation -q`，通过，`9 passed`。
- 任务 6 全量测试：`poetry run pytest -q`，通过，`89 passed`。
- 任务 6 全仓 Ruff：`poetry run ruff check .`，通过。
- 任务 6 定向 Black：`poetry run black --check app/modules/conversation tests/conversation migrations/versions/20260725_0008_conversation.py app/modules/agent/models.py app/modules/agent/repositories.py app/modules/knowledge/models.py app/modules/knowledge/repositories.py app/modules/knowledge/router.py app/modules/knowledge/schemas.py app/modules/skill/models.py app/modules/skill/repositories.py app/modules/mcp/repositories.py migrations/env.py app/__init__.py`，通过。
- OpenAPI 构建检查：通过，包含 `/api/v1/agents/{agent_id}/chat`。
- `poetry run alembic history`：通过，`20260725_0008` 为当前 head。
- SQLAlchemy mapper 检查：通过，Conversation、AgentKnowledgeBase 和已有模型可完成 mapper 配置。
- SSE 流式单元测试：通过，`stream_graph()` 使用 `astream` 逐段发送 `message_delta`，结束后持久化最终结果；工具调用场景仍使用一次运行完成后的结构化事件路径。

## 待执行

- `poetry run black --check .`：未通过，仓库现有 33 个文件会被 Black 重新格式化；本次 MCP 新增文件均已通过定向 Black，没有格式化无关文件。
- 迁移、启动和安全测试将在后续实现任务完成后逐项记录。
- 当前未启动 PostgreSQL、pgvector、Redis 和 Celery Worker，真实文件解析、外部 embedding 请求、向量查询及 Worker 重试需要在基础设施启动后联调。
- 本机 PostgreSQL 和 Redis 容器正在运行，但 worktree 默认数据库密码与容器配置不一致，`poetry run alembic current` 返回 `InvalidPasswordError`，因此未执行 `alembic upgrade head`。需要提供正确的 `DATABASE_URL` 后重做真实迁移验证。
- 当前没有可用的远程 Streamable HTTP MCP 测试服务，官方 MCP 客户端已通过注入会话测试，真实服务的初始化、工具发现和调用仍需联调。
- `poetry run alembic upgrade head`：未执行成功；当前 worktree 数据库密码与本机 PostgreSQL 容器不一致，不能据此声称真实迁移通过。

## 失败项与例外

- 原临时 worktree 被系统清理，未提交源码无法恢复；当前已在持久化 worktree 按本计划重建并分任务提交。
