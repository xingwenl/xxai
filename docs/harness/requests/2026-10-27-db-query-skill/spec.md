---
id: 2026-10-27-db-query-skill
tier: A
risk: high
approval:
  required: true
  granted: true
  why: ["架构边界变化：新增「Agent 直连数据库」数据通路，业务表首次启用行级安全策略", "数据模型变化：新增 db_query_audits 表与数据库登录角色 agent_reader", "API 契约变化：新增 db_schema / db_query 两个内置工具契约与 db 工具组", "鉴权或权限行为变化：按平台（platform_id）行级隔离，后台管理 Agent 只能看本平台数据"]
---

## 目标与范围

- 做成什么：后台管理 Agent 能「想查什么就查什么」地读本平台数据。两个只读内置工具——`db_schema`（自描述表结构与中文注释）与 `db_query`（执行只读 SQL）——加一个纯指令技能 `db-query`（何时查、怎么写、怎么报）。在悬浮助手用自然语言问「上周各店铺订单量」「这个 Agent 最近 7 天报错最多的工具」，模型先看结构、再写 SQL、拿到真实数字。
- 隔离与只读由**数据库强制**：独立登录角色 `agent_reader`（无写权限）+ 全表行级安全策略（谓词取平台）+ 只读事务 + 语句超时。应用层 SQL 校验只负责「早失败、给模型可读的错误」，不当安全边界。
- 不做：技能脚本访问数据库（沿用 `2026-08-04-skill-script-runner` 的非目标）；任何写/DDL；跨平台查询（平台管理员也只能看本平台）；服务端自然语言转 SQL；结果图表与前端页面；MCP 形态的数据库工具；查询结果缓存；引入 SQL 解析依赖（sqlglot/sqlparse）。

## 来源与方案比较

- **PostgreSQL 17.11 手册 §5.9 Row Security Policies**（https://www.postgresql.org/docs/17/ddl-rowsecurity.html ，2026-10-27 取用）：RLS 在无策略时默认拒绝；**超级用户与 `BYPASSRLS` 角色总是绕过**；表 owner 默认也绕过（`FORCE ROW LEVEL SECURITY` 才受约束）。→ 本仓应用连接是超级用户 `root`，因此给业务表加策略对应用零影响；隔离只能用「另一个非 owner、非超级用户」的登录角色才成立。
- **PostgreSQL 17.11 手册 §19.11.1 Client Connection Defaults**（https://www.postgresql.org/docs/17/runtime-config-client.html ，2026-10-27 取用）：`default_transaction_read_only`、`statement_timeout`、`idle_in_transaction_session_timeout` 均可按角色/会话设定；`row_security=off` 会让受策略影响的查询**报错**而不是静默过滤（本设计依赖前者做只读兜底）。
- **本仓既有边界先例**：`docs/harness/requests/2026-08-04-skill-script-runner/spec.md` 明确「不允许脚本访问…数据库」，`apps/backend/app/modules/tools/basic/http_get.py` 用 `target_not_public` 限制目标集合而非语法。同一思路：把安全性放在「能力边界」（角色 + 策略），不放在「输入检查」。
- **本机 agent 项目 Pi**（`/Users/lixingwen/xw/git/pi`，2026-10-27 检索）：只有 shell/文件类工具与 `@anthropic-ai/sandbox-runtime` 沙箱，没有数据库工具分支，无法照搬；其启示是「工具的危险面由运行环境隔离，不由提示词约束」。
- 方案 A（选中）：只读角色 + RLS 平台谓词 + 只读事务 + 轻量语法校验 + 外层 LIMIT；两个内置业务工具取数。
- 方案 B：应用层预置查询模板（选表 + 条件 + 聚合，不让模型写 SQL）。边界最硬，但多表 JOIN、窗口函数、CTE 全部不可用，等于砍掉「想查什么就查什么」；且每种查询形态都要写一层 DSL。
- 方案 C：把 SQL 交给独立 runner 容器执行（复用 skill-runner 的隔离模型）。需要在 runner 内放数据库凭证，直接推翻 runner「不碰数据库」的既有边界，且跨容器拿不到 `platform_id` 上下文。
- 选择 A：隔离交给数据库（策略），只读交给角色与只读事务，校验只做体验。缺点（策略逐表维护）用「启动期覆盖检查」补偿。

## 被否决的选项

