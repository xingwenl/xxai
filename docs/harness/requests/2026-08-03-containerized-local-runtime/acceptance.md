# 本地全栈容器化运行验收记录

## 当前结论

- 配置层验收通过：根目录 Compose、前后端镜像文件、Nginx 代理和共享存储卷已完成。
- Embedding 配置层验收通过：百炼远程 Embedding 不再依赖 Ollama；本地 Ollama 仍可通过 `local-embedding` profile 按需启用。
- 代码层验收通过：前端 Vite 产物构建和 Celery 任务注册检查通过。
- 百炼模型名 Bugfix 验收通过：`text-embedding-v3` 等非 LlamaIndex OpenAI 枚举模型通过 `model_name` 传递，不再在 `OpenAIEmbedding` 构造阶段报错。
- 路径修复验收通过：Worker 可将历史主机绝对 `storage_path` 重定位到当前容器存储根目录，Compose 使用宿主 `apps/backend/storage` 绑定目录共享上传文件。
- 运行层验收暂未完成：Docker Hub 拉取基础镜像超时，尚未完成真实容器启动和知识库文档消费。

## 验收标准对照

- [x] Compose 包含数据库、Redis、API、Worker 和前端服务。
- [x] API 与 Worker 使用同一数据库、Redis 配置和文件存储卷。
- [x] 混合运行场景下，Worker 能解析主机绝对路径并访问绑定存储目录中的上传文件。
- [x] 前端通过 Nginx 代理 API，并支持单页路由回退。
- [x] `knowledge.ingest_document` 任务注册成功。
- [x] Ollama 服务配置、模型持久化卷和本地端点凭证兼容逻辑已完成。
- [x] 阿里云百炼 `text-embedding-v3` 不再因 `OpenAIEmbeddingModelType` 枚举校验失败。
- [x] Compose 自动拉取默认 embedding 模型，API/Worker 等待模型初始化完成。
- [ ] 五个服务真实启动并通过健康检查。
- [ ] 上传 `agent-sdk-flow.md` 后由 Worker 消费并完成状态流转。

## 剩余风险

- 需要在 Docker Hub 网络可用后重新执行镜像构建和 `docker compose up -d`。
- `embeddinggemma` 在当前 Ollama 环境中 runner 返回 EOF；已将默认模型切换为 `nomic-embed-text`，需要重新启动并验证模型实际向量维度。
- 前端完整 TypeScript 检查仍有既有基线错误，当前不影响 Vite 产物构建，但需要另行治理。
