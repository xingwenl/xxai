# Skill 脚本执行器验证记录

## 当前状态

- 阶段：acceptance，验证已完成。
- 结果：实现和范围内验证通过；前端全量构建仅被本任务范围外的 Agent 页面既有类型错误阻塞。

## 已执行命令

| 命令 | 预期结果 | 实际结果 |
|---|---|---|
| `sed -n '1,280p' docs/harness/backend.md` | 读取 FastAPI 后端规范 | 通过 |
| `rg ... apps/backend/app/modules/host_tool apps/backend/app/modules/mcp` | 识别现有工具审计与状态机能力 | 通过 |
| `sed -n ... docker-compose.yml apps/backend/Dockerfile` | 识别现有 API、Celery 和存储部署边界 | 通过 |
| `curl -L -s https://docs.docker.com/engine/security/` | 获取 Docker 官方安全边界依据 | 通过 |
| `curl -L -s https://docs.docker.com/engine/containers/resource_constraints/` | 获取 Docker 官方资源限制依据 | 通过 |
| `curl -L -s https://docs.python.org/3/library/subprocess.html` | 获取结构化子进程调用依据 | 通过 |
| `curl -L -s https://cheatsheetseries.owasp.org/...` | 获取命令注入防护依据 | 通过 |
| `poetry run pytest tests/skill_runner tests/skill tests/conversation tests/gateway -q` | 验证 runner、权限、审计路由、对话与 Gateway 工具路由 | 通过，`63 passed, 1 skipped` |
| `poetry run ruff check ...` | 检查本次后端、runner、迁移和测试代码 | 通过，`All checks passed` |
| `pnpm exec eslint src/api/skills.ts src/features/skills/index.tsx` | 检查 Skill 前端代码 | 通过 |
| `pnpm exec prettier --check src/api/skills.ts src/features/skills/index.tsx` | 检查 Skill 前端格式 | 通过 |
| `docker compose config --quiet` | 校验 Compose 配置 | 通过 |
| `poetry run alembic upgrade head` | 应用执行审计与存储键纠正迁移 | 通过，数据库升级至 `20260804_0016` |
| `select id, storage_key from skill_packages` | 核对既有包回填结果 | 通过，包 1 为 `skill-packages/1/1b81b736ee1a49f08c13fede04039c3b` |
| `docker compose build skill-runner` | 构建最小 runner 镜像 | 通过，镜像约 260 MB |
| `docker compose up -d --force-recreate skill-runner` | 启动最终 runner | 通过，容器状态 `healthy` |
| runner 真实签名 HTTP 探针 | 验证健康、签名、路径、超时与输出限制 | 通过：成功 200、错误签名 401、路径穿越 400、超时失败、输出截断 |
| `docker inspect ai-base-skill-runner-1 ...` | 核对实际隔离配置 | 通过：非 root、只读根、只读包挂载、全部 capability 丢弃、禁止提权、256 MB、0.5 CPU、64 PID |
| `docker network inspect ai-base_skill-runner-network` | 核对网络隔离 | 通过，`internal=true`，runner 不暴露宿主端口 |
| `docker compose -f docker-compose.yml -f docker-compose.dev.yml ...` + `curl http://127.0.0.1:8090/health` | 验证本地 Python API 调试入口 | 通过，开发覆盖仅发布本机 8090，健康检查返回 200 |
| `env -u SKILL_RUNNER_URL APP_ENV=development poetry run python ...` | 验证本地 Python API 未显式配置时的 runner 默认地址 | 通过，执行 `demo-skill/scripts/report.py` 返回 `succeeded`，输出 `alpha|beta` |
| `git diff --check` | 检查空白字符错误 | 通过 |
| `pnpm build` | 执行前端全量构建 | 未通过，仅命中 `src/features/agents/index.tsx` 既有表单泛型错误 |

## 关键验证结论

- 权限关闭时不生成脚本工具；执行服务调用前再次检查平台、智能体绑定、包、Skill、文件索引和包级权限。
- MCP 与 Skill Script 混合工具列表可正确路由，普通聊天、工具型 SSE 和 Embed Gateway 均接入执行回调。
- 审计 API 已注册并声明 Bearer 认证，执行参数仅保存脱敏占位符。
- 真实容器可运行包内 Python 脚本，路径穿越、错误签名、超时和大输出限制均生效。
- runner 实际环境无数据库、Redis、Docker Socket 或宿主可写包目录。

## 失败项与例外

- 前端全量 `pnpm build` 被 `src/features/agents/index.tsx` 第 625 行起的既有 React Hook Form 泛型错误阻塞；本次修改的 `skills.ts` 和 Skill 页面已分别通过 ESLint 与 Prettier。
- Gateway 测试中 1 项因测试环境条件跳过，与 Skill Script 变更无关。
- FastAPI `TestClient` 输出一条上游弃用警告，不影响本次结果。
