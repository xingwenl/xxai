"""启动期只读连接安全自检。

只读查库的租户隔离完全依赖两件事：连接角色真的受行级策略约束、每张业务表都开了
RLS 并且有策略。两者漏一个都不会报错，只会静默地让 reader 角色读到全部租户的数据，
因此把检查放在应用启动路径上（两项都「默认拒绝」，查不到就当违规）：

1. 角色身份：超级用户、``BYPASSRLS`` 角色、表 owner 都会绕过策略。把
   ``DATABASE_READER_URL`` 误配成应用自己的超级用户连接串是最容易发生的错误配置，
   必须在启动时拦住。
2. 策略覆盖：public 下**所有** BASE TABLE 都必须开 RLS；白名单之外的每张表还必须
   至少有一条策略。**不能只认 ``platform_id`` 列**：库里 22 张一跳子表、2 张两跳表
   没有该列（它们靠父表 RLS + 外键关联），按列筛选会让它们静默漏网，未来新增的子表
   也会以同样方式漏掉——所以默认拒绝，白名单显式放行。

本地/未开通该能力（``DATABASE_READER_URL`` 为空）时检查直接跳过，不影响应用启动。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.db_query.engine import get_reader_engine

logger = get_logger(__name__)

# 连接角色是否「真的受策略约束」：rolsuper / rolbypassrls / 是否 public 下任一张
# 表的 owner（表 owner 默认绕过 RLS，除非迁移对该表做了 FORCE）。
_ROLE_SAFETY_SQL = text("""
    SELECT r.rolname AS role_name,
           r.rolsuper,
           r.rolbypassrls,
           (
               SELECT count(*)
               FROM pg_catalog.pg_class c
               JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'public'
                 AND c.relkind = 'r'
                 AND c.relowner = r.oid
           ) AS owned_tables
    FROM pg_catalog.pg_roles r
    WHERE r.rolname = current_user
    """)

# 全局表（迁移版本、账号与角色）不含租户数据，本来就不该有租户策略，显式白名单放行。
_GLOBAL_TABLES: tuple[str, ...] = (
    "alembic_version",
    "sys_roles",
    "sys_user_roles",
    "sys_users",
)
_GLOBAL_TABLES_SQL_LIST = ", ".join(f"'{name}'" for name in _GLOBAL_TABLES)

# 违规表清单：UNION ALL 两段（未开 RLS 的 / 非白名单且没有任何策略的），
# ORDER BY 固定，保证同一份 schema 每次输出的顺序一致（便于排障与断言）。
_RLS_COVERAGE_SQL = text(f"""
    WITH violations AS (
        SELECT c.relname AS table_name, 'rls_disabled' AS reason
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND NOT c.relrowsecurity
        UNION ALL
        SELECT c.relname AS table_name, 'no_policy' AS reason
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname NOT IN ({_GLOBAL_TABLES_SQL_LIST})
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_policy p WHERE p.polrelid = c.oid
          )
    )
    SELECT table_name, reason
    FROM violations
    ORDER BY table_name, reason
    """)


def _role_safety_violation(row: Any) -> str | None:
    """把一行角色体检结果翻译成拒绝原因；合规时返回 None。"""
    role_name = str(row[0])
    is_superuser = bool(row[1])
    bypasses_rls = bool(row[2])
    owned_tables = int(row[3])

    if is_superuser:
        return f"只读查库角色 {role_name} 是超级用户（rolsuper），会绕过行级安全策略"
    if bypasses_rls:
        return f"只读查库角色 {role_name} 拥有 BYPASSRLS 权限，会绕过行级安全策略"
    if owned_tables > 0:
        return (
            f"只读查库角色 {role_name} 是 public 下 {owned_tables} 张表的 owner，"
            "表 owner 默认绕过行级安全策略"
        )
    return None


def _limits_violation(settings: Any) -> str | None:
    """检查五项查库上限是否都是正整数。

    ``DB_QUERY_MAX_ROWS=0`` 这类配置不会在导入期报错，却会让 ``guard.check_sql`` 拼
    ``LIMIT`` 时抛 ``ValueError``，模型只会看到一个模糊的 ``db_error``；因此在启动期
    直接暴露成配置错误。
    """
    checks = (
        ("DB_QUERY_STATEMENT_TIMEOUT_MS", settings.db_query_statement_timeout_ms),
        ("DB_QUERY_MAX_ROWS", settings.db_query_max_rows),
        ("DB_QUERY_MAX_RESULT_BYTES", settings.db_query_max_result_bytes),
        ("DB_QUERY_MAX_CELL_CHARS", settings.db_query_max_cell_chars),
        ("DB_QUERY_POOL_SIZE", settings.db_query_pool_size),
    )
    bad = [f"{name}={value}" for name, value in checks if int(value) <= 0]
    return ", ".join(bad) if bad else None


async def ensure_rls_coverage() -> None:
    """校验 reader 角色身份与全表 RLS 覆盖；未配置 reader 连接串时安全跳过。

    :raises RuntimeError: 查库上限配置非法、角色会绕过 RLS，或存在未开 RLS / 无策略的
      表（消息带角色名、表名与原因）。
    """
    settings = get_settings()

    limits_violation = _limits_violation(settings)
    if limits_violation:
        raise RuntimeError(f"查库上限配置必须是正整数，拒绝启动：{limits_violation}")

    if not (settings.database_reader_url or "").strip():
        # 本地没有 reader 角色也没有连接串：能力未开通，不拦启动
        return

    engine = get_reader_engine()
    if engine is None:
        return

    async with engine.connect() as conn:
        role_row = (await conn.execute(_ROLE_SAFETY_SQL)).first()
        coverage_rows = (await conn.execute(_RLS_COVERAGE_SQL)).all()

    # ---- H3：角色身份必须真的受策略约束（默认拒绝） ----
    if role_row is None:
        raise RuntimeError(
            "无法确认只读查库角色身份（pg_roles 里查不到 current_user），"
            "不能保证行级安全策略生效，拒绝启动"
        )

    role_violation = _role_safety_violation(role_row)
    if role_violation:
        raise RuntimeError(
            f"{role_violation}，只读查库会跨租户读取，拒绝启动"
        )

    # ---- H2：全表 RLS + 策略覆盖（默认拒绝） ----
    if not coverage_rows:
        logger.info("只读查库 RLS 覆盖检查通过 role=%s", role_row[0])
        return

    violations = [f"{row[0]}（{row[1]}）" for row in coverage_rows]
    raise RuntimeError(
        "以下 public 表未满足「开启 RLS 且（白名单外）至少一条策略」，"
        "只读查库会跨租户读取，拒绝启动："
        + ", ".join(violations)
    )