- **复用应用超级用户连接 + 应用层拼 `WHERE platform_id`**：与现有仓储同样的自觉式隔离，漏一处即跨租户读；且超级用户让 RLS 完全失效。
- **给业务表加 `FORCE ROW LEVEL SECURITY`，让应用自己也受约束**：53 张表 × 全部仓储路径都要带会话变量，等于重写整个数据访问层，一次回归的风险远超收益。
- **引入 sqlglot/sqlparse 做 AST 校验**：解析器解决不了函数副作用（`pg_read_file` 类），却新增依赖；真正兜底的是只读事务与无写权限角色。
- **只暴露预置查询模板（方案 B）**：安全，但把用户的原初需求「想查什么就查什么」砍掉大半。
- **做成 MCP server**：多一层进程与凭证分发，与本仓内置工具的分组、审批、审计体系脱节。
- **`db_query` 每次查询走审批闸口（`side_effect=write`）**：只读查询每问一次弹一次卡，「查一下」直接不可用；风险已由数据库侧强制，改用 `db_query_audits` 审计补偿。
- **结果原样返回不截断**：一个 1MB 的 text 字段就能把上下文打爆；必须有单元格、行数、总字节三重上限。
- **给 `agent_reader` 开 `BYPASSRLS` 或建视图白名单**：前者等于取消隔离；后者要为每张表维护一份视图定义，与策略等量工作却更难审计。
- **用 `set_config('app.platform_id', …)` 在查询 SQL 里传租户**：`set_config` 默认对 PUBLIC 可执行，模型自写的 `SELECT` 可以直接把它改成别的平台再读数据（已实证越权），因此改为应用侧 `SET LOCAL` 写 GUC + 迁移里收回该函数的 PUBLIC 执行权。

## 停点判断

- 是否涉及架构边界变化：是——新增 Agent 直连数据库的数据通路，业务表首次启用行级安全策略。
- 是否涉及数据模型变化：是——新增 `db_query_audits` 表、数据库角色 `agent_reader`。
- 是否涉及 API 契约变化：是——新增两个内置工具契约与 `db` 工具组（对模型可见）。
- 是否涉及鉴权或权限行为变化：是——新增按 `platform_id` 的行级隔离主体。
- 结论：A 档，`approval.required: true`，实现前需用户确认；实现后按 HARNESS 跑两轮拷问。

## 变更点

- `apps/backend/migrations/versions/20261027_0047_agent_reader_and_rls.py`：建 `db_query_audits`；`DO` 块创建 `NOLOGIN` 角色 `agent_reader`（已存在则跳过）；`GRANT USAGE ON SCHEMA public` + `GRANT SELECT ON ALL TABLES` + `ALTER DEFAULT PRIVILEGES`；`ALTER ROLE agent_reader SET default_transaction_read_only=on / statement_timeout / idle_in_transaction_session_timeout`；对 public 下 53 张存量表 + `db_query_audits`（共 54 张）`ENABLE ROW LEVEL SECURITY`，逐表建策略——24 张有 `platform_id` 的表用直连谓词 `platform_id = current_setting('app.platform_id', true)::bigint`，`platforms` 用 `id = ...`，22 张一跳子表用「父表 `.platform_id`」`EXISTS` 谓词（如 `conversation_messages → conversations`），`agent_loop_steps` 经 `agent_loop_runs → conversations`、`workflow_step_runs` 经 `workflow_runs → workflows` 两跳；`sys_users`、`sys_roles`、`sys_user_roles`、`alembic_version` 无策略＝默认拒绝。**权限收紧**：`REVOKE EXECUTE ... FROM PUBLIC` 收回 `set_config` 与 backend 控制类函数（`pg_terminate_backend`/`pg_cancel_backend`/`pg_read_file` 等）的 PUBLIC 执行权——否则一条合法 `SELECT` 就能用 `set_config` 改写 `app.platform_id` 越权（已实证）；`REVOKE SELECT ON db_query_audits FROM agent_reader`（审计里有同平台其它会话的 SQL 摘要）。迁移开头 `SET LOCAL lock_timeout='8s'`，避免 54 次 `ENABLE RLS` 等锁无限阻塞。`down_revision='20261021_0046'`。
- `apps/backend/app/core/config.py`：`database_reader_url`（`DATABASE_READER_URL`，空＝未配置）、`db_query_statement_timeout_ms=5000`、`db_query_max_rows=200`、`db_query_max_result_bytes=65536`、`db_query_max_cell_chars=8192`、`db_query_pool_size=2`。
- 新模块 `apps/backend/app/modules/db_query/`：`engine.py`（模块级懒单例 `create_async_engine(pool_size=2, max_overflow=0, pool_pre_ping=True)` + 跳过 asyncpg JIT 探测的连接类——否则收回 `set_config` 后数组/`pgvector` 类型的查询会 `permission denied` + `dispose`）、`guard.py`（单语句、`SELECT`/`WITH` 前缀、禁用关键字与危险函数词表、强制外层 `LIMIT`）、`runner.py`（**`SET LOCAL app.platform_id = '<int>'` 写事务局部 GUC**——不用 `set_config`，它在迁移里被收回 PUBLIC 执行权；`SET TRANSACTION READ ONLY`、超时、`fetchmany(max_rows+1)`、单元格截断与字节预算）、`audits.py`（写 `db_query_audits`，被拒也写）、`health.py`（启动检查：连接角色非超级用户/非 `BYPASSRLS`/非表 owner，且白名单外的表必须有 RLS + 策略）。
- `apps/backend/app/modules/tools/business/db_query.py`：`db_schema`、`db_query` 两个工具，`side_effect="none"`；错误只回稳定码 `db_reader_not_configured` / `db_sql_rejected` / `db_timeout` / `db_result_too_large` / `db_error`，不把异步驱动的原始异常文本透给模型。
- `apps/backend/app/modules/tools/business/registry.py` 导入注册；`apps/backend/app/modules/builtin_tool/groups.py` 登记 `db` 组（标题「数据库」，描述「只读查询本平台数据：表结构与只读 SQL」）并映射两个工具名。
- `docs/skills/db-query/SKILL.md`：纯指令技能（frontmatter `name` + `description`），写何时用、先 `db_schema` 再看 `db_query`、方言约定（时间列是 `timestamptz`、不要自己加 `platform_id` 过滤、不要写 `LIMIT`）、输出规范与错误处理。
- `docker-compose.yml`：`x-backend-environment` 增加 `DATABASE_READER_URL: ${DATABASE_READER_URL:-}` 原样透传（不写 `:?`，未配置时 api 照常启动）；真实密码只进根目录 `.env`（已 gitignore），`.env.example` 只放占位。
- 工具层错误码口径：连接阶段失败（密码错、角色被收回 `LOGIN`、库不可达）也收口成 `db_reader_not_configured`——它和「SQL 写错」不同，只能由管理员改配置，不该让模型反复重试。
- `docs/runbooks/agent-reader-role.md`：给 `agent_reader` 设密码并开 `LOGIN`、compose 注入 `DATABASE_READER_URL` 的步骤。
- 测试：`apps/backend/tests/tools/test_db_query_guard.py`（纯单测）、`apps/backend/tests/tools/test_db_query_tool_errors.py`（连接层失败→`db_reader_not_configured` 的错误码收口）、`apps/backend/tests/db_query/test_reader_isolation.py`（真库，未配 `DATABASE_READER_URL` 则 skip）。
- 文档：`docs/adr/0018-db-query-read-only-boundary.md`、`CONTEXT.md`（只读查询工具 / 库查询技能 / agent_reader）、`docs/CHANGELOG.md`。
- 验证：`tools/harness/verify/2026-10-27-db-query-skill.sh`。

