# agent_reader 只读查库角色配置手册

本文说明如何把迁移建好的 `agent_reader` 角色变成「可登录、可被查库工具使用」的状态，以及如何自测
它确实只能读到本平台数据。对应 request `docs/harness/requests/2026-10-27-db-query-skill/`、ADR
`docs/adr/0018-db-query-read-only-boundary.md`，迁移
`apps/backend/migrations/versions/20261027_0047_agent_reader_and_rls.py`。

## 一句话用法

迁移只建 `NOLOGIN` 角色、授只读权限（并从 PUBLIC 收回 `set_config` 等敏感函数的执行权、
单独收回 `db_query_audits` 的 SELECT）、设角色级 GUC、建全表 RLS 策略；**剩下两件事必须由人做**：

```bash
# 1) 开 LOGIN 并设密码（密码只在交互式会话里输入，不写进仓库）
docker exec -it ai-base-db-1 psql -U root -d ai_db
#    在 psql 里执行（见「步骤 1」）
# 2) 把连接串注入 api 服务（改 .env + compose 一行，见「步骤 2」）
```

角色本身是 `NOLOGIN` 且没有密码，所以迁移在本地开发、CI 都能直接跑，不需要任何秘密值。

## 前置条件

- 迁移已执行：`select version_num from alembic_version;` 应为 `20261027_0047`（或更高）。
- 角色已存在且是 `NOLOGIN`：

  ```bash
  docker exec ai-base-db-1 psql -U root -d ai_db \
    -c "select rolname, rolcanlogin, rolsuper, rolbypassrls from pg_roles where rolname='agent_reader';"
  # 期望：agent_reader | f | f | f
  ```

- 你有数据库超级用户权限（迁移与应用连接用的是 `root`）。

## 安全边界：GUC 只能用 `SET LOCAL` 写，不能用 `set_config()`

`agent_reader` 对下面这些函数**没有** `EXECUTE` 权限（迁移在授权后逐个收回 PUBLIC 的
执行权，`pg_catalog.` 前缀同样被拒）：

| 函数 | 不收回的后果 |
| --- | --- |
| `set_config(text,text,boolean)` | 一条合法 SELECT 就能改写事务内的 `app.platform_id`，RLS 谓词形同虚设 |
| `pg_terminate_backend` / `pg_cancel_backend` | reader 能杀掉别人的查询 |
| `pg_read_file` / `pg_read_binary_file` / `pg_ls_dir` / `pg_stat_file` | 读写服务端文件系统 |
| `lo_import` / `lo_export` | 大对象的文件导入导出 |

所以查库工具必须用 SQL 语句写 GUC，**不要**用 `select set_config('app.platform_id', ...)`：

```sql
BEGIN;
SET TRANSACTION READ ONLY;
SET LOCAL app.platform_id = '1';   -- 普通 SET 语句，不经过函数执行权限
select count(*) from conversations;
COMMIT;
```

注意 `SET LOCAL` 只在事务块内有效（psql 自动提交模式下单独执行会告警且不生效），
所以必须包在 `BEGIN; ... COMMIT;` 里；`SET TRANSACTION READ ONLY` 与角色的
`default_transaction_read_only=on` 是同一个语义，可省略。

验证：

```bash
docker exec ai-base-db-1 psql -U root -d ai_db -c "
select has_function_privilege('agent_reader','pg_catalog.set_config(text,text,boolean)','execute') as set_config_exec,
       has_function_privilege('agent_reader','pg_catalog.pg_terminate_backend(int,bigint)','execute') as terminate_exec,
       has_table_privilege('agent_reader','db_query_audits','select') as audits_select;"
# 期望：f | f | f
```

> 注意 `pg_proc.proacl` 显示成 `{root=X/root}` 是收回 PUBLIC 后的正常形态（owner 之外无人可执行），
> 不是漏授。

## 安全边界：`db_query_audits` 不对 reader 开放

