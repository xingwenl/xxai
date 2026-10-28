"""只读查询执行器：单个只读事务 + 平台 GUC + 三道上限。

一次查询的固定顺序（PostgreSQL 要求 SET TRANSACTION 必须是事务里第一条语句）：

1. ``BEGIN``
2. ``SET TRANSACTION READ ONLY``：即使角色配置被改动，事务本身也强制只读
3. ``SET LOCAL app.platform_id``：写事务局部 GUC，RLS 策略据此过滤；这里刻意不用
   ``set_config()`` 函数——该函数已由迁移从 PUBLIC 收回执行权限，应用层改用 SET LOCAL
   也就不会留下「模型 SQL 改写 GUC 越权」的口子
4. ``SET LOCAL statement_timeout``：只作用于当前事务，超时由数据库取消
5. 执行 guard 包好 LIMIT 的 SQL，``fetchmany(max_rows + 1)`` 判断是否还有更多行
6. 单元格与总字节预算截断

校验（``check_sql``）放在取连接之前：注定失败的 SQL 不必占用连接，这也是 ADR
「校验在前、事务在后」的落点。
"""

from __future__ import annotations

import asyncio
import datetime
import decimal
import json
import time
import uuid
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.db_query.engine import get_reader_engine
from app.modules.db_query.guard import check_sql

logger = get_logger(__name__)

# 数据库侧 statement_timeout 之外再兜一层客户端超时；多出的宽限用于
# 建立连接、SET LOCAL 等事务准备动作，避免把准备耗时算进查询超时。
_CLIENT_TIMEOUT_GRACE_SECONDS = 2.0

# 单次 db_schema 最多返回多少张表的完整结构（防御模型随手要全量导致上下文爆炸）。
_MAX_SCHEMA_TABLES = 200


class ReaderNotConfiguredError(RuntimeError):
    """未配置 DATABASE_READER_URL，只读查库能力未开通。"""


class ReaderQueryTooLarge(RuntimeError):
    """单行结果就超出总字节预算，返回任何数据都没有意义。"""


def client_timeout_seconds(timeout_ms: int) -> float:
    """客户端超时 = 数据库语句超时 + 事务准备宽限。

    ``run_readonly_query`` 与调用方的 ``fetch_schema`` 都从这里取，保证两条路径的
    超时语义（以及工具层返回 ``db_timeout`` 的时机）完全一致。
    """
    return max(int(timeout_ms), 1) / 1000 + _CLIENT_TIMEOUT_GRACE_SECONDS


