"""db_query_audits 审计写入。

两个只读工具都是 ``side_effect="none"``（不弹审批卡），审计表是事后追溯的唯一凭据，
所以**每次调用**（含被拒绝、超时）都要落一条记录。

实现要点：

- 用应用引擎的独立会话写库，不复用工具上下文里的 session（避免把审计写入绑定到
  调用方的事务，也避免查询失败时污染调用方会话）；
- 用 ``text()`` 显式列名 INSERT，不依赖 ORM 模型（模型不随该能力一起建）；
- 整段 try/except 兜底：审计失败只告警，不能阻断查询本身。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from app.core.database import get_session_factory
from app.core.logging import get_logger

logger = get_logger(__name__)

_VALID_STATUSES: frozenset[str] = frozenset({"ok", "rejected", "timeout", "error"})

_MAX_DIGEST_CHARS = 500

# 敏感键名（列名/参数名）出现在字面量左侧时，把右侧字面量抹掉
_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "credential",
)

_QUOTED_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_LITERAL_LEFT_IDENTIFIER_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*"
    r"(?:=\s*|like\s+|ilike\s+|in\s*\(\s*)?$",
    re.IGNORECASE,
)

_INSERT_AUDIT_SQL = text("""
    INSERT INTO db_query_audits (
        platform_id,
        agent_id,
        conversation_id,
        user_id,
        tool_name,
        sql_digest,
        status,
        error_code,
        row_count,
        truncated,
        elapsed_ms
    ) VALUES (
        :platform_id,
        :agent_id,
        :conversation_id,
        :user_id,
        :tool_name,
        :sql_digest,
        :status,
        :error_code,
        :row_count,
        :truncated,
        :elapsed_ms
    )
    """)


def _contains_sensitive_keyword(identifier: str) -> bool:
    lowered = identifier.lower()
    return any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS)


def build_sql_digest(sql: str, *, max_chars: int = _MAX_DIGEST_CHARS) -> str:
    """生成可入库的 SQL 摘要：折叠空白、抹掉敏感字面量、截断长度。"""
    normalized = re.sub(r"\s+", " ", (sql or "").strip())
    if not normalized:
        return ""

    def _redact(match: re.Match[str]) -> str:
        prefix = match.string[: match.start()]
        identifier_match = _LITERAL_LEFT_IDENTIFIER_RE.search(prefix)
        if identifier_match and _contains_sensitive_keyword(identifier_match.group(1)):
            return "'[REDACTED]'"
        return match.group(0)

    redacted = _QUOTED_LITERAL_RE.sub(_redact, normalized)
    if len(redacted) > max_chars:
        return redacted[: max_chars - 1] + "…"
    return redacted


async def record_audit(
    *,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    tool_name: str,
    sql_digest: str,
    status: str,
    error_code: str | None = None,
    row_count: int | None = None,
    truncated: bool = False,
    elapsed_ms: int | None = None,
) -> None:
    """写一条查库审计；任何失败都只记 warning，不向上抛。"""
    normalized_status: Any = status if status in _VALID_STATUSES else "error"
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            # 审计表自己也开了 RLS（账本里是同平台其它会话的 SQL 摘要），写入必须显式
            # 声明租户。现在的应用连接是超级用户，策略对它不生效，看不出来；换成普通
            # 应用角色后会因 WITH CHECK 失败而被下面的 except 静默吞掉——所以这里先把
            # 平台上下文设好，别把正确性押在「应用是超级用户」上。
            await session.execute(
                text(f"SET LOCAL app.platform_id = '{int(platform_id)}'")
            )
            await session.execute(
                _INSERT_AUDIT_SQL,
                {
                    "platform_id": platform_id,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "sql_digest": sql_digest,
                    "status": normalized_status,
                    "error_code": error_code,
                    "row_count": row_count,
                    "truncated": bool(truncated),
                    "elapsed_ms": elapsed_ms,
                },
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - 审计失败不能影响查询
        logger.warning(
            "db_query 审计写入失败（不影响查询） tool=%s platform_id=%s",
            tool_name,
            platform_id,
            exc_info=True,
        )