迁移的 `GRANT SELECT ON ALL TABLES` 会把审计表一起放开，随后单独
`REVOKE SELECT ON TABLE db_query_audits FROM agent_reader` 收回。原因是审计行里存了
**同平台其它会话/用户**的 SQL 摘要、错误码与耗时，reader 读到它等于能窥探别人查了什么，
跨出「只读自己平台业务数据」的边界。

排障要查审计时用 `root` 或应用账号：

```bash
docker exec ai-base-db-1 psql -U root -d ai_db \
  -c "select id, platform_id, tool_name, status, sql_digest, created_at from db_query_audits order by id desc limit 20;"
```

版本号（`alembic_version`）、`sys_users`、`sys_roles`、`sys_user_roles` 同理：只启用 RLS
不建策略＝默认拒绝，reader 查询返回 `0` 行。

## 步骤 1：设密码并允许登录

最简写法（`<强密码>` 是占位符，真实密码不要贴进 shell 历史或任何仓库文件）：

```sql
ALTER ROLE agent_reader LOGIN PASSWORD '<强密码>';
```

**推荐写法**（密码不回显、不进 shell 历史）：先开 LOGIN，再用 psql 的 `\password` 交互输入：

```bash
docker exec -it ai-base-db-1 psql -U root -d ai_db
```

```sql
ALTER ROLE agent_reader LOGIN;
\password agent_reader      -- 提示输入两次，服务端直接存 SCRAM 哈希
```

验证：

```sql
select rolname, rolcanlogin from pg_roles where rolname = 'agent_reader';  -- rolcanlogin = t
```

回滚（收回登录能力，保留角色）：

```sql
ALTER ROLE agent_reader NOLOGIN PASSWORD NULL;
```

密码用随机长串（≥32 字符），只存放在两处：密码管理器和本地 `.env`。**永远不要写进仓库**
（`.env` 已被 `.gitignore` 忽略）。

## 步骤 2：把 `DATABASE_READER_URL` 注入 api 服务

> `docker-compose.yml` 里已经写好透传（`x-backend-environment` 的 `DATABASE_READER_URL: ${DATABASE_READER_URL:-}`，
> 四个后端服务共用这个锚点），所以开通时只需要改根 `.env`，不用再动 compose。

1. 在仓库根 `.env`（已被 git 忽略）追加一行，`<密码>` 换成步骤 1 设的值：

   ```bash
   DATABASE_READER_URL=postgresql+asyncpg://agent_reader:<密码>@db:5432/ai_db
   ```

   三个容易错的点：

   - 必须带 `+asyncpg` 驱动前缀（查库引擎是 async 的，与应用 `DATABASE_URL` 一致）；
   - 容器内主机名是 compose 网络里的 `db`；在宿主机直接用 venv 起后端时改成 `127.0.0.1`；
   - 密码里的 `@ : / ? # %` 等字符必须 URL 编码（例如 `@` → `%40`）。

2. 确认 compose 透传还在（未配置时为空串，服务照常启动）：

   ```yaml
   x-backend-environment: &backend-environment
     # 只读查库连接串；留空＝未开通，工具返回稳定错误码 db_reader_not_configured，不阻塞启动
     DATABASE_READER_URL: ${DATABASE_READER_URL:-}
   ```

   不要写成 `${DB_READER_PASSWORD:?}` 那种「缺密码就拒绝启动」的形式：本设计明确要求未配置连接串时
   服务照常启动，只让两个查库工具返回 `db_reader_not_configured`。

3. 重建并重启后端容器（镜像要带上新迁移；api 的启动命令里本来就有 `alembic upgrade head`）。
   只改 `.env` 里的连接串时用 `restart` 就够；换了镜像才需要 `up -d --build`：

   ```bash
   docker compose up -d --build api worker task-scheduler wechat-bot-worker
   ```

4. 验证：

   ```bash
   docker exec ai-base-api-1 printenv DATABASE_READER_URL          # 应打出一条含 agent_reader 的连接串
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/system/health   # 200
   ```

