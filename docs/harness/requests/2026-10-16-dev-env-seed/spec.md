---
id: 2026-10-16-dev-env-seed
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["未命中 A/B 档的路径触发条件，属主动上调（分档只上调不下调）；上调理由：reset 脚本会对开发库执行 TRUNCATE、清空 storage、FLUSHDB，且种子会写入固定 client_id/secret 的 embed client", "需用户确认两点取舍：开发环境使用固定账号与固定密码；一条命令会不可逆清空本地库、storage 与 Redis DB 0"]
  grantedAt: 2026-10-16
  grantedBy: 用户（spec 交付后确认：「批准，开始实现」；并选定种子管理员密码来源为「读 SEED_ADMIN_PASSWORD，缺省用文档写明的开发默认值」）
---

## 目标与范围

- 一句话：给 ai-base 加「一条命令把开发环境从任意状态恢复成可登录、可对话、带样例技能包/工作流/MCP 配置」的能力，让「可以随时清库」真正成立。
- 给谁用：本机开发与联调（当前无生产数据，本地 compose 栈在跑：`ai-base-db-1` pgvector/pg17、`ai-base-redis-1`、`ai-base-api-1`、`ai-base-front-1`）。
- 做：声明式种子脚本；技能包源文件入仓并从仓库导入；清库+清磁盘+清 Redis+重新种子的一条命令；补全后端 `.env.example`；一页 runbook。
- **不做**：不做生产/预发种子（`APP_ENV=production` 时脚本拒绝执行）；不改表结构、不新增迁移、不改路由与鉴权语义；不从线上导入真实数据、不做脱敏；不新增「本地目录/任意 Git 源导入技能包」的 API。

## 来源与方案比较

- **Rails Guides《Active Record Migrations》v8.1.4**（<https://guides.rubyonrails.org/active_record_migrations.html>，页面标注 Version 8.1.4、Release notes 列 8.1 - October 2025）：目录把「Setting Up / Preparing / **Resetting** the Database」与第 8 章「**Migrations and Seed Data**」明确拆成两个独立动作——重置库与灌种子数据不是同一件事。调研日期 2026-10-16。→ 本方案采用「迁移与种子分离」：迁移仍归 `apps/backend/scripts/create_tables.sh`，种子只负责数据。
- **Laravel 12.x《Database: Migrations》**（<https://laravel.com/docs/12.x/migrations>，抓取 HTTP 200、标题确认为 12.x）：`migrate:fresh` 与 seeder 组合是「清库 + 种子一条命令」的成熟先例。调研日期 2026-10-16。→ 取它的「一条命令」体验，但默认**不重放迁移**（见下）。
- **仓库内先例 `apps/backend/scripts/seed_demo_host_tools.py`（153 行）**：已有「逐条 `select` → insert/update」的幂等 upsert 写法与 `get_session_factory()` 用法，本次沿用同一形态而不是引入新框架。
- 三个候选方案（A 选定 / B、C 被否决，理由见「被否决的选项」）：A 声明式幂等种子脚本；B 数据库快照（`pg_dump`/`pg_restore`）；C 扩展 `skill/source_resolver.py` 支持本地目录或 Git 源导入。
- 调研未改变方案的原因：现有服务层已能覆盖全部对象（`platform/services.py:6-13 create_platform` 自动写 `platform_admins`；`agent/services.py:44-49/52-66/110-119` 建 Agent、建版本、发布版本；`workflows/services.py:168-213 create_workflow`；`mcp/services.py:59-73 create_mcp_server`；`skill/services.py:48-58 import_skill_package`），直接复用即可，不需要新抽象。

## 被否决的选项