def _normalize_cell(value: Any) -> Any:
    """把驱动返回值转换成 JSON 可序列化的单元格。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, dict)):
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
        return value
    return str(value)


def _cell_to_json_text(cell: Any) -> str:
    return json.dumps(cell, ensure_ascii=False, default=str)


def _truncate_cell(value: Any, max_cell_chars: int) -> tuple[Any, bool]:
    """超过 ``max_cell_chars`` 的单元格截断到恰好该字符数，返回 (值, 是否截断)。"""
    cell = _normalize_cell(value)
    if isinstance(cell, str):
        if len(cell) > max_cell_chars:
            return cell[:max_cell_chars], True
        return cell, False

    json_text = _cell_to_json_text(cell)
    if len(json_text) > max_cell_chars:
        return json_text[:max_cell_chars], True
    return cell, False


def _cell_bytes(cell: Any) -> int:
    return len(_cell_to_json_text(cell).encode("utf-8"))


async def _load_type_names(
    conn: AsyncConnection, type_oids: list[int]
) -> dict[int, str]:
    """把 pg_type OID 映射成可读类型名（``format_type`` 输出，如 integer）。"""
    unique_oids = sorted({oid for oid in type_oids if oid and oid > 0})
    if not unique_oids:
        return {}

    statement = text(
        "SELECT oid, format_type(oid, NULL) AS type_name "
        "FROM pg_catalog.pg_type WHERE oid IN :oids"
    ).bindparams(bindparam("oids", expanding=True))
    result = await conn.execute(statement, {"oids": unique_oids})
    return {int(oid): str(type_name) for oid, type_name in result.all()}


async def _describe_columns(conn: AsyncConnection, result: Any) -> list[dict[str, str]]:
    """根据游标 description 生成 ``[{"name", "type"}]``。

    asyncpg 方言把 ``cursor.description[i][1]`` 放成类型 OID，这里再查一次
    pg_type 换成人类可读的类型名；取不到时退化为 ``unknown``，不影响数据返回。
    """
    names = list(result.keys())
    oids: list[int | None] = [None] * len(names)
    cursor = getattr(result, "cursor", None)
    description = getattr(cursor, "description", None) if cursor is not None else None
    if description:
        for index, entry in enumerate(description[: len(names)]):
            oid = entry[1] if len(entry) > 1 else None
            if isinstance(oid, int) and oid > 0:
                oids[index] = oid

    try:
        type_names = await _load_type_names(conn, [oid for oid in oids if oid])
    except Exception:  # noqa: BLE001 - 类型名是锦上添花，查不到不能影响数据
        logger.debug("查询列类型名失败，退化为 unknown", exc_info=True)
        type_names = {}

    columns: list[dict[str, str]] = []
    for index, name in enumerate(names):
        oid = oids[index]
        type_name = type_names.get(oid, "unknown") if oid else "unknown"
        columns.append({"name": str(name), "type": type_name})
    return columns


async def _execute_readonly(
    engine: AsyncEngine,
    *,
    platform_id: int,
    final_sql: str,
    max_rows: int,
    max_bytes: int,
    max_cell_chars: int,
    timeout_ms: int,
) -> dict[str, Any]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            # 只读事务（必须在事务第一条语句设置）
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            # 事务局部 GUC：RLS 策略用 current_setting('app.platform_id', true) 取值。
            # 刻意不用 set_config()：该函数已由迁移从 PUBLIC 收回执行权限，应用层若还依赖
            # 它，权限模型上就留了「模型 SQL 也能改写 GUC」的口子。SET 不支持绑定参数，
            # 这里先用 int() 强制校验（非法值抛 ValueError，属于调用方 bug），再格式化进 SQL，
            # 不存在注入面。
            await conn.execute(
                text(f"SET LOCAL app.platform_id = '{int(platform_id)}'")
            )
            # statement_timeout 只作用于本事务；SET 不支持绑定参数，只能格式化整数
            await conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))

            result = await conn.execute(text(final_sql))
            columns = await _describe_columns(conn, result)

            fetched = result.fetchmany(max_rows + 1)
            row_overflow = len(fetched) > max_rows
            if row_overflow:
                fetched = fetched[:max_rows]

            rows: list[list[Any]] = []
            total_bytes = 0
            truncated = False
            truncated_reason: str | None = None
            cell_truncated = False

            for raw_row in fetched:
                cells: list[Any] = []
                row_cell_truncated = False
                for value in raw_row:
                    cell, was_truncated = _truncate_cell(value, max_cell_chars)
                    cells.append(cell)
                    row_cell_truncated = row_cell_truncated or was_truncated
                row_bytes = sum(_cell_bytes(cell) for cell in cells)

                if total_bytes + row_bytes > max_bytes:
                    if not rows:
                        raise ReaderQueryTooLarge("查询结果单行即超过结果字节上限")
                    truncated = True
                    truncated_reason = "max_bytes"
                    break

                rows.append(cells)
                total_bytes += row_bytes
                cell_truncated = cell_truncated or row_cell_truncated

            if row_overflow:
                truncated = True
                truncated_reason = "max_rows"
            elif truncated_reason is None and cell_truncated:
                truncated = True
                truncated_reason = "max_cell_chars"
        finally:
            # 只读事务不需要提交，显式回滚释放快照
            if transaction.is_active:
                try:
                    await transaction.rollback()
                except Exception:  # noqa: BLE001 - 回滚失败不能掩盖原始异常
                    logger.debug("只读事务回滚失败", exc_info=True)

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "truncated_reason": truncated_reason,
    }


async def run_readonly_query(
    *,
    platform_id: int,
    sql: str,
    max_rows: int,
    max_bytes: int,
    max_cell_chars: int,
    timeout_ms: int,
) -> dict[str, Any]:
    """在只读事务里执行一条 SQL，返回列信息、行数据与截断状态。"""
    engine = get_reader_engine()
    if engine is None:
        raise ReaderNotConfiguredError("只读查库连接未配置")

    # 校验在前：不合规的 SQL 直接拒绝，不占用连接
    final_sql = check_sql(sql, max_rows=max_rows)

    started_at = time.perf_counter()
    payload = await asyncio.wait_for(
        _execute_readonly(
            engine,
            platform_id=platform_id,
            final_sql=final_sql,
            max_rows=max_rows,
            max_bytes=max_bytes,
            max_cell_chars=max_cell_chars,
            timeout_ms=timeout_ms,
        ),
        timeout=client_timeout_seconds(timeout_ms),
    )
    payload["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    return payload


# ---------------------------------------------------------------------------
# db_schema：表结构
# ---------------------------------------------------------------------------

# 只暴露「reader 角色读得到数据」的表：public schema 下的普通表、已开 RLS 且至少
# 有一条策略。sys_users / sys_roles / sys_user_roles / alembic_version 这类全局表
# 没有策略（默认拒绝），不出现在结构查询里，避免模型误以为可以查它们。
_TABLE_QUERY = """
SELECT c.relname AS table_name,
       obj_description(c.oid, 'pg_class') AS table_comment
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND c.relrowsecurity
  AND has_table_privilege(c.oid, 'SELECT')
  AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_policy p WHERE p.polrelid = c.oid
  )
  {table_filter}
ORDER BY c.relname
"""

_COLUMN_QUERY = """
SELECT c.relname AS table_name,
       a.attnum AS column_number,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       col_description(c.oid, a.attnum) AS column_comment,
       NOT a.attnotnull AS nullable
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND a.attnum > 0
  AND NOT a.attisdropped
  {table_filter}
