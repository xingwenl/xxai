# 本地全栈容器化运行调研记录

## 调研问题

- 如何让前端、FastAPI、Celery Worker、Redis 和 PostgreSQL 使用同一套本地启动方式？
- 如何保证 API 上传的文件可以被 Worker 读取？
- 如何让浏览器通过前端入口访问后端 API，而不暴露 Docker 内部服务名？
- 如何在本地使用开源 embedding，避免知识库入库依赖 OpenAI API Key？

## 参考来源

### 来源 1：Docker Compose 官方文档

- 链接：https://docs.docker.com/compose/how-tos/startup-order/
- 调研日期：2026-08-03
- 核心做法：服务通过 Compose 网络使用服务名通信；`healthcheck` 和 `depends_on.condition` 用于表达依赖服务的可用状态。

### 来源 2：Celery 官方文档

- 链接：https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html
- 调研日期：2026-08-03
- 核心做法：Worker 是独立进程，通过 Broker 消费任务；API 进程只负责发布任务，不应承担 Worker 生命周期。

### 来源 3：Docker 官方 Python/Node 容器实践

- 链接：https://docs.docker.com/guides/python/containerize/
- 链接：https://docs.docker.com/guides/nodejs/containerize/
- 调研日期：2026-08-03
- 核心做法：后端和前端分别以自己的构建上下文生成镜像，多阶段构建可以将前端构建产物交给轻量 Web 服务器托管。

### 来源 4：Ollama 官方 Docker 文档与 OpenAI 兼容接口文档

- 链接：https://docs.ollama.com/docker
- 链接：https://docs.ollama.com/api/openai-compatibility
- 链接：https://docs.ollama.com/capabilities/embeddings
- 调研日期：2026-08-03
- 核心做法：Ollama 可以作为独立 Docker 服务运行，通过持久化卷保存模型，并提供 `/v1/embeddings` OpenAI-compatible 接口；客户端需要传入 `api_key` 参数，但本地服务不校验其真实值。

### 来源 5：阿里云百炼 OpenAI 兼容模式文档

- 链接：https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope
- 调研日期：2026-08-03
- 核心做法：百炼提供 OpenAI-compatible API，Embedding 请求可使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`，通过 API Key 鉴权，模型名使用百炼控制台支持的 Embedding 模型。

### 来源 6：LlamaIndex `OpenAIEmbedding` 实现

- 链接：https://github.com/run-llama/llama_index/blob/main/llama-index-integrations/embeddings/llama-index-embeddings-openai/llama_index/embeddings/openai/base.py
- 版本：`llama-index-embeddings-openai 0.6.0`
- 调研日期：2026-08-04
- 核心做法：`model` 参数先按 `OpenAIEmbeddingModelType` 解析；`model_name` 参数可覆盖实际 query/text engine，因此第三方 OpenAI-compatible 模型名不能直接作为 `model` 传入。

## 方案比较

| 方案 | 优点 | 限制 | 结论 |
|---|---|---|---|
| 只把 Redis/Worker 加入现有后端 Compose | 改动小 | API 和前端仍依赖宿主机，地址与文件路径容易分叉 | 不采用 |
| 根目录 Compose，分别构建前后端，并统一编排 DB/Redis/API/Worker | 服务边界清晰，容器内地址稳定，前端与 API 可通过 Nginx 同源访问，文件可用共享卷传递 | 需要新增两个 Dockerfile 和 Nginx 配置 | 采用 |
| 一个镜像同时启动 API 和 Worker | 镜像数量少 | 进程生命周期、扩缩容和日志混在一起，Worker 无法独立重启 | 不采用 |
| 宿主机安装本地 embedding 服务 | 调试直观 | 宿主机依赖、端口和容器网络地址不一致，部署步骤不可复用 | 不采用 |
| Compose 增加 Ollama 服务，并复用现有 OpenAI-compatible 客户端 | 本地模型与业务服务一起启动，模型数据可持久化，业务代码改动小 | 首次下载模型需要额外磁盘和时间，模型维度需按实际模型配置 | 采用 |
| 使用阿里云百炼远程 Embedding | 不占用本机模型内存，中文模型和服务由云端维护 | 需要 API Key、网络和按量计费；依赖云服务可用性 | 支持，按需选择 |

## 最终决策

- 在仓库根目录新增 `docker-compose.yml`，统一编排 `db`、`redis`、`api`、`worker` 和 `front`。
- 后端 API 和 Worker 复用同一个后端镜像，但使用不同启动命令。
- API 与 Worker 共享 `agent_storage` volume，确保文件导入任务读取同一份上传文件。
- 前端使用 Vite 生产构建和 Nginx 托管；Nginx 将 `/api/` 和 WebSocket 路径代理到 `api` 服务。
- Compose 内部配置使用 `db` 和 `redis` 服务名，宿主机访问仅暴露前端、API、数据库和 Redis 的必要端口。
- 增加 `ollama` 服务和持久化 `ollama_data` 卷；Worker 使用 `http://ollama:11434/v1` 访问本地 embedding。
- 不在 Compose 中硬编码具体模型和向量维度；首次拉取模型后通过接口查询实际维度，再填写知识库配置。
- 支持阿里云百炼 OpenAI-compatible Embedding；API Key 存入已有加密字段，模型名通过 `model_name` 传给第三方服务。
- 对任意不属于 LlamaIndex OpenAI 模型枚举的配置模型名，使用合法内部模型作为 `model`，通过 `model_name` 保留实际请求模型名；这样不依赖 Base URL 的精确识别。

## 剩余风险

- 真实镜像构建需要 Docker 可用并能访问镜像仓库。
- 前端全量 TypeScript 构建存在已有基线错误，需要在验证记录中区分本次容器化问题和既有问题。
- 生产环境仍需替换开发密钥、数据库密码和 Embed 配置；本次只提供本地运行编排。
- Ollama 模型首次下载需要执行 `docker compose exec ollama ollama pull <模型名>`；不同模型的向量维度不同，配置错误会导致入库校验失败。