如果暂时不想开通查库能力，把 `.env` 里的 `DATABASE_READER_URL` 置空并重启 api 即可，不需要回滚迁移。

## 步骤 3：自测租户隔离与只读

以 `agent_reader` 连接（`-h 127.0.0.1` 走 TCP + 密码认证；不加 `-h` 走容器内 socket 的 trust 认证，
验不到密码但同样能验隔离）：

```bash
docker exec -it -e PGPASSWORD='<密码>' ai-base-db-1 \
  psql -h 127.0.0.1 -U agent_reader -d ai_db
```

```sql
-- 角色级 GUC 已生效
show default_transaction_read_only;        -- on

-- 1) 不设租户上下文：0 行且不报错（current_setting(..., true) 为 NULL → 谓词为假）
select count(*) from conversations;        -- 0

-- 2) 平台 1：应等于 root 视角下 platform_id=1 的行数
begin;
set transaction read only;
set local app.platform_id = '1';
select count(*) from conversations;
commit;

-- 3) 平台 2：看不到平台 1 的行
begin;
set transaction read only;
set local app.platform_id = '2';
select count(*) from conversations;
commit;

-- 3b) 越权尝试必须失败：GUC 已经写成 2，再用 set_config 改回 1
begin;
set transaction read only;
set local app.platform_id = '2';
select count(*) from (select set_config('app.platform_id','1',true)) s, conversations c;
commit;
-- 期望：ERROR: permission denied for function set_config

-- 4) 无策略的全局表默认拒绝
select count(*) from sys_users;            -- 0
select count(*) from alembic_version;      -- 0

-- 4b) 审计表不对 reader 开放
select count(*) from db_query_audits;      -- ERROR: permission denied for table db_query_audits

-- 5) 写操作必须失败（只读事务，根本没走到权限检查）
insert into conversations (platform_id, agent_id, title) values (1, 1, 'x');
update conversations set title = title where id = 1;
delete from conversations where id = 1;

-- 6) 语句超时 5s
select pg_sleep(10);                       -- 约 5 秒后 canceling statement due to statement timeout
```

对照真值从应用超级用户视角取（`root` 是超级用户，按 PostgreSQL 手册 §5.9 绕过 RLS，因此读数不受策略影响）：

```bash
docker exec ai-base-db-1 psql -U root -d ai_db \
  -c "select platform_id, count(*) from conversations group by 1 order by 1;"
```

判定标准：

| 操作 | 期望 |
| --- | --- |
| 不设 GUC 查 `conversations` | `0`，且**不报错** |
| `app.platform_id=1` | 与 root 视角 `platform_id=1` 的 count 一致 |
| `app.platform_id=2` | 与 root 视角 `platform_id=2` 的 count 一致（没有平台 2 数据时就是 0） |
| `set_config(...)` 或 `pg_catalog.set_config(...)` | `ERROR: permission denied for function set_config` |
| `pg_terminate_backend` / `pg_cancel_backend` / `pg_ls_dir` | `ERROR: permission denied for function ...` |
| `select count(*) from db_query_audits` | `ERROR: permission denied for table db_query_audits` |
| `sys_users` / `sys_roles` / `sys_user_roles` / `alembic_version` | `0`（启用 RLS 但无策略＝默认拒绝） |
| `insert` / `update` / `delete` / `truncate` | 全部 `ERROR`（`cannot execute ... in a read-only transaction`） |
| `select pg_sleep(10)` | 约 5 秒后 `canceling statement due to statement timeout` |

要点：**不要**在 SQL 里手写 `where platform_id = ...` 去「证明」隔离——谓词已经在数据库侧，写不写
`platform_id` 都不影响可见集；验证要看的是「设了平台 1 只能看到平台 1」。

## 运行 /verify 之后要重启后端容器

