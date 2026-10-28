---
source: script
request: 2026-10-27-db-query-skill
ranAt: "2026-10-27 18:38:26 CST"
exitCode: 0
---

## 已执行的命令与结果
连接数据库：`postgresql+asyncpg://root:Dd123456@…`
运行前 agent_reader：已开通 LOGIN（结束时恢复原密码散列）

### 0. 复位上一次中断留下的临时登录态（保证后续断言可重复）

```text
agent_reader 已复位：NOLOGIN + 空密码

结果：PASS（exit=0）
```

### 1. 静态检查：ruff 与工具注册

All checks passed!

结果：PASS（exit=0）

```text
db_schema: group=db side_effect=none 必填参数=[]
db_query: group=db side_effect=none 必填参数=['sql']
db 组：title=数据库 description=只读查询本平台数据：查看表结构与执行只读 SQL
工具注册与分组断言通过

结果：PASS（exit=0）
```

### 2. 迁移升级与库侧安全边界

```bash
$ alembic upgrade head
```

```text

```

```text
alembic_version = 20261027_0047
agent_reader: rolsuper=False rolcanlogin=False rolbypassrls=False
agent_reader rolconfig: default_transaction_read_only=on statement_timeout=5s idle_in_transaction_session_timeout=15s
public 下 base table = 54
relrowsecurity=true 的表 = 54/54
有 platform_id 但未开启 RLS 的表 = 0
启用 RLS 但无策略（默认拒绝）的表 = ['alembic_version', 'sys_roles', 'sys_user_roles', 'sys_users']
策略数 = 50
agent_reader 有 SELECT 权限的表 = 53
agent_reader 对 db_query_audits：SELECT=不可读，INSERT=不可写
agent_reader：set_config 不可执行，backend/文件类函数均不可执行
db_query_audits 字段 = 13，缺少注释 = 0
库侧安全边界断言通过

结果：PASS（exit=0）
```

### 3. 迁移回滚与再升级

注意：本段会重建 agent_reader 角色，正在运行的后端容器需重启才能重连（见脚本头部说明）。

```text

结果：PASS（exit=0）

```text
alembic_version = 20261021_0046
agent_reader 已删除
db_query_audits 已删除
relrowsecurity=true = 0，策略数 = 0
回滚断言通过

结果：PASS（exit=0）
```

```text

结果：PASS（exit=0）
```

### 4. SQL 轻校验单测（不是安全边界，只保证早失败与外层 LIMIT）

```text
.................................                                        [100%]
33 passed in 1.86s

结果：PASS（exit=0）
```

### 5. 启动期自检 fail-closed（角色身份 + 默认拒绝覆盖 + 越权拒绝）

```text
5a) 把 DATABASE_READER_URL 误配成超级用户（root）时必须拒绝启动：
拒绝启动：只读查库角色 root 是超级用户（rolsuper），会绕过行级安全策略，只读查库会跨租户读取，拒绝启动

结果：PASS（exit=0）
```

5b) 白名单外「没有 platform_id、也没有策略」的新表必须拒绝启动；set_config 越权必须被权限层拒绝：

```text
已临时开启 agent_reader 登录（脚本退出时会复位），并建了无策略探针表
无 platform_id 的新表未建策略时拒绝启动：以下 public 表未满足「开启 RLS 且（白名单外）至少一条策略」，只读查库会跨租户读取，拒绝启动：_rls_coverage_probe（no_policy）, _rls_coverage_probe（rls_disabled）
探针表删除后覆盖检查通过
SET LOCAL app.platform_id=1 → conversations 可见 169 行
SET LOCAL app.platform_id=2 → conversations 可见 0 行
越权用例 set_config：被拒绝（ProgrammingError，permission denied）
越权用例 pg_catalog."set_config"：被拒绝（ProgrammingError，permission denied）

结果：PASS（exit=0）
```

### 6. 真库租户隔离与工具层端到端

```text
已临时开启 agent_reader 登录（验证结束后复位）

结果：PASS（exit=0）
```

```text
s.....s.                                                                 [100%]
6 passed, 2 skipped in 3.27s

结果：PASS（exit=0）
```

工具层端到端（错误码、结果上限、审计落库）：

```text
db_query 执行超时 platform_id=1 sqlstate=57014
db_schema: table_count=1 keys=['table_count', 'tables']
db_schema 列信息: columns=9 primary_key=[]
db_schema 默认（只回表名+注释）: table_count=49 bytes≈5052
数组/向量类型查询 OK: select conkey from pg_constraint limit 1 -> row_count=1
数组/向量类型查询 OK: select array[1, 2]::int4[] as a -> row_count=1
数组/向量类型查询 OK: select embedding from conversation_asset_emb -> row_count=1
db_query: row_count=1 rows=[[169]] truncated=False
300 行查询: row_count=200 truncated=True reason=max_rows
20KB 单元格: 返回长度=8192 truncated=True reason=max_cell_chars
字节预算: row_count=130 总字节=65000 truncated=True reason=max_bytes
  'update conversations set updated_at = now()' -> db_sql_rejected | 只允许执行只读查询（SELECT 或 WITH）
  'select 1; drop table conversations' -> db_sql_rejected | 一次只能执行一条 SQL，请去掉分号拼接的多条语句
  'select 1 /* ; */ ; delete from conversations' -> db_sql_rejected | 一次只能执行一条 SQL，请去掉分号拼接的多条语句
  "select pg_read_file('/etc/passwd')" -> db_sql_rejected | SQL 使用了不允许的函数或系统表：pg_read_file
  "select set_config('app.platform_id', '2', true)" -> db_sql_rejected | SQL 使用了不允许的函数或系统表：set_config
  'select pg_sleep(10)' -> db_timeout | 查询超时，请缩小查询范围（增加更精确的过滤条件）后重试
