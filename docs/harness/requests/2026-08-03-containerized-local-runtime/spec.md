# 本地全栈容器化运行规格

## 目标

- 通过仓库根目录的 Docker Compose 启动前端、FastAPI、Celery Worker、Redis 和 PostgreSQL。
- 通过同一套 Compose 启动可选的本地 Ollama embedding 服务，知识库不必依赖 OpenAI API Key。
- 支持配置阿里云百炼 OpenAI-compatible Embedding，使用云端 API Key 时不依赖本地 Ollama 模型。
- 使知识库文件上传后，Worker 能够消费 `knowledge.ingest_document` 任务并读取上传文件。
- 让浏览器通过前端统一入口访问 API 和 WebSocket。

## 范围

- 新增后端 Dockerfile，安装 `poetry.lock` 锁定的主依赖。
- 新增前端 Dockerfile，执行 Vite 构建并使用 Nginx 托管静态资源。
- 新增 Nginx 配置，代理 `/api/` 和 WebSocket 请求到 API 服务，并支持前端 history fallback。
- 新增根目录 `docker-compose.yml`，编排 `db`、`redis`、`api`、`worker` 和 `front`。
- Compose 将 `ollama` 服务和自动拉取模型的 `ollama-init` 一次性服务放入 `local-embedding` 可选 profile；启用本地模型时 Worker 通过 `http://ollama:11434/v1` 访问其 OpenAI-compatible embedding API。
- API 启动前执行 Alembic 迁移；Worker 与 API 共享环境变量和文件存储卷。
- 保留 `apps/backend/docker-compose.yml` 作为历史入口前，需避免两个 Compose 文件产生相互矛盾的默认端口；根目录 Compose 作为唯一推荐入口。

## 非目标

- 不修改业务 API 契约、数据库模型和 Celery 任务逻辑。
- 不处理生产密钥管理、镜像发布和 Kubernetes 部署。
- 默认由 `ollama-init` 自动拉取 `nomic-embed-text`；可通过 `OLLAMA_EMBEDDING_MODEL` 更换模型，向量维度仍需按实际模型确认。
- 不修复前端已有的全量 TypeScript 基线错误。

## 运行约束

- Compose 内 API/Worker 连接 `postgresql+asyncpg://...@db:5432/...`。
- Compose 内 API/Worker 连接 `redis://redis:6379/0`。
- 前端使用相对 API 基础路径 `/api/v1`，浏览器不直接解析 Docker 服务名。
- API 和 Worker 挂载同一个 `agent_storage` volume 到 `/app/storage`。
- Ollama 使用独立持久化卷保存模型；知识库配置使用模型实际返回的向量维度。
- 使用百炼远程 Embedding 时，API/Worker 不启动 Ollama；使用本地模型时通过 `docker compose --profile local-embedding up -d` 启用 Ollama 和自动拉模服务。
- PostgreSQL 默认以 external volume 复用旧 Compose 的 `backend_postgres_data` volume；如需新库，必须显式修改 `POSTGRES_VOLUME_NAME` 并提前创建卷，不得通过 `down -v` 隐式删除旧数据。

## 验收标准

- `docker compose config` 可以成功渲染根目录 Compose。
- Compose 服务包含 `db`、`redis`、`api`、`worker`、`front`，并具备必要健康检查或依赖关系。
- 后端镜像启动命令可分别运行 FastAPI 和 Celery Worker。
- 前端镜像成功生成静态资源，Nginx 配置包含 API、WebSocket 代理和 SPA fallback。
- Worker 镜像能够加载并注册 `knowledge.ingest_document`。
- API/Worker 使用同一个存储卷，数据库和 Redis 使用容器服务名通信。
- Ollama 服务可启动并被 Worker 通过 Compose 服务名访问；本地端点无 API Key 时使用兼容占位 key，远程 OpenAI 端点缺 key 仍明确失败。
- 百炼端点可使用自定义模型名并携带知识库 API Key 发起 embedding 请求。

## 变更记录

### 2026-08-04 第 10 次变更（fix）

- 变更原因：使用阿里云百炼模型名 `text-embedding-v3` 时，部分配置会将第三方模型名直接传给 LlamaIndex 的 `model` 参数，触发 `OpenAIEmbeddingModelType` 枚举校验错误。
- 变更内容：不再根据 Base URL 判断是否使用自定义模型名；凡是不属于 LlamaIndex OpenAI 模型枚举的模型值，统一使用合法内部模型作为 `model`，并通过 `model_name` 传递实际第三方模型名。
- 影响章节：运行约束、验收标准、风险。
- 是否触发人工确认：否，属于既有 OpenAI-compatible embedding 适配逻辑的局部 bug 修复，不修改架构边界、数据模型、API 契约或权限语义。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-03 第 9 次变更