ORDER BY c.relname, a.attnum
"""

_CONSTRAINT_QUERY = """
SELECT c.relname AS table_name,
       con.contype AS constraint_type,
       con.conkey AS column_numbers,
       ref.relname AS references_table,
       con.confkey AS references_column_numbers
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_class ref ON ref.oid = con.confrelid
WHERE n.nspname = 'public'
  AND con.contype IN ('p', 'f')
  {table_filter}
ORDER BY c.relname, con.conname
"""


def _normalize_table_names(table_names: list[str] | None) -> list[str]:
    """清洗表名过滤参数：去空白、去重、限制数量；空列表视为「不过滤」。"""
    if not table_names:
        return []

    cleaned: list[str] = []
    for name in table_names:
        if not isinstance(name, str):
            continue
        stripped = name.strip()
        if stripped and stripped not in cleaned:
            cleaned.append(stripped)
        if len(cleaned) >= _MAX_SCHEMA_TABLES:
            break
    return cleaned


def _with_table_filter(
    template: str, table_names: list[str], params: dict[str, Any]
) -> Any:
    """按需拼上表名过滤子句（表名走绑定参数，不拼字符串）。"""
    if not table_names:
        return text(template.format(table_filter=""))

    params["table_names"] = table_names
    statement = text(
        template.format(table_filter="AND c.relname IN :table_names")
    ).bindparams(bindparam("table_names", expanding=True))
    return statement


async def _fetch_tables(conn: AsyncConnection, table_names: list[str]) -> list[Any]:
    params: dict[str, Any] = {}
    statement = _with_table_filter(_TABLE_QUERY, table_names, params)
    result = await conn.execute(statement, params)
    return result.all()


async def _fetch_columns(conn: AsyncConnection, table_names: list[str]) -> list[Any]:
    params: dict[str, Any] = {}
    statement = _with_table_filter(_COLUMN_QUERY, table_names, params)
    result = await conn.execute(statement, params)
    return result.all()


async def _fetch_constraints(
    conn: AsyncConnection, table_names: list[str]
) -> list[Any]:
    params: dict[str, Any] = {}
    statement = _with_table_filter(_CONSTRAINT_QUERY, table_names, params)
    result = await conn.execute(statement, params)
    return result.all()


def _assemble_schema(
    table_rows: list[Any],
    column_rows: list[Any],
    constraint_rows: list[Any],
    *,
    include_columns: bool,
) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    for row in table_rows:
        name = str(row[0])
        tables[name] = {
            "name": name,
            "comment": row[1],
            "columns": [],
            "primary_key": [],
            "foreign_keys": [],
        }

    # (表名, attnum) -> 列名，用于把主键/外键的列号翻译成列名
    column_names: dict[tuple[str, int], str] = {}
    for row in column_rows:
        table_name = str(row[0])
        column_number = int(row[1])
        column_name = str(row[2])
        column_names[(table_name, column_number)] = column_name

        table = tables.get(table_name)
        if table is None or not include_columns:
            continue
        table["columns"].append(
            {
                "name": column_name,
                "type": str(row[3]),
                "comment": row[4],
                "nullable": bool(row[5]),
            }
        )

    for row in constraint_rows:
        table_name = str(row[0])
        constraint_type = str(row[1])
        column_numbers = row[2] or []
        references_table = str(row[3]) if row[3] is not None else None
        references_numbers = row[4] or []

        table = tables.get(table_name)
        if table is None:
            continue

        columns = [
            column_names.get((table_name, int(number)), f"#{number}")
            for number in column_numbers
        ]
        if constraint_type == "p":
            table["primary_key"] = columns
            continue

        references_columns = [
            column_names.get((references_table or "", int(number)), f"#{number}")
            for number in references_numbers
        ]
        table["foreign_keys"].append(
            {
                "columns": columns,
                "references_table": references_table,
                "references_columns": references_columns,
            }
        )

    return {
        "tables": list(tables.values()),
        "table_count": len(tables),
    }


async def fetch_schema(
    *, table_names: list[str] | None, include_columns: bool
) -> dict[str, Any]:
    """读取表结构（表名、中文注释、列、主键、外键）。

    只读结构信息，不涉及租户数据，因此不需要设置平台 GUC；但仍使用只读引擎和
    只读事务，避免这条旁路能力在任何情况下变成写入口。

    ``include_columns=False`` 时只查表名与表注释，列/主键/外键三条查询直接跳过：
    全量列信息（实测 88 KB）会撑爆单次结果预算，而「有哪些表」这一步用不到它们。
    """
    engine = get_reader_engine()
    if engine is None:
        raise ReaderNotConfiguredError("只读查库连接未配置")

    names = _normalize_table_names(table_names)
    timeout_ms = get_settings().db_query_statement_timeout_ms

    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            table_rows = await _fetch_tables(conn, names)
            if include_columns:
                column_rows = await _fetch_columns(conn, names)
                constraint_rows = await _fetch_constraints(conn, names)
            else:
                column_rows = []
                constraint_rows = []
        finally:
            if transaction.is_active:
                try:
                    await transaction.rollback()
                except Exception:  # noqa: BLE001
                    logger.debug("表结构查询事务回滚失败", exc_info=True)

    return _assemble_schema(
        table_rows,
        column_rows,
        constraint_rows,
        include_columns=include_columns,
    )
