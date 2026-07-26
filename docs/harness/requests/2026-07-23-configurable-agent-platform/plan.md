# 可配置多平台 AI Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 FastAPI 后端实现多平台可配置 Agent 第一阶段。

**Architecture:** 模块化 FastAPI 单体，直接使用 LangGraph、LlamaIndex、官方 MCP SDK；PostgreSQL + pgvector 保存知识库，Celery + Redis 处理异步导入。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、LangGraph、LlamaIndex、MCP SDK、Celery、Redis、pgvector、httpx、cryptography。

---

### 任务 0：依赖与配置

- [x] 更新 `pyproject.toml` 和 `poetry.lock`。
- [x] 增加模型、Redis、文件存储、抓取和加密配置。
- [x] 添加依赖烟囱测试，运行全量 pytest、ruff 和 black。

### 任务 1：平台隔离

- [x] 新增平台、平台管理员模型、迁移、仓储、服务和 API。
- [x] 平台创建者自动成为管理员。
- [x] 添加跨平台访问失败测试。

### 任务 2：Agent 配置

- [x] 新增 Agent 草稿和不可变发布版本。
- [x] 使用 LangGraph/LangChain OpenAI 客户端构造聊天模型。
- [x] 增加 Fernet 密钥加密、发布和回滚测试。

### 任务 3：知识库

- [x] 新增知识库、文档、切片、向量和导入任务模型。
- [x] 使用 LlamaIndex 处理文件解析、切片、embedding 和检索。
- [x] 使用 Celery + Redis 异步导入，加入 URL SSRF 防护。
- [x] 返回文档标题、来源 URL 和命中片段。

### 任务 4：Skill、任务 5：MCP

- [x] 实现配置式 Skill 和绑定。
- [x] 实现远程 MCP、工具白名单、副作用确认和审计。

### 任务 6：LangGraph 对话与 SSE

**变更文件清单：**

- 创建 `apps/backend/app/modules/conversation/{__init__.py,models.py,repositories.py,schemas.py,runtime.py,router.py}`。
- 创建 `apps/backend/migrations/versions/20260725_0008_conversation.py`。
- 修改 Agent、Knowledge、Skill、MCP 仓储以提供平台隔离后的运行时能力查询。
- 修改 `apps/backend/app/__init__.py` 注册 conversation router。
- 创建 `apps/backend/tests/conversation/`，覆盖模型、运行时、JSON/SSE 契约和取消路径。
- 更新本 request 的 `verify.md`、`acceptance.md`、`meta.json`。

**数据流与边界：**

1. 路由校验登录用户、Agent 所属平台、已发布默认版本和 Conversation 所属用户。
2. Runtime loader 查询绑定的知识库、已启用 Skill 和 MCP 白名单能力；任何能力查询都带 `platform_id`。
3. LangGraph State 依次执行检索、提示组装、模型决策和工具分支。工具调用只通过 `invoke_tool()`，工具结果限制为固定最大字符数后回填模型。
4. 普通回答持久化 user/assistant 消息；副作用工具只持久化待确认状态并返回 confirmation ID。
5. JSON 直接返回最终 envelope；SSE 使用异步生成器发送同一运行时产生的事件，客户端取消时取消生成并避免继续调用工具。

**TDD 实施切分与 checkpoint：**

- [ ] 6.1 先写 Conversation、Message、AgentKnowledgeBase 及平台/唯一约束失败测试，再写模型和迁移；执行定向测试与 `alembic history`，提交 checkpoint。
- [ ] 6.2 先写 Agent 发布版本、绑定知识库、Skill 排序和 MCP 白名单加载器失败测试，再实现仓储和运行时能力对象；提交 checkpoint。
- [ ] 6.3 先写 Citation/grounded 与无工具回答失败测试，再实现最小 LangGraph 图和 fake model 注入；提交 checkpoint。
- [ ] 6.4 先写只读工具自动执行与副作用确认不执行失败测试，再接入 `invoke_tool()` 和工具结果限制；提交 checkpoint。
- [ ] 6.5 先写 JSON 响应和权限隔离失败测试，再实现 chat router；提交 checkpoint。
- [ ] 6.6 先写 SSE 事件顺序、完成、错误和客户端取消失败测试，再实现异步事件生成器；提交 checkpoint。
- [ ] 6.7 执行定向/全量验证，更新 Harness 文档；数据库密码不正确时不得声称真实迁移通过，提交最终 checkpoint。

### 验证与回滚

- `cd apps/backend && poetry run pytest -q`
- `cd apps/backend && poetry run ruff check .`
- `cd apps/backend && poetry run black --check .`
- `cd apps/backend && poetry run alembic upgrade head`
- 每个任务完成后提交独立 checkpoint；数据库回滚前停止 Worker 并备份。

**回滚：**

代码回滚按 checkpoint 逐步回退；数据库回滚使用 `20260725_0008_conversation.py` 的 downgrade，必须先停止 Worker 并确认没有正在写入 Conversation 的请求。由于本期不引入 checkpointer，不需要处理 Graph checkpoint 数据迁移。
