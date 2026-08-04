# Skill 脚本执行器实施计划

## 变更文件

- 新增 `apps/backend/app/modules/skill_runner/`：内部 runner 客户端、请求签名、工具描述和结果 schema。
- 新增 `apps/backend/runner/`：最小 HTTP runner 服务、路径校验、解释器白名单、进程组超时与输出截断。
- 新增 `apps/backend/Dockerfile.runner`：包含 Python、Node.js 和 POSIX shell 的非 root 运行镜像。
- 修改 `docker-compose.yml`：新增内部 runner 服务、专用网络、只读技能包挂载、tmpfs 和资源/安全限制。
- 修改 `apps/backend/app/core/config.py`：增加 runner URL、共享密钥、超时和输出限制配置。
- 修改 `apps/backend/app/modules/skill/models.py`：新增 `storage_key` 与 `SkillScriptExecution`，所有新增字段带中文 `comment`。
- 新增 Alembic 迁移：创建执行审计表并回填现有技能包 `storage_key`。
- 修改 `apps/backend/app/modules/skill/repositories.py`：查询允许运行的脚本、创建与完成审计、分页查询审计。
- 修改 `apps/backend/app/modules/skill/services.py`：执行授权、参数校验、审计状态和 runner 调用编排。
- 修改 `apps/backend/app/modules/conversation/runtime.py`、`services.py`、路由准备逻辑：把 Skill Script 工具加入运行时并路由 invoke 回调。
- 修改 `apps/backend/app/modules/skill/router.py`、`schemas.py`：新增执行审计查询接口与响应模型。
- 修改 `apps/front/src/api/skills.ts`、`features/skills/index.tsx`：runner 状态、脚本信息和执行审计界面。
- 新增/修改 `apps/backend/tests/skill_runner/`、`tests/skill/`、对话运行时测试：覆盖权限、路径、执行限制、审计和工具路由。

## 数据流

1. 运行时加载智能体已绑定 Skill，并筛选 `allow_script_execution=true` 的技能包。
2. 为每个包生成结构化脚本工具，模型仅能选择索引中允许的脚本路径。
3. invoke 回调再次校验平台、智能体、绑定、包权限、脚本索引和参数，创建 `requested/running` 审计。
4. API 使用签名内部请求调用 runner；runner 将 `storage_key + script_path` 解析到只读包目录，拒绝越界和符号链接。
5. runner 用固定解释器参数数组启动进程，在临时工作目录执行，超时终止进程组，并截断输出。
6. API 将成功或失败写入审计，再把结构化结果作为 ToolMessage 返回模型。

## 实施步骤

1. 等待人工确认 runner 架构、审计模型、API 与真实权限语义。
2. 先定义 runner 内部协议、签名校验和执行限制常量，补纯函数测试。
3. 实现 `storage_key` 与执行审计模型、迁移、仓储层和 schema。
4. 实现独立 runner 服务、非 root 镜像及路径/解释器/资源限制。
5. 实现 API runner 客户端、授权编排和审计状态写入。
6. 将 Skill Script 工具接入 conversation、SSE 和 Embed Gateway 工具调用链，保持 MCP/Host Tool 路由兼容。
7. 实现审计查询 API 与前端展示、runner 状态提示。
8. 执行单元测试、真实 Compose runner 探针、恶意路径/超时/大输出测试、前端静态检查。
9. 更新 `verify.md`、`acceptance.md` 和 `meta.json`。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/skill_runner tests/skill tests/conversation -q`
- `cd apps/backend && poetry run ruff check app/modules/skill_runner app/modules/skill app/modules/conversation tests/skill_runner tests/skill`
- `docker compose config`
- `docker compose build skill-runner api`
- 使用 fixture 包验证 Python、Node.js、shell 成功执行。
- 验证权限关闭、索引外路径、`../`、符号链接、不支持扩展名、参数超限、超时、无限输出和非零退出码。
- 检查 runner 容器用户、capabilities、挂载、网络和环境变量，不得出现数据库、Redis、Docker Socket。
- `cd apps/front && pnpm exec eslint src/api/skills.ts src/features/skills/index.tsx`
- `cd apps/front && pnpm exec prettier --check src/api/skills.ts src/features/skills/index.tsx`

## 回滚说明

- 先从运行时工具列表移除 Skill Script 工具并停用 runner 服务，即可立即停止脚本执行。
- 回滚前端审计入口、API 路由、服务和 runner 文件后，再回滚数据库迁移。
- 保留既有 `allow_script_execution` 字段不影响 Zip 导入；回滚后它恢复为授权预留状态。
- 执行审计属于安全证据，生产环境回滚前应先导出或按保留策略处理，不应直接无记录删除。

## 人工确认点

- 确认新增专用 runner 容器，而不是 API/Celery 进程内直接执行。
- 确认首期固定支持 Python、Node.js、POSIX shell，禁止动态安装依赖和任意出网。
- 确认管理员开启包权限即允许模型自动调用，不增加逐次人工确认。
- 确认新增 `storage_key`、执行审计表和管理员审计查询 API。