`tools/harness/verify.sh 2026-10-27-db-query-skill` 会 downgrade/upgrade 迁移，迁移里 `agent_reader`
是删掉重建的（OID 变了）。正在运行的 api/worker 里已建立的只读连接池因此失效，日志会报
`invalid role OID` 或 `permission denied for table …`，此时查库工具返回 `db_error`——重启容器即可：

```bash
docker compose restart api worker task-scheduler wechat-bot-worker
```

本地已开通查库能力时更稳妥的做法是给验证脚本指定独立库（`VERIFY_DATABASE_URL=…`），
这样回滚/升级不会碰开发库里的角色。脚本退出时会按运行前状态恢复 `agent_reader`
（原先已开通 LOGIN 则写回原密码散列，否则收回 NOLOGIN）。

## 步骤 4：轮换密码 / 收回能力

> 轮换后如果 `.env` 里的旧连接串没跟着改，工具会返回 `db_reader_not_configured`（连接阶段认证失败被收口成这个稳定码），
> 而不是让模型看到一堆驱动异常——改完 `.env` 后 `docker compose up -d api worker task-scheduler wechat-bot-worker` 重载即可。



轮换密码：重复步骤 1，再更新 `.env` 里的 `DATABASE_READER_URL` 并重启 api。

彻底收回：

```sql
ALTER ROLE agent_reader NOLOGIN PASSWORD NULL;
```

然后清空 `.env` 的 `DATABASE_READER_URL` 并 `docker compose up -d api`。此后两个查库工具返回
`db_reader_not_configured`，与迁移前行为一致。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `FATAL: role "agent_reader" is not permitted to log in` | 只跑了迁移，没做步骤 1 | `ALTER ROLE agent_reader LOGIN PASSWORD '...'` |
| `password authentication failed for user "agent_reader"` | 密码不一致，或连接串里特殊字符没做 URL 编码 | 重设密码 / 编码连接串 |
| 设了 `app.platform_id` 仍然 0 行 | `SET LOCAL` 只在本事务内有效，`commit` 后就没了；或 GUC 名写错；或在自动提交模式下单独执行 `SET LOCAL`（只告警不生效） | 在同一个 `begin; ... commit;` 里设置并使用；名字必须是 `app.platform_id` |
| `ERROR: permission denied for function set_config` | **预期行为**：迁移已从 PUBLIC 收回执行权，正是为了堵住「合法 SELECT 改写 GUC 越权」 | 应用侧改用 `SET LOCAL app.platform_id = '<int>'`；只有超级用户 `root` 能调 `set_config` |
| `ERROR: permission denied for table db_query_audits` | **预期行为**：审计行含同平台其它会话的 SQL 摘要，不对 reader 开放 | 排障时用 `root` 或应用账号查审计 |
| 工具返回 `db_reader_not_configured` | api 容器里 `DATABASE_READER_URL` 为空 | 检查 `.env`、compose 那一行、是否 `--build` 重启；`docker exec ai-base-api-1 printenv DATABASE_READER_URL` |
| 查询报 `permission denied for table xxx`（不是 `db_query_audits`） | 表是迁移后新建的、又没授权 | `GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;`（迁移里的 `ALTER DEFAULT PRIVILEGES` 只覆盖 `root` 之后建的表） |
| 应用启动期检查报「有 platform_id 却没有 RLS 的表」 | 新表漏补策略（这是刻意设计的硬失败；`ALTER DEFAULT PRIVILEGES` 会自动给新表 SELECT，但**不会**建策略） | 在下一个迁移里参照 `RLS_POLICIES` 字典给新表补 `tenant_isolation` 策略 |
| 迁移报 `canceling statement due to lock timeout` | 迁移开头设了 `SET LOCAL lock_timeout = '8s'`，8 秒内拿不到 ACCESS EXCLUSIVE 锁就主动回滚 | 按下一节清掉长事务后**重跑即可**，不要修改迁移里的超时值 |

## 迁移锁等待与长事务排查

