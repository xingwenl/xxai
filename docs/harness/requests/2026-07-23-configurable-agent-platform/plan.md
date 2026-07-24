# 可配置多平台 AI Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 FastAPI 后端实现多平台可配置 Agent 第一阶段。

**Architecture:** 模块化 FastAPI 单体，直接使用 LangGraph、LlamaIndex、官方 MCP SDK；PostgreSQL + pgvector 保存知识库，Celery + Redis 处理异步导入。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、LangGraph、LlamaIndex、MCP SDK、Celery、Redis、pgvector、httpx、cryptography。

---

### 任务 0：依赖与配置

- [ ] 更新 `pyproject.toml` 和 `poetry.lock`。
- [ ] 增加模型、Redis、文件存储、抓取和加密配置。
- [ ] 添加依赖烟囱测试，运行全量 pytest、ruff 和 black。

### 任务 1：平台隔离

- [ ] 新增平台、平台管理员模型、迁移、仓储、服务和 API。
- [ ] 平台创建者自动成为管理员。
- [ ] 添加跨平台访问失败测试。

### 任务 2：Agent 配置

- [ ] 新增 Agent 草稿和不可变发布版本。
- [ ] 使用 LangGraph/LangChain OpenAI 客户端构造聊天模型。
- [ ] 增加 Fernet 密钥加密、发布和回滚测试。

### 任务 3：知识库

- [ ] 新增知识库、文档、切片、向量和导入任务模型。
- [ ] 使用 LlamaIndex 处理文件解析、切片、embedding 和检索。
- [ ] 使用 Celery + Redis 异步导入，加入 URL SSRF 防护。
- [ ] 返回文档标题、来源 URL 和命中片段。

### 任务 4：Skill、任务 5：MCP、任务 6：对话与 SSE

- [ ] 实现配置式 Skill 和绑定。
- [ ] 实现远程 MCP、工具白名单、副作用确认和审计。
- [ ] 实现 LangGraph 对话流程、引用和 SSE 事件。

### 验证与回滚

- `cd apps/backend && poetry run pytest -q`
- `cd apps/backend && poetry run ruff check .`
- `cd apps/backend && poetry run black --check .`
- `cd apps/backend && poetry run alembic upgrade head`
- 每个任务完成后提交独立 checkpoint；数据库回滚前停止 Worker 并备份。
