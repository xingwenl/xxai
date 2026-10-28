# 库查询能力：把「只读」和「租户隔离」压到数据库侧，模型只负责写 SQL

## Status

accepted

关联 Harness request：`docs/harness/requests/2026-10-27-db-query-skill/`（tier A，spec 与验证证据见该目录）。术语（只读查询工具、库查询技能、`agent_reader`）见 `CONTEXT.md`。本 ADR 与 `docs/harness/requests/2026-08-04-skill-script-runner/spec.md` 的「脚本不允许访问数据库」是分工而不是冲突：脚本仍不许碰库，查库能力只以**内置业务工具**形态存在。

## Decision

**查库做成内置业务工具，不做技能脚本。** 本仓的「技能」是一段 `skills.instruction_template` 文本，脚本跑在独立 runner 容器里且被明令禁止访问数据库（`skill-runner-network: internal: true`、runner 镜像无 DB 驱动）。因此技能只承载「何时查、怎么查、怎么报」，取数只能由宿主进程里的业务工具完成——这与 `docs/shopskills/order-query/SKILL.md` 的「技能不取数、只绑定工具」完全同构。

**只读性由三件数据库事实强制，SQL 校验不算安全边界。** ①`agent_reader` 只被授予 `SELECT`，没有任何写权限；②该角色 `default_transaction_read_only=on`，执行前再 `SET TRANSACTION READ ONLY`；③业务表全部开启 RLS。应用层 `guard.py` 的单语句、`SELECT`/`WITH` 前缀、禁用关键字/函数词表只负责「让模型尽早拿到可读错误」，因为它拦不住函数副作用，也不该假装能拦。顺序上校验在前、事务在后：注定失败的 SQL 不必占连接。

**租户隔离用行级安全策略，不用应用层 `WHERE platform_id`。** 本仓现有仓储都手写 `WHERE platform_id`，属于自觉式隔离，而查库工具的输入是模型生成的任意 SQL——自觉隔离在这里等于没有。RLS 由 PostgreSQL 判定每一行，模型写的 SQL 里加不加 `platform_id` 都不影响可见集。前提是连接角色**不是表 owner 也不是超级用户**（`docs/adr/0018` 引用 PostgreSQL 17 手册 §5.9：超级用户与表 owner 默认绕过策略）；当前应用连接是 `root`，因此策略对应用零影响，这也是不用 `FORCE ROW LEVEL SECURITY` 的原因。

**策略按「表 → 租户锚点」逐表登记，不动态推导。** 实测库内 53 张存量表（加本轮新建的 `db_query_audits` 共 54 张）：24 张有 `platform_id` 列，直接谓词；`platforms` 用 `id`；22 张子表经一条外键到租户表（如 `conversation_messages → conversations`）；`agent_loop_steps` 经 `agent_loop_runs → conversations`、`workflow_step_runs` 经 `workflow_runs → workflows` 两跳；`sys_users`、`sys_roles`、`sys_user_roles`、`alembic_version` 不建策略＝默认拒绝（`sys_users` 含密码哈希，本就该看不见）。迁移里写死这份清单而不是在 SQL 里做外键图遍历：生成出来的谓词在评审里不可读，而「哪张表归哪个租户锚点」正是要被人看的那件事。

**角色由迁移创建为 `NOLOGIN`，密码永远不进仓库。** 迁移只建角色、授权、设 GUC、建策略；`LOGIN` 与密码由 `docs/runbooks/agent-reader-role.md` 里的人手动完成，连接串走 `DATABASE_READER_URL`。所以迁移在本地开发环境也能跑（不需要密码），而「谁有查库权限」这件事留在运维动作里可审计。

**未配置连接串时工具返回稳定错误码，不让服务启动失败。** 本地开发、CI 多半没有 `agent_reader` 的密码；把 `DATABASE_READER_URL` 设成硬要求会让所有环境先配库才能启动。折中是：`db_schema`/`db_query` 返回 `db_reader_not_configured`，模型据此告诉用户「查库能力未开通」；而后台开关（Agent 是否启用 `db` 组工具）仍然是真正的可用性闸口。

