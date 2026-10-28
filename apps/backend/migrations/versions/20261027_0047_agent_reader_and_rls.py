"""只读查库：db_query_audits 审计表、agent_reader 角色与全表行级安全策略

本迁移是「后台管理 Agent 直连数据库查数」能力（见
docs/harness/requests/2026-10-27-db-query-skill/spec.md 与
docs/adr/0018-db-query-read-only-boundary.md）的数据库侧边界，做四件事：

1. 建 ``db_query_audits``：``db_schema`` / ``db_query`` 每次调用（含被拒绝、超时）
   落一条记录。内置工具此前没有审计表，只读查库是高风险读取，必须有独立账本。
   审计行由应用（超级用户 ``root``）写入；不建外键，避免删会话/删用户时外键级联
   或约束失败把历史账本带走——账本要能独立留存。
2. 建 ``NOLOGIN`` 角色 ``agent_reader``：只授 ``SELECT``（+ 只读事务与语句/空闲
   事务超时的角色级 GUC）。它**不是**表 owner 也不是超级用户，因而是全库唯一
   真正受行级安全策略约束的连接主体；应用连接 ``root`` 是超级用户，按 PostgreSQL
   手册 §5.9 默认绕过策略，所以本迁移对应用零影响。
3. 对 public 下全部表启用 RLS 并逐表建 ``tenant_isolation`` 策略：24 张自带
   ``platform_id`` 的表直接比较列值；``platforms`` 用主键；22 张子表经一条非空
   外键取父行的 ``platform_id``；``agent_loop_steps``、``workflow_step_runs``
   两跳才能到租户锚点。``sys_users`` / ``sys_roles`` / ``sys_user_roles`` /
   ``alembic_version`` 只启用 RLS、不建策略＝默认拒绝（``sys_users`` 含密码哈希）。
4. 谓词统一用 ``current_setting('app.platform_id', true)``：双参数形式在 GUC 缺失
   时返回 NULL 而不是报错，于是「忘了设租户」= 谓词为假 = 0 行，不会变成一个
   可能被上层当成可重试的错误。

清单写死而不是在迁移里遍历外键图：生成的谓词在评审里不可读，而「哪张表归哪个
租户锚点」正是必须被人看的那件事（ADR 0018「策略按表→租户锚点逐表登记」）。

本迁移新建的 ``db_query_audits`` 自身也带 ``platform_id``，因此同样启用 RLS 并建
策略；否则「public 下有 platform_id 而 relrowsecurity=false 的表数为 0」这条启动期
覆盖检查会失败，新表会被 reader 全量跨租户读到。

安全补强（与上面的授权段配合）：``GRANT SELECT`` 之后会收回 ``set_config`` 等
敏感函数对 PUBLIC 的 EXECUTE——否则一条语法合法的 SELECT 就能把事务内的
``app.platform_id`` 改写掉，RLS 谓词完全失效；同时单独收回 ``db_query_audits``
的 SELECT，审计里有同平台其它会话的 SQL 摘要，reader 不该读。

操作属性：54 次 ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` 都需要 ACCESS
EXCLUSIVE 锁，而且整批在 alembic 的单个事务里执行。应用侧的长事务或
``idle in transaction`` 连接会把迁移一直卡在等锁上（本地执行时就被一个 embed
聊天遗留的空闲事务阻塞过），建议在低峰执行。因此迁移开头先
``SET LOCAL lock_timeout = '8s'``：锁等待超过 8 秒就报错回滚，而不是无限等锁并把
后续全部读写堵在锁队列后面。**锁等待超过 lock_timeout 会报错，重跑即可；若持续
失败先排查长事务**（查 ``pg_stat_activity`` 里的 ``idle in transaction``，必要时
``pg_terminate_backend``），不要盲目重跑。

不可逆点：``downgrade`` 会删除 ``db_query_audits``（审计历史丢失）并 ``DROP ROLE
agent_reader``（含人工在 runbook 里设过的 LOGIN 与密码，需要重新配置）。

Revision ID: 20261027_0047
Revises: 20261021_0046
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261027_0047"
down_revision: Union[str, None] = "20261021_0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

READER_ROLE = "agent_reader"
POLICY_NAME = "tenant_isolation"
# 展开后即 current_setting('app.platform_id', true)::bigint：
# 变量不存在时得到 NULL（谓词为假，返回 0 行），而不是抛 invalid_parameter_value。
TENANT_SETTING = "current_setting('app.platform_id', true)::bigint"


def _child_predicate(table: str, parent: str, fk_column: str) -> str:
    """子表一跳谓词：经一条非空外键回到租户表，取父行的 platform_id。

    三个参数全是写死的表名/列名，迁移里不查外键图；这样映射关系在代码里可评审。
    """
    return (
        f"EXISTS (SELECT 1 FROM {parent} p "
        f"WHERE p.id = {table}.{fk_column} "
        f"AND p.platform_id = {TENANT_SETTING})"
    )


# {表名: 租户谓词 SQL}。键集合需与 public 下「有 platform_id 的表」+「经外键能到
# 租户锚点的子表」+ platforms 完全一致，缺失即等于该表对 reader 全量可见。
RLS_POLICIES: dict[str, str] = {
    # ---- 24 张自带 platform_id 的表：直接比较列值 ----
    "agent_builtin_tools": f"platform_id = {TENANT_SETTING}",
    "agent_loop_run_checkpoints": f"platform_id = {TENANT_SETTING}",
    "agents": f"platform_id = {TENANT_SETTING}",
    "conversation_assets": f"platform_id = {TENANT_SETTING}",
    "conversations": f"platform_id = {TENANT_SETTING}",
    "host_tool_call_audits": f"platform_id = {TENANT_SETTING}",
    "host_tool_policies": f"platform_id = {TENANT_SETTING}",
    "knowledge_bases": f"platform_id = {TENANT_SETTING}",
    "mcp_servers": f"platform_id = {TENANT_SETTING}",
    "mcp_tool_call_audits": f"platform_id = {TENANT_SETTING}",
    "mcp_tool_confirmations": f"platform_id = {TENANT_SETTING}",
    "model_usage_records": f"platform_id = {TENANT_SETTING}",
    "platform_admins": f"platform_id = {TENANT_SETTING}",
    "platform_embed_clients": f"platform_id = {TENANT_SETTING}",
    "platform_end_users": f"platform_id = {TENANT_SETTING}",
    "platform_models": f"platform_id = {TENANT_SETTING}",
    "skill_packages": f"platform_id = {TENANT_SETTING}",
    "skill_script_executions": f"platform_id = {TENANT_SETTING}",
    "skills": f"platform_id = {TENANT_SETTING}",
    "tasks": f"platform_id = {TENANT_SETTING}",
    "tool_confirmations": f"platform_id = {TENANT_SETTING}",
    "user_memories": f"platform_id = {TENANT_SETTING}",
    "wechat_bot_bindings": f"platform_id = {TENANT_SETTING}",
    "workflows": f"platform_id = {TENANT_SETTING}",
    # ---- 租户根表：锚点就是它自己的主键 ----
    "platforms": f"id = {TENANT_SETTING}",
    # ---- 22 张一跳子表：经非空外键回到租户表 ----
    # 父表选择遵循「非空外键 + 父表有 platform_id」；同一子表有多条路径时取
    # 语义上最贴近归属的那条（如 agent_subagents 取 parent_agent_id）。
    "agent_host_tools": _child_predicate("agent_host_tools", "agents", "agent_id"),
    "agent_knowledge_bases": _child_predicate(
        "agent_knowledge_bases", "agents", "agent_id"
    ),
    # agent_loop_runs 挂会话而非 agent：一次运行可能跨 agent 版本，但会话归属唯一。
    "agent_loop_runs": _child_predicate(
        "agent_loop_runs", "conversations", "conversation_id"
    ),
    "agent_mcp_servers": _child_predicate("agent_mcp_servers", "agents", "agent_id"),
    "agent_model_bindings": _child_predicate(
        "agent_model_bindings", "agents", "agent_id"
    ),
    "agent_skills": _child_predicate("agent_skills", "agents", "agent_id"),
    # 子 agent 关系按「父 agent 属于哪个平台」判定；父子同平台由业务侧保证。
    "agent_subagents": _child_predicate(
        "agent_subagents", "agents", "parent_agent_id"
    ),
    "agent_versions": _child_predicate("agent_versions", "agents", "agent_id"),
    "conversation_asset_chunks": _child_predicate(
        "conversation_asset_chunks", "conversations", "conversation_id"
    ),
    "conversation_asset_embeddings": _child_predicate(
        "conversation_asset_embeddings", "conversations", "conversation_id"
    ),
    "conversation_asset_processing": _child_predicate(
        "conversation_asset_processing", "conversations", "conversation_id"
    ),
    "conversation_context_compactions": _child_predicate(
        "conversation_context_compactions", "conversations", "conversation_id"
    ),
    "conversation_messages": _child_predicate(
        "conversation_messages", "conversations", "conversation_id"
    ),
    "embed_client_host_tools": _child_predicate(
        "embed_client_host_tools", "platform_embed_clients", "client_id"
    ),
    "knowledge_chunks": _child_predicate(
        "knowledge_chunks", "knowledge_bases", "knowledge_base_id"
    ),
    "knowledge_documents": _child_predicate(
        "knowledge_documents", "knowledge_bases", "knowledge_base_id"
    ),
    "knowledge_ingestion_tasks": _child_predicate(
        "knowledge_ingestion_tasks", "knowledge_bases", "knowledge_base_id"
    ),
    "mcp_tools": _child_predicate("mcp_tools", "mcp_servers", "server_id"),
    "platform_embed_client_agents": _child_predicate(
        "platform_embed_client_agents", "platform_embed_clients", "client_id"
    ),
    "skill_package_files": _child_predicate(
        "skill_package_files", "skill_packages", "package_id"
    ),
    "task_runs": _child_predicate("task_runs", "tasks", "task_id"),
    "workflow_runs": _child_predicate("workflow_runs", "workflows", "workflow_id"),
    # ---- 两跳子表 ----
    # agent_loop_steps 没有 conversation_id，只能经 agent_loop_runs 回到 conversations。
    "agent_loop_steps": (
        "EXISTS (SELECT 1 FROM agent_loop_runs r "
        "JOIN conversations c ON c.id = r.conversation_id "
        "WHERE r.id = agent_loop_steps.loop_run_id "
        f"AND c.platform_id = {TENANT_SETTING})"
    ),
    # workflow_step_runs 的 run_id 非空指向 workflow_runs，而 workflow_runs 没有
    # platform_id；若改走可空的 conversation_id（只有 agent 步骤才有），tool 型
    # 步骤行会对 reader 整片消失。所以按 run_id → workflow_runs → workflows 两跳，
    # 覆盖全部步骤行。
    "workflow_step_runs": (
        "EXISTS (SELECT 1 FROM workflow_runs r "
        "JOIN workflows w ON w.id = r.workflow_id "
        "WHERE r.id = workflow_step_runs.run_id "
        f"AND w.platform_id = {TENANT_SETTING})"
    ),
    # ---- 本迁移新建的审计表（自身带 platform_id） ----
    "db_query_audits": f"platform_id = {TENANT_SETTING}",
}

# 启用 RLS 但**不建策略**＝默认拒绝所有行。这四张表要么是全局表，要么含敏感列：
# - sys_users：含密码哈希与登录资料，reader 一行都不该看到；
# - sys_roles / sys_user_roles：全局 RBAC 配置，不属于任何平台；
# - alembic_version：技术表，与业务数据无关。
RLS_DENY_ALL_TABLES: tuple[str, ...] = (
    "sys_users",
    "sys_roles",
    "sys_user_roles",
    "alembic_version",
)

# 这些函数在 PostgreSQL 里默认对 PUBLIC 可执行，而 reader 只需要 SELECT。
# 一旦保留执行权，一条普通 SELECT 就能越出「只读同平台」的边界：
# - set_config(text,text,boolean)：直接改写本事务的 app.platform_id → RLS 失效
#   （实测：会话 GUC=2 时 select count(*) from (select
#   set_config('app.platform_id','1',true)) s, conversations c 能读到平台 1）；
# - pg_terminate_backend / pg_cancel_backend：杀掉别人的查询；
# - pg_read_file / pg_read_binary_file / pg_ls_dir / pg_stat_file：读写服务端文件；
# - lo_import / lo_export：大对象的文件导入导出。
DANGEROUS_FUNCTIONS: tuple[str, ...] = (
    "set_config",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
)


def _create_audit_table() -> None:
    """建只读查库审计账本。列注释是该表的自描述，db_schema 工具会读它。"""
    op.create_table(
        "db_query_audits",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            primary_key=True,
            comment="审计记录主键；审计是写入量最大的表，用大整数避免溢出",
        ),
        sa.Column(
            "platform_id",
            sa.BigInteger(),
            nullable=True,
            comment=(
                "查询所在平台 ID；平台上下文尚未解析就失败时为空，"
                "这类记录对 agent_reader 不可见"
            ),
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            nullable=True,
            comment="发起查询的智能体 ID；无智能体上下文的调用为空",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=True,
            comment="发起查询的会话 ID；后台独立调用时为空",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="发起查询的平台用户 ID；系统或终端用户触发时为空",
        ),
        sa.Column(
            "tool_name",
            sa.String(length=64),
            nullable=False,
            comment="被调用的内置工具名：db_schema 或 db_query",
        ),
        sa.Column(
            "sql_digest",
            sa.String(length=512),
            nullable=False,
            comment="脱敏并截断后的 SQL 文本，供人工复核；不保存完整原始 SQL",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment="调用结果状态：ok 成功 / rejected 校验拒绝 / timeout 超时 / error 执行出错",
        ),
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
            comment="失败时的稳定错误码（如 db_sql_rejected、db_timeout），成功时为空",
        ),
        sa.Column(
            "row_count",
            sa.Integer(),
            nullable=True,
            comment="实际返回给模型的行数；被拒绝或失败时为空",
        ),
        sa.Column(
            "truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="结果是否因行数、单元格长度或总字节上限被截断",
        ),
        sa.Column(
            "elapsed_ms",
            sa.Integer(),
            nullable=True,
            comment="从开始执行到得到结果的耗时（毫秒）；未进入执行阶段时为空",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间（UTC）",
        ),
        # if_not_exists：迁移半途失败后重跑时表可能已建好，CREATE TABLE 报
        # duplicate_table 会让整批（含后面 54 次 RLS 设置）一起回滚。
        if_not_exists=True,
    )
    # created_at 支撑「按时间倒查最近查询」；platform_id+created_at 支撑平台维度
    # 的时间窗检索；agent_id 支撑「这个 Agent 最近查了什么」。
    op.create_index(
        "ix_db_query_audits_created_at",
        "db_query_audits",
        ["created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_db_query_audits_platform_id_created_at",
        "db_query_audits",
        ["platform_id", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_db_query_audits_agent_id",
        "db_query_audits",
        ["agent_id"],
        if_not_exists=True,
    )


def _create_reader_role() -> None:
    """建 NOLOGIN 角色；已存在则跳过，重复执行本迁移不会报角色已存在。"""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
                CREATE ROLE {READER_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )


def _grant_reader_privileges() -> None:
    """只授只读：schema 可见 + 全部表 SELECT + 未来新表默认 SELECT。"""
    op.execute(f"GRANT USAGE ON SCHEMA public TO {READER_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER_ROLE}")
    # 审计表是上面的全表授权的例外：db_query_audits 存的是同平台其它会话/用户的
    # SQL 摘要与错误码，reader 读它等于能窥探他人查了什么，必须单独收回。
    op.execute(f"REVOKE SELECT ON TABLE db_query_audits FROM {READER_ROLE}")
    # 默认权限只解决「未来新表自动可读」，**不解决隔离**：root 之后建的每张表都会
    # 自动拿到 SELECT，但不会自动有 RLS 策略。所以新表必须在同一个迁移里补
    # tenant_isolation 策略（参照 RLS_POLICIES）；漏了会被启动期覆盖检查拒绝启动。
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT ON TABLES TO {READER_ROLE}"
    )


def _set_dangerous_function_execute(revoke: bool) -> None:
    """收回／复原敏感函数对 PUBLIC 的 EXECUTE。

    拒绝路径（upgrade）解决的是 H1：``set_config(text,text,boolean)`` 默认对
    PUBLIC 可执行，一条合法 SELECT 就能改写事务内的 ``app.platform_id``，
    让 RLS 谓词按攻击者给的平台过滤（实测会话 GUC=2 时仍能读到平台 1 的行）。
    收回后 reader 只能靠应用侧的 ``SET LOCAL app.platform_id = '<int>'`` 写入
    GUC —— 那是普通 SET 语句，不经过函数执行权限。

    用 ``pg_proc`` 按 ``proname`` 动态枚举重载，而不是写死 ``text,text,boolean``
    这类签名：签名写错会让整个迁移在授权阶段直接失败，而且 PG 升级改签名时
    这里不会跟着碎。downgrade 用同一份名单复原，保持对称。
    """
    names = ", ".join(f"'{name}'" for name in DANGEROUS_FUNCTIONS)
    verb = "REVOKE" if revoke else "GRANT"
    grantee = "FROM PUBLIC" if revoke else "TO PUBLIC"
    op.execute(
        f"""
        DO $$
        DECLARE
            proc_signature text;
        BEGIN
            FOR proc_signature IN
                SELECT p.oid::regprocedure::text
                FROM pg_catalog.pg_proc p
                WHERE p.proname IN ({names})
            LOOP
                EXECUTE format(
                    '{verb} EXECUTE ON FUNCTION %s {grantee}',
                    proc_signature
                );
            END LOOP;
        END
        $$;
        """
    )


def _configure_reader_role() -> None:
    """角色级 GUC：只读事务 + 语句超时 + 空闲事务超时，作为应用层之外的兜底。"""
    op.execute(f"ALTER ROLE {READER_ROLE} SET default_transaction_read_only = on")
    op.execute(f"ALTER ROLE {READER_ROLE} SET statement_timeout = '5s'")
    op.execute(
        f"ALTER ROLE {READER_ROLE} SET idle_in_transaction_session_timeout = '15s'"
    )


def _enable_row_level_security() -> None:
    """逐表启用 RLS 并建隔离策略；清单来自静态字典，不做运行时外键推导。"""
    for table, predicate in RLS_POLICIES.items():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        # 先 DROP IF EXISTS 再 CREATE：策略已存在时 CREATE POLICY 报
        # duplicate_object，会把整批（含后面的表）一起回滚；重跑迁移必须幂等。
        op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON public.{table}")
        # USING 之外不写 WITH CHECK：FOR ALL 策略下 PostgreSQL 复用 USING 表达式
        # 校验新行，任何命令都受平台谓词约束。reader 本身没有写权限，写操作在
        # 权限层就已失败，策略只是让「隔离」对所有命令成立。
        op.execute(
            f"CREATE POLICY {POLICY_NAME} ON public.{table} FOR ALL USING ({predicate})"
        )
    for table in RLS_DENY_ALL_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # 54 次 ENABLE ROW LEVEL SECURITY 都要 ACCESS EXCLUSIVE 锁；等锁必须有上限，
    # 否则一条长事务／idle in transaction 就能让迁移无限挂起，并把它之后的全部
    # 读写堵在锁队列里（本机曾卡过一条 9 分钟的 idle in transaction 连接）。
    # alembic 在事务里执行，SET LOCAL 随事务结束自动失效。
    op.execute("SET LOCAL lock_timeout = '8s'")
    _create_audit_table()
    _create_reader_role()
    _grant_reader_privileges()
    _set_dangerous_function_execute(revoke=True)
    _configure_reader_role()
    _enable_row_level_security()


def downgrade() -> None:
    # 与 upgrade 同因：逐表 DISABLE 也要 ACCESS EXCLUSIVE，等锁不能无限。
    op.execute("SET LOCAL lock_timeout = '8s'")
    # 1) 逐表撤策略并关闭 RLS；策略名是本迁移独占的，先 DROP IF EXISTS 保证幂等。
    for table in (*RLS_POLICIES, *RLS_DENY_ALL_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    # 2) 审计表（不可逆：历史审计记录随表删除）。
    op.drop_table("db_query_audits")
    # 3) 先撤销所有授予，否则 DROP ROLE 会因对象依赖（表权限、默认权限）失败。
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT ON TABLES FROM {READER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {READER_ROLE}"
    )
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {READER_ROLE}")
    # 4) 复原敏感函数的 PUBLIC 执行权。这些函数对 PUBLIC 可执行本就是 PostgreSQL
    # 的默认状态，upgrade 只是临时收回；不回滚会让后续新建的普通角色无端受限。
    _set_dangerous_function_execute(revoke=False)
    # 5) 角色级 GUC 与密码随角色一起消失（不可逆：runbook 的 LOGIN/密码需重做）。
    op.execute(f"DROP ROLE IF EXISTS {READER_ROLE}")
