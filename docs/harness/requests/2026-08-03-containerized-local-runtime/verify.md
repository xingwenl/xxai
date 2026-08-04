# 本地全栈容器化运行验证记录

## 已完成检查

- `docker compose config`：通过；根目录 Compose 成功渲染 `db`、`redis`、`ollama`、`ollama-init`、`api`、`worker`、`front` 七个服务。
- `docker compose config --quiet`：通过。
- `docker compose config | rg -n "LOG_FILE_PATH|apps/backend/logs|/app/logs|apps/backend/storage|/app/storage"`：通过；API 和 Worker 均设置 `LOG_FILE_PATH=/app/logs/app.log`，并绑定宿主 `apps/backend/logs` 到 `/app/logs`。
- `docker compose config | rg -n "OPENAI_API_KEY|OPENAI_BASE_URL"`：通过；API 和 Worker 均包含 OpenAI 凭证环境变量入口。当前本地 `.env` 未填实际值时渲染为空，需要人工配置后重启 Worker。
- `docker compose config --quiet`：通过；Ollama 与 `ollama-init` 配置为 `local-embedding` 可选 profile，默认 API/Worker 不依赖 Ollama。
- `cd apps/backend && poetry run pytest tests/knowledge/test_knowledge_services.py -q`：通过，19 passed；覆盖本地 Ollama 端点自动使用兼容占位 key，以及远程端点缺 key 时仍保留原始空凭证行为。
- 本地模型名兼容性回归：`build_embedding_model` 对 `embeddinggemma` 使用 `model_name` 绕过 OpenAI 模型枚举限制，并保留实际请求模型名；已由上述测试覆盖。
- 百炼模型名兼容性回归：`build_embedding_model` 对 `dashscope.aliyuncs.com` 使用 `model_name` 传递 `text-embedding-v3` 等第三方模型名；已由单测覆盖。
- Compose profile 核对：使用百炼远程 Embedding 时执行 `docker compose up -d`；需要本地模型时执行 `docker compose --profile local-embedding up -d`。
- `cd apps/backend && .venv/bin/python -m ruff check app/modules/knowledge/runtime.py tests/knowledge/test_knowledge_services.py`：通过。
- `cd apps/front && pnpm exec vite build`：通过，生成前端 `dist` 产物。
- `cd apps/backend && .venv/bin/python -c 'from app.modules.knowledge.tasks import celery_app; ...'`：通过，已注册 `knowledge.ingest_document`。
- 根目录 `docker-compose.yml` 静态核对：API 和 Worker 使用 `db`、`redis` 容器服务名，并共享绑定到 `/app/storage` 的 `apps/backend/storage` 目录；前端 Nginx 配置包含 `/api/` 代理和 SPA fallback。
- Docker volume 核对：本机存在旧卷 `backend_postgres_data`；根目录 Compose 已通过 `POSTGRES_VOLUME_NAME` 默认复用该卷，避免启动后切换到空数据库。

## 2026-08-04 百炼模型名 Bugfix 验证

- `cd apps/backend && poetry run pytest tests/knowledge/test_knowledge_services.py -q`：通过，`21 passed`；覆盖百炼 `text-embedding-v3` 在非固定 Base URL 下仍通过 `model_name` 传递，以及原生 OpenAI 模型枚举回归。
- `cd apps/backend && poetry run ruff check app/modules/knowledge/runtime.py tests/knowledge/test_knowledge_services.py`：通过。
- `cd apps/backend && poetry run python -c '...'`：通过；构造结果为 `model_name=text-embedding-v3`、`text_engine=text-embedding-v3`、`query_engine=text-embedding-v3`，未再触发 `OpenAIEmbeddingModelType` 校验错误。
- 方案核对：实现基于 `OpenAIEmbeddingModelType` 判断是否需要自定义模型名，不依赖 `dashscope.aliyuncs.com` 的精确域名匹配；未修改数据模型、API 契约和权限行为。

## 未完成检查

- `docker compose build api worker front`：失败。Dockerfile 已进入 Docker Desktop builder，但拉取 `python:3.12-slim` 时访问 Docker Hub token 超时：`DeadlineExceeded`。这是外部网络阻塞，不是 Compose 配置解析错误。
- 未执行 `docker compose up` 和真实 Worker 消费验证，因为镜像尚未构建完成。
- 已通过宿主机接口验证 `embeddinggemma` 会在 Ollama runner 阶段返回 EOF；默认模型已切换为 `nomic-embed-text`，需重新启动后验证真实 embedding 请求。
- 初始化服务使用 `/bin/sh -c` 覆盖 Ollama 镜像默认 entrypoint，避免将 `sh` 误解析为 Ollama 子命令。
- `cd apps/front && pnpm build`：仍受仓库既有 TypeScript 错误阻塞；容器构建暂使用 `pnpm exec vite build` 生成运行时静态产物，类型检查仍应单独修复。

## 运行方式

在 Docker Hub 网络可用后，于仓库根目录执行：

```bash
docker compose build
docker compose up -d
docker compose logs -f worker
```

前端入口为 `http://localhost:5173`。Worker 日志出现 `Task knowledge.ingest_document[...] received` 后，知识库文档会从 `pending` 进入 `processing`，完成后进入 `ready` 或 `failed`。后端文件日志会写入宿主 `apps/backend/logs`，容器内路径为 `/app/logs`。

## 2026-08-03 路径修复补充

现象：Worker 报错 `File /Users/lixingwen/xw/study/ai-base/apps/backend/storage/1/8f9b542d01c945bfb429971f5d373811.md does not exist.`，但宿主机 `apps/backend/storage/1/8f9b542d01c945bfb429971f5d373811.md` 实际存在。

结论：这是本地 API 与容器 Worker 混合运行时的路径空间不一致。已将 Compose 改为绑定宿主存储目录，并在 Worker 读取前将历史主机绝对路径重定位到当前 `AGENT_FILE_STORAGE_PATH`。