**启动期做两项自检，任一不成立就拒绝启动。** 一是**角色身份**：连接 `DATABASE_READER_URL` 的角色若是超级用户、`BYPASSRLS`，或 public 下任一张表的 owner，策略对它全部失效——把连接串误配成应用自己的 `root` 是最容易发生的错误配置，必须在启动时就拦住（查 `pg_roles` 的 `rolsuper`/`rolbypassrls` 与 `pg_class.relowner`）。二是**策略覆盖，且默认拒绝**：不能只检查「有 `platform_id` 但没开 RLS」的表，因为 22 张一跳子表与 2 张两跳表根本没有该列，将来新增一张 `conversation_attachments` 这类子表时 `ALTER DEFAULT PRIVILEGES` 会自动给 reader 授权、而检查看不出来。因此改成：public 下每张 BASE TABLE 都必须 `relrowsecurity`，白名单（`sys_users`/`sys_roles`/`sys_user_roles`/`alembic_version`）之外还必须有至少一条策略，否则 `RuntimeError` 带表名列表——与 `builtin_tool/groups.py`「工具漏登记分组即启动失败」同一种用确定性换安全的思路。

**独立只读引擎，不复用应用会话。** 应用只有全局一个 `AsyncSession` 工厂，且 Gateway 正在 flush/commit 的会话被并发使用会触发 asyncpg 并发操作错误（`builtin_tool/services.py` 对 `get_runtime_info` 特判独立会话的原因）。查库工具另建模块级懒单例：`pool_size=2`、`max_overflow=0`、`pool_pre_ping=True`，与应用引擎完全分离，池小是为了让「模型发起查库」永远抢不走业务连接。

**结果读三道上限：行、单元格、总字节。** `fetchmany(max_rows + 1)` 用多取一行判断截断，不靠 `COUNT(*)` 再查一遍；单元格超长截断并标记；总字节超预算就停止追加并置 `truncated`。理由很具体：一个 1MB 的 `text` 字段足够把模型上下文打爆，而「查库炸上下文」比「查不到」更难排查。

**`side_effect="none"`，不弹审批卡，用审计补偿。** 只读查询每次弹卡会让「查一下」彻底不可用；而写入面已被角色与只读事务封死，不存在「批准与否」的决策空间。补偿是 `db_query_audits`：每次调用（含被拒绝、超时）落一条记录，字段含平台、Agent、会话、工具名、SQL 摘要、状态码、耗时——内置工具此前完全没有审计表，只有 `agent_loop_steps.input_summary` 的 300 字符截断，查库这种高风险读取必须有独立账本。

**租户上下文由应用执行 `SET LOCAL app.platform_id = '<int>'` 写入，`set_config` 从 PUBLIC 收回执行权。** 最初实现用 `select set_config('app.platform_id', $1, true)`（因为 `SET LOCAL` 不能绑参数），评审时被实证出越权：reader 对 `set_config` 有默认 PUBLIC 执行权，模型只要写一条 `select … from (select set_config('app.platform_id','1',true)) s, conversations c`，就能在会话 GUC=平台 2 时读到平台 1 的 166 行。修复分两层：迁移里 `REVOKE EXECUTE … FROM PUBLIC`（并收回 `pg_terminate_backend`/`pg_cancel_backend`/文件读取类函数），应用改用不需要函数权限的 `SET LOCAL`（平台号是可信整数，`int()` 校验后拼接）。策略谓词仍用 `current_setting('app.platform_id', true)` 双参数形式：变量缺失时返回 `NULL` 而不是抛错，于是「忘了设」= 谓词为假 = 0 行，而不是一个可能被上层当成可重试的错误。审计表 `db_query_audits` 也不对 reader 开放（里面存着同平台其它会话的 SQL 摘要）。

**只读连接关掉 asyncpg 的 JIT 能力探测（自定义连接类）。** 收回 `set_config` 后暴露一个连带问题：asyncpg 首次做类型内省要先执行 `SELECT current_setting('jit'), set_config('jit','off',false)`（`asyncpg/connection.py` 的 `_introspect_types`，服务端版本 ≥ 11 恒触发），于是一旦查询涉及数组、`pgvector` 等非内置映射类型——包括 `db_schema` 取列信息用到的 `pg_constraint.conkey/confkey`——只读角色就会撞上 `permission denied for function set_config`，把合法查询一起误伤。可选路径里「换 psycopg3 驱动」最干净但要引依赖、改连接串；「单独 `GRANT set_config` 给 `agent_reader`」等于把刚收掉的越权面放回来；「把 `conkey/confkey` 在 SQL 里转成文本」只救 `db_schema`，救不了用户自己 `SELECT` 数组列。最终在只读引擎上用一个 `asyncpg.Connection` 子类把连接能力里的 `jit` 标记清掉，让 asyncpg 跳过这段探测——只读短查询本来也用不到 JIT，代价只是依赖一个 asyncpg 私有属性（实现里做了存在性兜底）。

