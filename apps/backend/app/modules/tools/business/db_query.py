"""db_schema / db_query 业务工具：只读查询本平台数据。

两个工具都是 ``side_effect="none"``：不弹审批卡，靠 db_query_audits 事后追溯。
真正的隔离在数据库侧（独立 reader 角色只有 SELECT、全表 RLS、只读事务、语句超时），
这里只负责参数校验、错误码收口与审计，不透传驱动原始异常。

错误码（稳定契约，模型与验证脚本都依赖）：

- ``db_reader_not_configured``：未配置 DATABASE_READER_URL、连接串非法，或连接层失败
  （密码错、角色被收回 LOGIN、库不可达）——都是配置问题、要管理员改，重试没有意义；
- ``db_sql_rejected``：SQL 不是单条只读查询（含空 SQL）；
- ``db_timeout``：语句超时、客户端超时或被取消；
- ``db_result_too_large``：单行/表结构超出结果预算；
- ``db_error``：其他查库失败（原始异常只写日志）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import asyncpg
from sqlalchemy.exc import ArgumentError, DBAPIError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.db_query.audits import build_sql_digest, record_audit
from app.modules.db_query.engine import get_reader_engine
from app.modules.db_query.guard import SqlRejected
from app.modules.db_query.runner import (
    ReaderNotConfiguredError,
    ReaderQueryTooLarge,
    client_timeout_seconds,
    fetch_schema,
    run_readonly_query,
)
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)

logger = get_logger(__name__)

_TOOL_DB_SCHEMA = "db_schema"
_TOOL_DB_QUERY = "db_query"

# 数据库侧 statement_timeout 触发后 asyncpg 返回的 SQLSTATE（query_canceled）
_STATEMENT_TIMEOUT_SQLSTATE = "57014"

_MAX_DIGEST_CHARS = 500

_READER_NOT_CONFIGURED_MESSAGE = "查库能力未开通，请联系管理员配置只读数据库连接"
_TIMEOUT_MESSAGE = "查询超时，请缩小查询范围（增加更精确的过滤条件）后重试"
_GENERIC_ERROR_MESSAGE = "查库失败，请稍后重试；持续失败请联系管理员"
_RESULT_TOO_LARGE_MESSAGE = "查询结果过大，请减少返回列或增加过滤条件"
_SCHEMA_TOO_LARGE_MESSAGE = "表结构返回过大，请用 tables 参数只查看需要的表"

_DB_SCHEMA_DESCRIPTION = (
    "查看本平台数据库的表结构。分两步用："
    "① 不传 tables 时只返回「表名 + 中文表注释」，用来确认有哪些表、表是干什么的；"
    "② 需要列名/类型/主键/外键时，把表名放进 tables（可一次传多张）。"
    "include_columns 只在同时传了 tables 时才生效（默认 true），"
    "省略 tables 时它被忽略——默认返回里没有列信息，这是刻意控制返回体积。"
    "只返回本平台可见的业务表，系统账号表、迁移版本表等全局表不会出现。"
    "表与列的注释来自数据库 COMMENT，可直接用来判断业务含义。"
)

_DB_QUERY_DESCRIPTION = (
    "在当前平台数据库上执行一条只读查询，返回列信息与数据行。"
    "用法：先用 db_schema 确认表结构；sql 只写单条 SELECT（可用 WITH），"
    "不要自己写 LIMIT（返回行数会被自动限制），也不要自己拼 platform_id 过滤条件，"
    "数据库已按当前平台隔离数据。"
    "结果字段：columns 为列名与类型，rows 为数据行数组，row_count 为行数，"
    "truncated=true 表示结果被截断，truncated_reason 说明是行数（max_rows）、"
    "单元格（max_cell_chars）还是总字节（max_bytes）超限。"
    "单次最多返回 200 行；超时或结果过大时请缩小查询范围后重试。"
)

_DB_SCHEMA_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tables": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "要查看列结构的表名列表。省略=只返回全部可见表的表名与表注释；"
                "传了=返回这些表的列/主键/外键"
            ),
        },
        "include_columns": {
            "type": "boolean",
            "description": (
                "是否返回列信息，默认 true；仅在同时传了 tables 时生效，省略 tables 时忽略"
            ),
        },
    },
    "required": [],
}

_DB_QUERY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "单条 SELECT 只读查询，不要写 LIMIT",
        },
        "max_rows": {
            "type": "integer",
            "description": "最多返回行数，上限 200",
        },
    },
    "required": ["sql"],
}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _clamp_max_rows(value: Any, configured_max_rows: int) -> int:
    """把模型给的 max_rows 收敛到 [1, 配置上限]；非法值回落到配置上限。"""
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = configured_max_rows
    return max(1, min(requested, max(1, configured_max_rows)))


def _parse_include_columns(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", ""}
    return bool(value)


def _normalize_requested_tables(value: Any) -> list[str]:
    """清洗 db_schema 的 tables 参数（去空白、去重，保持模型给的顺序）。"""
    if not isinstance(value, list):
        return []

    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def _schema_digest(table_names: list[str], include_columns: bool) -> str:
    """表结构查询没有 SQL，用参数摘要填充审计的 sql_digest 字段。"""
    tables = ",".join(table_names) if table_names else "*"
    digest = (
        f"db_schema tables={tables} " f"include_columns={str(include_columns).lower()}"
    )
    return digest[:_MAX_DIGEST_CHARS]


# 连接层失败的白名单：asyncpg 的认证/角色/库不存在错误 + 套接字错误。这些都不是
# 「SQL 写错了」，而是 reader 连接串失效（密码轮换、角色被收回 LOGIN、库没起），
# 归到 db_reader_not_configured 才不会把模型引向无意义的重试。
_READER_CONNECTION_ERROR_NAMES = frozenset(
    {
        "InvalidPasswordError",
        "InvalidAuthorizationSpecificationError",
        "InvalidCatalogNameError",
        "CannotConnectNowError",
        "ConnectionDoesNotExistError",
        "ConnectionFailureError",
    }
)


def _is_reader_connection_error(exc: BaseException) -> bool:
    """判断异常是否属于「只读连接不可用」（配置问题，而非 SQL 问题）。"""
    if isinstance(exc, (ConnectionError, OSError)):
        return True
    return (
        type(exc).__name__ in _READER_CONNECTION_ERROR_NAMES
        and type(exc).__module__.startswith("asyncpg")
    )


def _is_statement_timeout(exc: BaseException) -> bool:
    """判断异常是否由 statement_timeout / 客户端超时导致。"""
    if isinstance(exc, (asyncio.TimeoutError, asyncpg.QueryCanceledError)):
        return True
    if isinstance(exc, DBAPIError):
        original = exc.orig
        sqlstate = getattr(original, "sqlstate", None) or getattr(
            original, "pgcode", None
        )
        if sqlstate == _STATEMENT_TIMEOUT_SQLSTATE:
            return True
        cause = getattr(original, "__cause__", None)
        if isinstance(original, asyncpg.QueryCanceledError) or isinstance(
            cause, asyncpg.QueryCanceledError
        ):
            return True
    return False


async def _audit(
    ctx: BusinessToolContext,
    *,
    tool_name: str,
    sql_digest: str,
    status: str,
    started_at: float,
    error_code: str | None = None,
    row_count: int | None = None,
    truncated: bool = False,
    elapsed_ms: int | None = None,
) -> None:
    await record_audit(
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        conversation_id=ctx.conversation_id,
        user_id=ctx.user_id,
        tool_name=tool_name,
        sql_digest=sql_digest,
        status=status,
        error_code=error_code,
        row_count=row_count,
        truncated=truncated,
        elapsed_ms=elapsed_ms if elapsed_ms is not None else _elapsed_ms(started_at),
    )


async def _reject(
    ctx: BusinessToolContext,
    *,
    tool_name: str,
    sql_digest: str,
    status: str,
    error_code: str,
    message: str,
    started_at: float,
) -> None:
    """落审计后抛出稳定错误码（审计失败不影响抛错）。"""
    await _audit(
        ctx,
        tool_name=tool_name,
        sql_digest=sql_digest,
        status=status,
        started_at=started_at,
        error_code=error_code,
    )
    raise BusinessToolError(error_code, message=message)


@business_tool(
    name=_TOOL_DB_SCHEMA,
    description=_DB_SCHEMA_DESCRIPTION,
    input_schema=_DB_SCHEMA_INPUT_SCHEMA,
    side_effect="none",
)
async def db_schema_tool(
    args: dict[str, Any], ctx: BusinessToolContext
) -> dict[str, Any]:
    settings = get_settings()
    started_at = time.perf_counter()
    table_names = _normalize_requested_tables(args.get("tables"))
    # M1：列信息只随「显式 tables」返回。默认（不传 tables）只给表名 + 表注释，
    # 否则全量列信息实测 88 KB，直接超过单次结果预算，模型第一次调用必然失败。
    include_columns = bool(table_names) and _parse_include_columns(
        args.get("include_columns")
    )
    sql_digest = _schema_digest(table_names, include_columns)

    try:
        if get_reader_engine() is None:
            raise ReaderNotConfiguredError("只读查库连接未配置")
        schema = await asyncio.wait_for(
            fetch_schema(
                table_names=table_names or None,
                include_columns=include_columns,
            ),
            # 与 run_readonly_query 共用同一份客户端超时口径（语句超时 + 准备宽限）
            timeout=client_timeout_seconds(settings.db_query_statement_timeout_ms),
        )
    except ArgumentError as exc:
        # reader 连接串写错（驱动前缀/DSN 非法）与「未配置」是同一种处置：都要管理员
        # 改配置，重试永远不会成功，所以复用 db_reader_not_configured，而不是让模型
        # 反复重试 db_error。
        logger.warning(
            "db_schema reader 连接串非法 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="error",
            error_code="db_reader_not_configured",
            message=_READER_NOT_CONFIGURED_MESSAGE,
            started_at=started_at,
        )
    except ReaderNotConfiguredError:
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="error",
            error_code="db_reader_not_configured",
            message=_READER_NOT_CONFIGURED_MESSAGE,
            started_at=started_at,
        )
    except SqlRejected as exc:  # 表结构查询不会触发，防御性收口
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="rejected",
            error_code="db_sql_rejected",
            message=exc.message,
            started_at=started_at,
        )
    except (asyncio.TimeoutError, asyncpg.QueryCanceledError) as exc:
        logger.warning(
            "db_schema 查询超时 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="timeout",
            error_code="db_timeout",
            message=_TIMEOUT_MESSAGE,
            started_at=started_at,
        )
    except DBAPIError as exc:
        if _is_statement_timeout(exc):
            logger.warning(
                "db_schema 查询超时 platform_id=%s sqlstate=57014",
                ctx.platform_id,
            )
            await _reject(
                ctx,
                tool_name=_TOOL_DB_SCHEMA,
                sql_digest=sql_digest,
                status="timeout",
                error_code="db_timeout",
                message=_TIMEOUT_MESSAGE,
                started_at=started_at,
            )
        logger.warning(
            "db_schema 查询失败 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
            exc_info=True,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="error",
            error_code="db_error",
            message=_GENERIC_ERROR_MESSAGE,
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 - 原始异常只进日志，不透给模型
        if _is_reader_connection_error(exc):
            logger.warning(
                "db_schema 只读连接不可用 platform_id=%s error=%s",
                ctx.platform_id,
                type(exc).__name__,
            )
            await _reject(
                ctx,
                tool_name=_TOOL_DB_SCHEMA,
                sql_digest=sql_digest,
                status="error",
                error_code="db_reader_not_configured",
                message=_READER_NOT_CONFIGURED_MESSAGE,
                started_at=started_at,
            )
        logger.warning(
            "db_schema 查询异常 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
            exc_info=True,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="error",
            error_code="db_error",
            message=_GENERIC_ERROR_MESSAGE,
            started_at=started_at,
        )
    except asyncio.CancelledError:
        # CancelledError 继承 BaseException，上面的 except Exception 接不住。被取消
        # （上层超时回收、客户端断开）同样要落审计，否则「每次调用都有审计」在取消
        # 路径上不成立；审计写完把取消继续抛给上层，绝不吞掉。
        logger.warning("db_schema 查询被取消 platform_id=%s", ctx.platform_id)
        await _audit(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="timeout",
            started_at=started_at,
            error_code="db_timeout",
        )
        raise

    payload_bytes = len(json.dumps(schema, ensure_ascii=False).encode("utf-8"))
    if payload_bytes > settings.db_query_max_result_bytes:
        logger.info(
            "db_schema 结果超出预算 platform_id=%s bytes=%s",
            ctx.platform_id,
            payload_bytes,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_SCHEMA,
            sql_digest=sql_digest,
            status="error",
            error_code="db_result_too_large",
            message=_SCHEMA_TOO_LARGE_MESSAGE,
            started_at=started_at,
        )

    await _audit(
        ctx,
        tool_name=_TOOL_DB_SCHEMA,
        sql_digest=sql_digest,
        status="ok",
        started_at=started_at,
        row_count=schema.get("table_count"),
    )
    return schema


@business_tool(
    name=_TOOL_DB_QUERY,
    description=_DB_QUERY_DESCRIPTION,
    input_schema=_DB_QUERY_INPUT_SCHEMA,
    side_effect="none",
)
async def db_query_tool(
    args: dict[str, Any], ctx: BusinessToolContext
) -> dict[str, Any]:
    settings = get_settings()
    started_at = time.perf_counter()
    sql = str(args.get("sql") or "").strip()
    sql_digest = build_sql_digest(sql)
    max_rows = _clamp_max_rows(args.get("max_rows"), settings.db_query_max_rows)

    if not sql:
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="rejected",
            error_code="db_sql_rejected",
            message="SQL 不能为空",
            started_at=started_at,
        )

    try:
        if get_reader_engine() is None:
            raise ReaderNotConfiguredError("只读查库连接未配置")
        result = await run_readonly_query(
            platform_id=ctx.platform_id,
            sql=sql,
            max_rows=max_rows,
            max_bytes=settings.db_query_max_result_bytes,
            max_cell_chars=settings.db_query_max_cell_chars,
            timeout_ms=settings.db_query_statement_timeout_ms,
        )
    except ArgumentError as exc:
        # reader 连接串非法（驱动前缀/DSN 解析失败）与「未配置」同一处置：属于配置
        # 问题，只能是管理员修，模型重试没有意义，因此复用 db_reader_not_configured。
        logger.warning(
            "db_query reader 连接串非法 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="error",
            error_code="db_reader_not_configured",
            message=_READER_NOT_CONFIGURED_MESSAGE,
            started_at=started_at,
        )
    except SqlRejected as exc:
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="rejected",
            error_code="db_sql_rejected",
            message=exc.message,
            started_at=started_at,
        )
    except ReaderQueryTooLarge as exc:
        logger.info(
            "db_query 结果超出预算 platform_id=%s reason=%s",
            ctx.platform_id,
            exc,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="error",
            error_code="db_result_too_large",
            message=_RESULT_TOO_LARGE_MESSAGE,
            started_at=started_at,
        )
    except ReaderNotConfiguredError:
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="error",
            error_code="db_reader_not_configured",
            message=_READER_NOT_CONFIGURED_MESSAGE,
            started_at=started_at,
        )
    except (asyncio.TimeoutError, asyncpg.QueryCanceledError) as exc:
        logger.warning(
            "db_query 执行超时 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="timeout",
            error_code="db_timeout",
            message=_TIMEOUT_MESSAGE,
            started_at=started_at,
        )
    except DBAPIError as exc:
        if _is_statement_timeout(exc):
            logger.warning(
                "db_query 执行超时 platform_id=%s sqlstate=57014",
                ctx.platform_id,
            )
            await _reject(
                ctx,
                tool_name=_TOOL_DB_QUERY,
                sql_digest=sql_digest,
                status="timeout",
                error_code="db_timeout",
                message=_TIMEOUT_MESSAGE,
                started_at=started_at,
            )
        logger.warning(
            "db_query 执行失败 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
            exc_info=True,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="error",
            error_code="db_error",
            message=_GENERIC_ERROR_MESSAGE,
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 - 原始异常只进日志，不透给模型
        if _is_reader_connection_error(exc):
            logger.warning(
                "db_query 只读连接不可用 platform_id=%s error=%s",
                ctx.platform_id,
                type(exc).__name__,
            )
            await _reject(
                ctx,
                tool_name=_TOOL_DB_QUERY,
                sql_digest=sql_digest,
                status="error",
                error_code="db_reader_not_configured",
                message=_READER_NOT_CONFIGURED_MESSAGE,
                started_at=started_at,
            )
        logger.warning(
            "db_query 执行异常 platform_id=%s error=%s",
            ctx.platform_id,
            type(exc).__name__,
            exc_info=True,
        )
        await _reject(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="error",
            error_code="db_error",
            message=_GENERIC_ERROR_MESSAGE,
            started_at=started_at,
        )
    except asyncio.CancelledError:
        # 取消路径也要留痕：CancelledError 是 BaseException，上面的 except Exception
        # 接不住。审计写完后原样抛出，取消语义不变。
        logger.warning("db_query 执行被取消 platform_id=%s", ctx.platform_id)
        await _audit(
            ctx,
            tool_name=_TOOL_DB_QUERY,
            sql_digest=sql_digest,
            status="timeout",
            started_at=started_at,
            error_code="db_timeout",
        )
        raise

    await _audit(
        ctx,
        tool_name=_TOOL_DB_QUERY,
        sql_digest=sql_digest,
        status="ok",
        started_at=started_at,
        row_count=result.get("row_count"),
        truncated=bool(result.get("truncated")),
        elapsed_ms=result.get("elapsed_ms"),
    )
    return result