迁移里有 54 次 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`，每次都要求 ACCESS EXCLUSIVE
锁，而且整批在 alembic 的**单个事务**里执行。任何一条持锁的长事务（最常见的是应用侧
`idle in transaction` 的空闲连接）都会让迁移一直等锁；更糟的是 pg 的锁队列是 FIFO 的，
排在迁移后面的读请求也会被一起堵住。所以迁移开头用
`SET LOCAL lock_timeout = '8s'` 给等锁设了上限：拿不到锁就报错回滚，不会无限挂起。

迁移报 `lock timeout` 后按顺序排查：

```sql
-- 1) 谁在跑 / 谁在空闲事务里占着锁（超过几秒的都值得看）
select pid, usename, state, now() - xact_start as xact_age,
       now() - state_change as state_age, left(query, 100) as query
from pg_stat_activity
where datname = 'ai_db' and pid <> pg_backend_pid()
order by xact_start nulls last;

-- 2) 迁移在等谁：被阻塞的进程 + 阻塞源
select blocked.pid as blocked_pid, blocked.query as blocked_query,
       blocker.pid as blocker_pid, blocker.state as blocker_state,
       blocker.query as blocker_query
from pg_stat_activity blocked
join pg_locks bl on bl.pid = blocked.pid and not bl.granted
join pg_locks kl on kl.locktype = bl.locktype
                and kl.database is not distinct from bl.database
                and kl.relation is not distinct from bl.relation
                and kl.granted
join pg_stat_activity blocker on blocker.pid = kl.pid
where blocked.pid <> pg_backend_pid();
```

处理：

- `state = 'idle in transaction'` 且 `xact_age` 很大：先确认业务影响，能停就 `select pg_terminate_backend(<pid>);`
  （只有 `root` 等超级用户能调；`agent_reader` 已无此函数执行权）。
- 不要 `pg_terminate_backend` 正在跑批任务的连接，优先等它提交或让应用侧重启空闲连接池。
- 清完长事务后重跑 `alembic upgrade head`；迁移是幂等的（`CREATE ROLE` 有存在判断、
  `CREATE TABLE`/索引带 `IF NOT EXISTS`、策略先 `DROP POLICY IF EXISTS` 再建），
  半途失败后重跑不需要手工清理。
- 低峰执行；本地 `docker compose` 起 embed 聊天等会长期挂着事务的服务时尤其注意。

## 边界

- 角色由迁移创建为 `NOLOGIN`，密码永远不进仓库；`downgrade` 会连同 `db_query_audits` 一起删除，
  再升级后需要重做步骤 1、2。
- `agent_reader` 只被授予 `SELECT`，并带 `default_transaction_read_only=on`、`statement_timeout=5s`、
  `idle_in_transaction_session_timeout=15s` 三个角色级 GUC；改这些参数也在这里做，不要改应用连接。
- 敏感函数的 PUBLIC 执行权在迁移里被收回（`set_config`、`pg_terminate_backend`、`pg_cancel_backend`、
  `pg_read_file`、`pg_read_binary_file`、`pg_ls_dir`、`pg_stat_file`、`lo_import`、`lo_export`），
  这会影响**整个库的所有非超级用户**，不只 reader。若将来有别的普通角色确实需要这些函数，
  要单独 `GRANT EXECUTE` 给它，不要用 `GRANT ... TO PUBLIC` 把口子开回去。
  `downgrade` 会把它们恢复成 PUBLIC 可执行（PostgreSQL 默认状态）。
- `db_query_audits` 对 reader 不可读；审计还留在表里，用 `root` 或应用账号查。
- 租户谓词清单写死在迁移的 `RLS_POLICIES` 字典里（53 张存量表 + 新建的 `db_query_audits`），新增
  带 `platform_id` 的表必须在迁移里补一行策略。`ALTER DEFAULT PRIVILEGES` 只会自动给新表 SELECT，
  **不会**自动建策略，漏了会被启动期覆盖检查拒绝启动。