- **方案 B｜`pg_dump` / `pg_restore` 快照**：快照会把 uuid 化的 `storage_path` 绝对路径、`embed client` 的随机 `client_id` 与历史脏数据一起冻结；技能包实体文件在 `apps/backend/storage/`（`.gitignore:33` 未入库）不在快照里；无法在「库还在、只缺某个对象」时补种；schema 一变快照即失效。收益（状态完全一致）抵不过不可维护。
- **方案 C｜扩展 `skill/source_resolver.py` 支持本地目录或任意 Git 源导入**：`parse_source()` 目前只认 `github.com`（`skill/source_resolver.py:81-99`），放开本地路径等于给一个面向管理员的出网入口增加本地文件系统语义，属安全面变化，且要连带改 `skill/router.py` 与 `skill/schemas.py`（B 档扩到 API 契约）；而 `import_skill_package` 已是与管理台上传同一条落库链路，直接喂 zip bytes 即可，收益小于改动面与风险。
- **方案 D｜把 `tests/workflows/helpers.py:52 seed()` 提升为公共工厂供种子上线使用**：该 helper 面向内存 sqlite、依赖 pytest 事务与 `seed_seq`、不落 storage、不处理 `.env`/Redis/embed client；把测试脚手架变成环境种子依赖会污染测试边界，且「测试要的事务回滚」与「种子要的持久化」语义相反。

## 停点判断

- 是否涉及架构边界变化：否（不新建模块目录、不改服务职责边界，改动集中在 `apps/backend/scripts/`）。
- 是否涉及数据模型变化：否（不新增/修改表、字段、实体关系，不新增迁移）。
- 是否涉及 API 契约变化：否（不新增或修改路由、请求体、响应体）。
- 是否涉及鉴权或权限行为变化：否（只写入既有 `platform_admins` 归属行，「`platform_admins` 有行即平台管理员」的语义不变；`apps/backend/app/modules/tasks/router.py:39-54` 注释已定义该语义）。
- 是否缺少关键资料无法可靠比较方案：否（已读完 `create_tables.sh`、`migrations/env.py`、各模块模型与服务层、`embed/models.py`、`.env`/compose 配置、`tests/workflows/helpers.py`）。
- 结论：命中项为 0。按「拿不准按 B」与「分档只上调」主动定为 B 档并请求人工确认，`approval.required: true`：① 开发环境使用固定账号与固定密码（密码由 `SEED_ADMIN_PASSWORD` 提供，未提供时用文档写明的开发默认值）；② `reset_dev_db.sh` 会不可逆清空本地库、`apps/backend/storage/` 与 Redis DB 0。

## 变更点