- 变更原因：使用百炼远程 Embedding 时不应因本地 Ollama 模型导致额外内存占用或启动失败。
- 变更内容：将 Ollama 与自动拉模服务改为 `local-embedding` 可选 profile，默认 Compose 启动不再依赖 Ollama。
- 影响章节：范围、运行约束、运行方式。
- 是否触发人工确认：否，属于本地 embedding 运行方式的配置优化。
- 关联计划更新：已同步更新 `verify.md`。

### 2026-08-03 第 8 次变更

- 变更原因：用户选择使用阿里云百炼的通义 Embedding API，避免本地 Ollama 模型占用 Docker 内存。
- 变更内容：识别 `dashscope.aliyuncs.com` OpenAI-compatible 地址，并通过 `model_name` 支持 `text-embedding-v3` 等百炼模型；补充官方来源和配置说明。
- 影响章节：目标、范围、验收标准、方案比较。
- 是否触发人工确认：否，未改变数据库字段、API 契约或权限语义。
- 关联计划更新：已同步更新 `verify.md`。

### 2026-08-03 第 7 次变更

- 变更原因：用户不希望每次启动后手动执行 `ollama pull` 维护模型。
- 变更内容：增加 `ollama-init` 一次性 Compose 服务，等待 Ollama 健康后自动拉取 `OLLAMA_EMBEDDING_MODEL`，API/Worker 等待初始化成功。
- 影响章节：范围、运行约束、验收标准、运行方式。
- 是否触发人工确认：否，属于既有本地运行编排的启动自动化。
- 关联计划更新：已同步更新 `verify.md`。

### 2026-08-03 第 6 次变更

- 变更原因：Ollama 模型名 `embeddinggemma` 不属于 LlamaIndex 的 `OpenAIEmbeddingModelType`，导致本地 embedding 在请求前构造失败。
- 变更内容：本地 OpenAI-compatible 端点使用合法的内部模型枚举，并通过 `model_name` 将 Ollama 实际模型名传入请求；远程 OpenAI 端点保持原有校验。
- 影响章节：验收标准、风险。
- 是否触发人工确认：否，属于既有本地 embedding 适配逻辑的 bug 修复。
- 关联计划更新：已同步更新 `verify.md`。

### 2026-08-03 第 5 次变更

- 变更原因：用户要求支持在 Docker 中运行本地开源 embedding，避免必须申请 OpenAI Embedding API Key。
- 变更内容：增加 Ollama Compose 服务、持久化模型卷和本地端点凭证兼容逻辑；补充官方调研、模型拉取与维度配置说明。
- 影响章节：目标、范围、运行约束、验收标准、风险。
- 是否触发人工确认：是，涉及本地运行架构边界；用户已明确要求继续实施。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-03 第 4 次变更

- 变更原因：知识库文档入库生成 Embedding 时，Worker 未获得 OpenAI 凭证，导致 `Missing credentials`。
- 变更内容：根目录 Compose 为 API 与 Worker 透传 `OPENAI_API_KEY` 和可选 `OPENAI_BASE_URL`；`.env.example` 增加对应占位。
- 影响章节：运行约束、验收标准。
- 是否触发人工确认：否，未改变架构边界、数据模型、API 契约或权限语义。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-03 第 3 次变更

- 变更原因：后端容器日志需要落到本机，便于本地排查 API/Worker 运行问题。
- 变更内容：为 API 与 Worker 显式配置 `LOG_FILE_PATH=/app/logs/app.log`，并将 `/app/logs` 绑定到宿主 `apps/backend/logs`。
- 影响章节：范围、运行约束、验收标准。
- 是否触发人工确认：否，未改变架构边界、数据模型、API 契约或权限语义。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-03 第 2 次变更

- 变更原因：本地 API 与容器 Worker 混合运行时，知识库文件路径写入了主机绝对路径，Worker 无法直接访问。
- 变更内容：Worker 读取文件时按当前存储根目录重定位历史绝对路径；根目录 Compose 改为绑定主机 `apps/backend/storage`，保证同一份文件可被宿主与容器共享。
- 影响章节：运行约束、验收标准。
- 是否触发人工确认：否，未改变数据模型、API 契约或权限语义。
- 关联计划更新：已同步更新 `plan.md`。

### 2026-08-03 第 1 次变更

- 变更原因：知识库文档长期停留在 `pending`，缺少统一启动的 Redis 和 Celery Worker。
- 变更内容：将前端、API、Worker、Redis 和 PostgreSQL 纳入根目录 Compose。
- 影响章节：范围、运行约束、验收标准。
- 是否触发人工确认：是，涉及本地运行架构边界；用户已明确要求全部放入 Compose。
