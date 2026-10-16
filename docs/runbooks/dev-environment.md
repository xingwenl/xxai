# 开发环境重置与种子手册

本文说明如何把本地开发环境恢复成「可登录、可对话、带样例对象」的状态，以及这套恢复为什么可靠。
对应的 request 是 `docs/harness/requests/2026-10-16-dev-env-seed/`。

## 一句话用法

```bash
# 前置：docker compose 全栈已起（db / redis / api）
bash apps/backend/scripts/reset_dev_db.sh
```

执行完用 `admin` / `admin123456` 登录 <http://localhost:8080> 即可。

这条命令会**不可逆地**做四件事：清空开发库全部数据（保留 `alembic_version`，自增序号复位）、清空
`apps/backend/storage/` 下的全部派生态文件、对 Redis DB 0 执行 `FLUSHDB`、重新灌入种子。不要在生产环境跑。

## 重置之后有什么

| 对象 | 值 | 由来 |
| --- | --- | --- |
| 平台 | 开发平台（`code=dev-platform`，id=1） | `platform/services.py create_platform`，顺带写入 `platform_admins` |
| 管理员 | `admin` / `admin123456`，email `admin@example.com` | `user/services.py create_user`；密码可用 `SEED_ADMIN_PASSWORD` 覆盖 |
| Agent | 开发助手（`slug=dev-assistant`，id=1） | `agent/services.py create_agent` + `create_agent_version` + `publish_agent_version` |
| 内置工具 | `ask_user`、`get_runtime_info`、`http_get` | `builtin_tool/repositories.py set_binding` |
| 技能包 | `dev-sample-skill`（含 SKILL.md + reference.md 两个文件） | `skill/services.py import_skill_package`，已绑定给 Agent |
| MCP 配置 | 开发样例 MCP（`endpoint_url=https://example.com/mcp`） | `mcp/services.py create_mcp_server`，只写配置，未同步工具 |
| 工作流 | 开发助手单步流程（`status=active`，单个 agent 步骤） | `workflows/services.py create_workflow` |
| Embed Client | 沿用 `.env` 里的 `EMBED_CLIENT_ID` | `embed/repositories.py create_client`，`secret_hash` 由 `EMBED_CLIENT_SECRET` 现算 |

「可对话」的硬条件是 `platform_admins` 有一行、`agents.default_version_id` 非空、且该版本 `published_at`
非空 —— 三者必须同时成立，所以种子走的是发布服务而不是直插 ORM。

## 只灌种子，不重置

```bash
# 库结构已就绪时，单独重跑种子是幂等的：不会产生第二份数据
docker compose run --rm --no-deps \
  -v "$PWD/apps/backend/scripts:/app/scripts:ro" \
  api python -m scripts.seed_dev_env
```

两个细节：

- 必须用 `python -m scripts.seed_dev_env`。直接跑 `python scripts/seed_dev_env.py` 时 `sys.path[0]` 是
  `/app/scripts`，`import app` 会 `ModuleNotFoundError`。
- 必须把 `scripts/` 只读挂进容器。api 镜像不挂载源码（代码来自镜像里的 `COPY . .`），新写的种子脚本不挂载就看不见。

脚本会拒绝在 `APP_ENV=production` 下执行。

## reset 脚本的其他选项

```bash
bash apps/backend/scripts/reset_dev_db.sh --rebuild    # 额外 DROP SCHEMA public → alembic upgrade head（换一份全新库结构）
bash apps/backend/scripts/reset_dev_db.sh --no-seed    # 只清空，不灌种子
bash apps/backend/scripts/reset_dev_db.sh --local      # 用 apps/backend/.venv 跑种子，而不是走容器
```

所有数据库与 Redis 操作都在容器内执行，用的是容器自己的 `POSTGRES_USER` / `POSTGRES_DB`。这是刻意的：
宿主机 `apps/backend/.env` 与仓库根 `.env` 是两套配置，在宿主机上拼连接串容易「清的不是正在跑的那个库」。

## 为什么可以随时清库

前提是**数据库里没有唯一副本**：

- 平台、管理员、Agent、工作流、MCP 配置、内置工具绑定全部由 `apps/backend/scripts/seed_dev_env.py`
  声明式重建，改动即提交进仓库。
- 技能包的源文件在仓库里（`apps/backend/scripts/seed_data/skills/<slug>/`）。数据库只存落库后的元数据，
  实体文件在 `apps/backend/storage/skill-packages/`，属于数据库行的派生态，所以清库时一并清掉。
- `EMBED_CLIENT_ID` 被写死成 `.env` 里的值（`client_id` 在模型上是普通列），清库后 `.env` 不用改。

验证这套说法的方式是跑一次官方验证脚本：

```bash
bash tools/harness/verify.sh 2026-10-16-dev-env-seed
```

它会连续两次完整重置并比对 13 张表的对象指纹，指纹不变才算通过。

## 已知边界

- **两个 `.env` 是漂移源**：`docker compose` 读仓库根 `.env`，宿主机裸跑读 `apps/backend/.env`。
  `apps/backend/.env.example` 只列宿主机直跑需要的项，并标注了这一点。
- **仓库根 `.env.example` 里留有真实凭据**（`EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / 数据库口令）。
  本次未改动它，需要用独立 request 处理。
- **MCP 工具同步不上**：`endpoint_url` 是占位地址，管理台点「同步工具」会失败，属预期；要真正可调用，
  需要换成可连通的端点，`mcp_tools` 只能由 `sync_mcp_tools` 连接端点生成。
- **技能 slug 会退化**：包 slug 由名称 `slugify` 得到，中文名会退化成 `skill`。所以种子包名保持 ASCII，
  技能名仍是中文（`开发示例技能`，slug 为 `skill`）。
- **真实对话需要模型凭据**：种子不持有密钥，`model_base_url` / `api_key` 留空表示继承运行栈的
  `OPENAI_BASE_URL` / `OPENAI_API_KEY`。本机 relay 余额不足时对话会失败；此时可用
  `tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py` 起一个本地假模型做链路验证。
- **`EMBED_AGENT_ID` 要跟种子 Agent 的 id 对齐**：`TRUNCATE ... RESTART IDENTITY` 让 id 复位到 1，
  正常情况下与默认 `.env` 一致；不一致时种子脚本会打印告警。