- 新增 `apps/backend/scripts/seed_dev_env.py`：声明式、幂等的开发环境种子；复用服务层（`create_platform` / `create_agent` / `create_agent_version` / `publish_agent_version` / `create_mcp_server` / `create_workflow` / `import_skill_package` / `bind_skill`），不手写核心 ORM；`settings.app_env == "production"` 时直接拒绝执行。
- 新增 `apps/backend/scripts/seed_data/skills/<slug>/`：技能包源文件入仓（`SKILL.md` + 附属文件）；seed 在内存打包为 zip 后调用既有 `import_skill_package(repo, platform_id, filename=..., content=...)`，与管理员上传走同一条解析、落库、落盘链路（`skill/importers.py:56 parse_skill_package`、`:123-141 store_skill_package_files`）。
- 新增 `apps/backend/scripts/reset_dev_db.sh`：一条命令完成「TRUNCATE 全部业务表（动态枚举 `public` 下 `pg_tables`，保留 `alembic_version` 并用 `RESTART IDENTITY` 复位自增序号）→ 清 `apps/backend/storage/` 下全部派生态文件 → Redis `FLUSHDB` → 跑 seed」；DB/Redis 操作通过 `docker compose exec -T db|redis` 在容器内用其自身环境变量执行，避免宿主机 `apps/backend/.env` 与根 `.env` 两套变量漂移。
  - **实现期偏离 1**：`--rebuild` 最终实现为 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` + `docker compose run --rm --no-deps api alembic upgrade head`，而不是本文初稿写的 `create_tables.sh downgrade base && upgrade head`。理由：迁移链能从头重放由 38 个迁移脚本的 `down_revision` 保证，不必依赖各自的 `downgrade` 质量；`DROP SCHEMA` 语义等价于「一份全新库」。
  - **实现期偏离 2**：清磁盘最终清的是 `apps/backend/storage/` 下**全部**内容，而不是只清 `skill-packages` 与 `assets`。理由：该目录下所有内容都是数据库行的派生态（技能包解压目录、附件、知识库上传件），清库后只会变孤儿；逐目录列举在将来新增子目录时会漏。脚本内保留 `STORAGE_DIR == ${ROOT}/apps/backend/storage` 断言防误删。
- 种子写入的技能包/Agent/工作流与运行栈共享同一卷（`docker-compose.yml:127 ./apps/backend/storage:/app/storage`），seed 默认通过 `docker compose run --rm --no-deps -v "$PWD/apps/backend/scripts:/app/scripts:ro" api python -m scripts.seed_dev_env` 执行（api 镜像不挂载源码，只读挂载让种子脚本改动即时生效；必须用 `python -m`，否则 `import app` 失败），`--local` 时改用 `apps/backend/.venv/bin/python -m scripts.seed_dev_env`。
- 种子写入的 embed client 使用 `settings.embed_client_id` / `embed_client_secret` 作为固定 `client_id` 与 secret（`PlatformEmbedClient.client_id` 是普通 `String(80)` 且有唯一约束，`app/modules/embed/models.py:38`），使清库后根 `.env` 的 `EMBED_CLIENT_ID`/`EMBED_AGENT_ID` 仍然有效。
- 补全 `apps/backend/.env.example`：加入 DB_*、`AGENT_FILE_STORAGE_PATH`、`AGENT_MASTER_KEY`、`EMBED_*`、`QUOTA_ENABLED` 等重建环境所需键，值一律占位符，不写真实密钥。
- 新增 `docs/runbooks/dev-environment.md`：一页说明这条命令、种子产物（登录账号、Agent slug、技能包、工作流名）、需要人工补齐的项（真模型 key、SDK demo origin）。
- 新增 `tools/harness/verify/2026-10-16-dev-env-seed.sh`，由它产出 `verify.md`；同时新增配套的 `tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py`（本地 OpenAI 兼容假模型，用于让端到端对话验证不依赖外部账号余额）；同步更新 `docs/CHANGELOG.md`。

## 验收标准

1. 在干净库上 `bash apps/backend/scripts/reset_dev_db.sh` 退出码为 0；紧接着再跑一次 `seed_dev_env.py`，种子对象的行数与首次一致（幂等）。
2. 用种子账号调 `POST /api/v1/auth/login`（`apps/backend/app/modules/auth/router.py:29-36`）返回 200 并带 access token，`GET /api/v1/auth/me` 返回同一用户。
3. 种子 Agent 存在且 `default_version_id` 指向 `published_at` 非空的版本；`POST /api/v1/agents/{agent_id}/chat` 可建立会话。**实现期补充**：本机 relay 账号余额不足（`INSUFFICIENT_BALANCE`）导致真实出词恒失败，验证脚本改为起一个本地假模型（`-e OPENAI_BASE_URL=http://host.docker.internal:<port>/v1`）跑完整一轮对话，业务链路全部真实；未验证真实端点出词，记入「未执行项与原因」。
4. 技能包列表接口能列出种子技能包，`skill_package_files` 行数与 `apps/backend/scripts/seed_data/skills/<slug>/` 下文件数一致，且 Agent 的技能绑定存在。
5. 工作流列表接口能列出种子工作流且状态为 `active`，其 definition 能通过既有工作流静态校验。
6. `python3 tools/harness/audit.py` 退出码 0。
7. 可重建性：删除开发库数据、`apps/backend/storage/skill-packages` 与 Redis DB 0 后，仅凭 `reset_dev_db.sh` 能再次得到与第 2~5 条相同的结果（证明仓库内无数据库唯一副本）。
