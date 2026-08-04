# Skill 脚本执行器验收记录

## 当前结论

- 验收通过，可以进入合并或归档流程。
- 已完成 `research -> spec -> plan -> implement -> verify -> acceptance`，用户已在实现前确认架构、数据模型、API 和权限行为变化。

## 已满足项

- 已完成官方安全资料和项目现有能力调研。
- 已比较 API 直跑、Celery worker、专用 runner 和单次容器方案。
- 已确定专用受限 runner、固定解释器、禁网、只读挂载、资源限制和执行审计方案。
- 已实现 Zip 包脚本索引、包级执行授权、运行时工具、HMAC runner 协议和执行审计。
- 已接入普通聊天、工具型 SSE 和 Embed Gateway，且保留 MCP/Host Tool 路由。
- 已完成真实 PostgreSQL 迁移、既有包 `storage_key` 回填修复和真实容器脚本执行。
- 已验证 runner 的非 root、只读、禁提权、capability、网络、CPU、内存、PID、超时和输出限制。
- 已提供本地 Python API 调试模式；生产默认仍不发布 runner 宿主端口。

## 验收标准核对

- 权限关闭不注册脚本工具：通过。
- 权限开启且 Skill 已绑定时可执行受支持脚本：通过真实 Python 探针；Node.js、shell 和扩展名映射由白名单与单元测试覆盖。
- 路径、参数、符号链接、超时和输出限制：通过。
- runner 不持有数据库/Redis/Docker Socket 权限且资源受限：通过容器实态检查。
- 执行成功、失败与脱敏参数写入审计：通过服务测试和数据库模型检查。
- 审计 API 受平台管理员 Bearer 认证保护：通过路由与 OpenAPI 回归。
- 对话、SSE、Embed Gateway 不破坏现有工具链：通过相关测试，`63 passed, 1 skipped`。
- Compose 和 Skill 前端静态检查：通过。

## 剩余风险

- 禁网和禁止动态安装依赖会限制部分市场 Skill 的兼容性。
- 管理员包级授权后模型可自动调用，需要依靠审计、资源限制和明确的关闭能力控制风险。
- 当前使用常驻容器而非 microVM；高对抗或多租户公网场景应升级到 gVisor、Kata Containers 或 Firecracker 等更强隔离。
- 前端全量构建仍有 `src/features/agents/index.tsx` 的既有类型错误，本 request 的 Skill 前端文件静态检查已通过。