## 验收标准

1. 迁移：`alembic upgrade head` 与 `downgrade -1` 均退出 0（且可重复升级）；`pg_roles` 中 `agent_reader` 存在且 `rolcanlogin=false`（配密码前不可登录）；public 下每张 BASE TABLE 都 `relrowsecurity=true`，白名单外每张表至少一条策略（无策略表恰为 4 张：`sys_users`/`sys_roles`/`sys_user_roles`/`alembic_version`）；`has_function_privilege('agent_reader','pg_catalog.set_config(text,text,boolean)','execute') = false`、`has_table_privilege('agent_reader','db_query_audits','select') = false`。
2. 租户隔离：以 `agent_reader` 连接并 `SET LOCAL app.platform_id = '1'` 后，`select count(*) from conversations` 只统计平台 1；切成平台 2 看不到平台 1 的行；**不设 GUC** 时返回 0 行且不报错；**越权用例必须失败**——reader 执行 `select … from (select set_config('app.platform_id','1',true)) s, conversations c` 得到 `permission denied`（`pg_catalog."set_config"` 同样被拒），防线在权限而非黑名单。
3. 只读强制：同一会话里 `insert/update/delete/truncate` 任一语句失败（只读事务或无权限），库中行数与内容不变。
4. 超时与错误码：`select pg_sleep(10)`（或等价长查询）被拦，工具返回 `db_timeout`；`update ...`、`drop table ...`、多语句、注释拼接分别返回 `db_sql_rejected`，模型收到的是稳定码 + 一句短消息，不含原始驱动异常栈。
5. 结果上限：造 300 行结果时返回 ≤200 行且 `truncated=true`；单单元格 20KB 文本被截到 8192 字符；总输出 ≤65536 字节。
6. 应用不受影响：RLS 对超级用户 `root` 零影响——`docker compose` 里 api 容器健康，`poetry run pytest` 全绿，`select count(*) from conversations`（应用连接）与迁移前一致。
7. 审计与前端：每次调用（含被拒、超时、取消）落一条 `db_query_audits`（平台、Agent、工具名、SQL 摘要、状态、耗时）；`pnpm --dir apps/front build` 退出 0 且 Agent 工具页出现「数据库」组；`python3 tools/harness/audit.py` 退出 0。
