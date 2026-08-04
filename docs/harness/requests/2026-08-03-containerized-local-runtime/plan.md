# 本地全栈容器化运行实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to execute this plan task-by-task.

**目标：** 使用根目录 Docker Compose 统一启动前端、API、Celery Worker、Redis 和 PostgreSQL。

**架构：** 后端 API 和 Worker 复用后端镜像但使用独立进程；前端使用多阶段构建和 Nginx，同源代理 API/WebSocket；上传文件通过绑定的 `apps/backend/storage` 目录在宿主、API 和 Worker 之间传递。

**技术栈：** Docker Compose、Python 3.12、Poetry、FastAPI、Celery、Redis、PostgreSQL、Node 22、Vite、Nginx。

## 2026-08-04 Bugfix 增量计划

- 修改 `apps/backend/app/modules/knowledge/runtime.py`，基于 `OpenAIEmbeddingModelType` 判断模型是否为 LlamaIndex 原生模型；第三方模型名统一通过 `model_name` 传递。
- 修改 `apps/backend/tests/knowledge/test_knowledge_services.py`，覆盖代理 Base URL 下的 `text-embedding-v3`，并保留原生 OpenAI 模型回归。
- 执行知识库服务测试和 Ruff 检查，确认不改变已有本地 Ollama 与 OpenAI 模型行为。
- 更新 `verify.md`、`acceptance.md` 和 `meta.json`，记录真实验证结果。

---

### 任务 1：新增后端镜像

**文件：**

- 新增：`apps/backend/Dockerfile`
- 新增：`apps/backend/.dockerignore`

- [ ] 使用 Python 3.12 slim 基础镜像，安装 Poetry 2.4.1。
- [ ] 先复制 `pyproject.toml` 和 `poetry.lock`，执行 `poetry install --only main --no-root`。
- [ ] 再复制后端源码，默认启动 `uvicorn main:app`。
- [ ] 排除 `.venv`、日志、运行时存储和缓存，避免污染构建上下文。

### 任务 2：新增前端生产镜像和代理

**文件：**

- 新增：`apps/front/Dockerfile`
- 新增：`apps/front/nginx.conf`
- 新增：`apps/front/.dockerignore`

- [ ] 使用 Node 22 安装 pnpm 并执行锁文件安装和 `pnpm build`。
- [ ] 将 `dist` 复制到 Nginx 镜像。
- [ ] 将 `/api/`、`/api/v1/ws/` 代理到 `api:8000`，其它路径回退到 `index.html`。

### 任务 3：新增根目录 Compose

**文件：**

- 新增：`docker-compose.yml`

- [ ] 定义 PostgreSQL、Redis、API、Worker 和 Front 服务。
- [ ] 为 PostgreSQL 和 Redis 添加健康检查。
- [ ] API 启动前执行 `alembic upgrade head`，Worker 使用 `celery -A app.modules.knowledge.tasks:celery_app worker --loglevel=INFO`。
- [ ] API 与 Worker 共享数据库、Redis、密钥和绑定到 `/app/storage` 的宿主存储目录。
- [ ] API 与 Worker 将 `/app/logs` 绑定到宿主 `apps/backend/logs`，并通过 `LOG_FILE_PATH` 写入本地日志文件。
- [ ] API 与 Worker 透传 `OPENAI_API_KEY` 和可选 `OPENAI_BASE_URL`，保留远程 OpenAI 配置能力。
- [ ] 增加 Ollama 服务和持久化模型卷；本地 Base URL 无 key 时传入兼容占位 key。
- [ ] 增加 `ollama-init` 一次性服务，自动拉取 `OLLAMA_EMBEDDING_MODEL`，并让 API/Worker 等待其成功完成。
- [ ] 补充本地模型维度查询和知识库配置步骤。
- [ ] 为前端构建注入 `VITE_API_URL=/api/v1`。
- [ ] Worker 读取文件前按当前 `AGENT_FILE_STORAGE_PATH` 重定位历史主机绝对路径。

### 任务 4：文档与验证记录

**文件：**

- 修改：`docs/harness/requests/2026-08-03-containerized-local-runtime/verify.md`
- 修改：`docs/harness/requests/2026-08-03-containerized-local-runtime/acceptance.md`
- 修改：`docs/harness/requests/2026-08-03-containerized-local-runtime/meta.json`

- [ ] 执行 `docker compose config`。
- [ ] 执行 `docker compose config --quiet`。
- [ ] 执行 `cd apps/backend && .venv/bin/python -m pytest tests/knowledge/test_knowledge_services.py -q`。
- [ ] 执行后端任务注册检查和前端构建检查。
- [ ] 若 Docker 环境可用，执行镜像构建和服务启动检查；否则记录阻塞证据。