审计行数 = 15
  审计: tool=db_query status=timeout error_code=db_timeout
  审计: tool=db_query status=rejected error_code=db_sql_rejected
  审计: tool=db_query status=rejected error_code=db_sql_rejected
  审计: tool=db_query status=rejected error_code=db_sql_rejected
  审计: tool=db_query status=rejected error_code=db_sql_rejected
  审计: tool=db_query status=rejected error_code=db_sql_rejected
  审计: tool=db_query status=ok error_code=-
  审计: tool=db_query status=ok error_code=-
工具层端到端断言通过

结果：PASS（exit=0）
```

恢复 agent_reader 为不可登录：

```text
恢复 agent_reader：LOGIN + 原密码散列（已校验一致）
已恢复（NOLOGIN + 空密码）
```

### 7. 未开通查库能力时返回稳定错误码

```text
db_schema_tool -> db_reader_not_configured | 查库能力未开通，请联系管理员配置只读数据库连接
db_query_tool -> db_reader_not_configured | 查库能力未开通，请联系管理员配置只读数据库连接
未开通时的稳定错误码断言通过

结果：PASS（exit=0）
```

连接串漏写驱动前缀（postgresql:// 而非 postgresql+asyncpg://）也必须收口成同一个稳定码：

```text
只读查库引擎初始化失败（连接串非法，按未配置处理） error=InvalidRequestError detail=The asyncio extension requires an async driver to be used. The loaded 'psycopg2' is not async.
只读查库引擎初始化失败（连接串非法，按未配置处理） error=InvalidRequestError detail=The asyncio extension requires an async driver to be used. The loaded 'psycopg2' is not async.
db_schema_tool -> db_reader_not_configured
db_query_tool -> db_reader_not_configured
非法连接串时的稳定错误码断言通过

结果：PASS（exit=0）
```

连接阶段认证失败（密码错 / 角色已收回 LOGIN）同样必须收口成稳定码：

```text
db_schema 只读连接不可用 platform_id=1 error=InvalidPasswordError
db_query 只读连接不可用 platform_id=1 error=InvalidPasswordError
db_schema_tool -> db_reader_not_configured | 查库能力未开通，请联系管理员配置只读数据库连接
db_query_tool -> db_reader_not_configured | 查库能力未开通，请联系管理员配置只读数据库连接
认证失败时的稳定错误码断言通过

结果：PASS（exit=0）
```

### 8. 应用可启动（工具注册、分组、启动检查接线）

```text
create_app() 成功，OpenAPI 路径数 = 104
Agent 工具页接口已挂载：/platforms/{platform_id}/agents/{agent_id}/builtin-tools
启动期 RLS 覆盖检查已接线（未配置 DATABASE_READER_URL 时跳过）

结果：PASS（exit=0）
```

运行中的 api 容器健康检查（证明 RLS 对超级用户连接零影响）：

```text
GET /api/v1/system/health -> HTTP 200
{"success":true,"message":"ok","data":{"service":"AI Base Backend","version":"0.0.1","environment":"development","status":"ok"},"meta":null,"code":0,"error_code":null}

结果：PASS（exit=0）
```

### 9. 相关回归测试（业务工具与内置工具分组）

```text
........................................................................ [ 42%]
........................................................................ [ 85%]
.........................                                                [100%]
169 passed in 4.75s

结果：PASS（exit=0）
```

### 10. 前端构建（工具组由接口驱动，本次无前端代码改动）

```text
dist/assets/chats-DwhnNck_.js                        868.47 kB │ gzip: 300.93 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 925ms

结果：PASS（exit=0）
```

### 11. Harness 门禁审计

```text
SKIP   2026-10-20-personal-knowledge-base（spec.md 标记为已取消，仅归档设计记录，不校验产物）

v2 requests: 37  存量跳过: 59  已取消跳过: 1  ERROR: 0  WARN: 0

注：运行时 verify.md 尚未生成（本脚本输出即其内容），「缺少 verify.md」一条属自指，已排除。
本任务相关的 ERROR 数 = 0（audit 退出码 0）

结果：PASS（exit=0）
```

## 未执行项与原因

- 全量 `pytest` 未执行：仓库内多个同名测试文件（`test_services.py` 等）在无 `__init__.py` 的目录下会触发 import mismatch，属存量问题；本脚本改跑工具/分组相关的 `tests/tools tests/builtin_tool` 与两个新增测试文件。
- 「Agent 工具页出现数据库组」未做浏览器端点击验证：前端完全由 group 列表接口驱动且本次无前端改动，脚本以第 1 段的注册断言 + 第 8 段的接口挂载断言 + 第 10 段构建代替。
- 第 8 段末尾的 api 容器健康检查在该端口无服务时会标注跳过；容器跑的是迁移前镜像，故该条只证明「启用 RLS 后超级用户连接照常可用」。
- `docker-compose.yml` 未注入 `DATABASE_READER_URL`：按 spec 属于部署侧动作，runbook 已写明手工步骤。

## 验收结论

本次执行的所有片段均通过（详见上文各段真实输出与退出码）。
恢复 agent_reader：LOGIN + 原密码散列（已校验一致）