## Considered Options

- **应用层拼 `WHERE platform_id`**：不加迁移、不动角色；但模型写任意 SQL 时没有任何机制保证它在 `WHERE` 里写对平台，一次漏写就是跨租户读。
- **`FORCE ROW LEVEL SECURITY` + 全局会话变量**：隔离最统一（应用自己也受策略约束）；但 53 张表的所有仓储路径都要带 `set_config`，等于重写数据访问层，与本轮「加一个只读查询能力」不匹配。
- **AST 校验（sqlglot/sqlparse）**：能优雅拒绝多语句与 DDL；但挡不住函数副作用，且新增依赖；真正的兜底是权限与只读事务。
- **预置查询模板 / 查询 DSL**：边界最硬；但多表 JOIN、窗口函数、CTE 都不可用，等于砍掉用户「想查什么就查什么」的需求。
- **独立 runner 容器执行 SQL**：复用既有隔离模型；但需在 runner 内放数据库凭证，推翻 `2026-08-04-skill-script-runner` 的非目标，且跨容器没有 `platform_id` 上下文。
- **MCP 形态的数据库工具**：可复用 MCP 的审计与确认链路；但多一层进程与凭证分发，且本仓内置工具已有分组、绑定、审批体系，没必要另开一条路。
- **给每张表建租户视图白名单**：不依赖策略；但视图定义与策略等量维护、更难审计，且 `security_barrier` 之外还有一堆坑。
- **迁移里用外键图自动推导策略**：新表自动覆盖；但生成的谓词在评审里不可读，而「这张表归哪个租户」正是必须人看的部分。
- **用 `set_config` 在查询 SQL 里传租户 GUC**：实现最直接（可绑参数）；但该函数默认对 PUBLIC 可执行，模型自写 SQL 能改写 GUC 越权读取（已实证 166 行），只能收回权限并改走 `SET LOCAL`。
- **换 psycopg3 驱动（`postgresql+psycopg://`）来绕开 asyncpg 的 JIT 探测**：不用碰 asyncpg 私有属性；但只读引擎与全仓驱动分叉，需要新增依赖并额外验证连接串/类型映射，收益小于风险。
- **单独给 `agent_reader` 授予 `set_config` 执行权**：asyncpg 内省立刻恢复；但这正是评审实证的越权面（模型 SQL 改写租户 GUC），靠 SQL 黑名单不是边界。
- **在 `db_schema` 的 SQL 里把 `conkey/confkey` 转成 `array_to_string` 文本**：只改一条查询、最省事；但只能救 schema，用户 `SELECT` 数组列/`pgvector` 列照样失败，等于把能力砍成半残。

## Consequences

- 好处：查库能力以最小新增面落地——一个迁移、一个只读引擎、两个工具、一个纯指令技能；隔离与只读由数据库判定，应用层校验写错也不会越权；越权面在评审中被实证后收口在数据库权限层（`set_config` 收回 PUBLIC），不是靠 SQL 黑名单；`db_query_audits` 补上了内置工具审计的空缺；新增子表若忘补策略或角色配错会在启动期立刻暴露。
- 代价：49 张表进入 `agent_reader` 可见集，4 张全局/技术表（含 `sys_users`）与 `db_query_audits` 不可见，需要时得单独加策略或换应用账号查；迁移的 downgrade 要逐个 `DROP POLICY`，是长而机械的代码；RLS 谓词存在于每条查询，带外键 `EXISTS` 的子表查询会比直连表慢；策略清单需要随新表维护（由启动检查兜住漏项）。
- 待观察：`agent_reader` 连接串的密码分发（runbook 是手动步骤，尚未自动化）；模型自写 SQL 的质量依赖技能指令与 `db_schema` 的注释质量；单行超大字段（如 `repeat('x', 200000000)`）仍会在截断判定前整行读入进程内存——服务端游标救不了单行，目前只靠 5s 语句超时与 `pool_size=2` 兜底，必要时得在 SQL 层限制列；只读引擎依赖 asyncpg 私有属性 `_server_caps`（无该属性时跳过），升级 asyncpg 需要回归数组/`pgvector` 查询宽；审计写入是 best-effort（失败只告警、不阻断查询），取消路径可能丢记录；`db_query_audits` 无保留期策略，长期需要按时间清理；只读角色目前只有一条池，未来若要支持多个平台并发查库需要按池大小评估。
