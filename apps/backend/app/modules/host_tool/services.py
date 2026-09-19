from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Iterable

from jsonschema import ValidationError, validate

from app.modules.host_tool.schemas import HostToolStatus

_TRANSITIONS: dict[str, set[str]] = {
    "requested": {"awaiting_confirmation", "running"},
    "awaiting_confirmation": {"running", "rejected", "expired"},
    "running": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
    "rejected": set(),
    "expired": set(),
}


def as_utc(value: datetime | None) -> datetime | None:
    """把数据库读回的时间统一成带时区的 UTC，屏蔽列类型的差异。

    审计时间列是 ``TIMESTAMP WITH TIME ZONE``，asyncpg 读回 aware 值；但历史
    数据或由 ``create_all`` 建出的 naive 列会读回 naive 值。读取侧必须同时兼容：
    否则 aware 值与 naive 值相减会直接抛
    ``TypeError: can't subtract offset-naive and offset-aware datetimes``。
    """

    if value is None:
        return None
    if value.tzinfo is None:
        # 历史 naive 值按 UTC 解释（写入侧统一使用带时区的 UTC）。
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def wait_timeout_seconds(expires_at: datetime | None, *, default: float) -> float:
    """计算“距离过期还剩多少秒”，用于等待页面的超时上限。

    缺失过期时间时回退 ``default``；已经过期时按 0 处理，让
    ``asyncio.wait_for`` 立即超时并走既有的过期分支，而不是等待负数时长。
    """

    normalized = as_utc(expires_at)
    if normalized is None:
        return default
    return max(0.0, (normalized - datetime.now(UTC)).total_seconds())


def allowed_host_tool_names(
    *,
    token_names: Iterable[str],
    agent_names: Iterable[str],
    registered_names: Iterable[str],
) -> set[str]:
    return set(token_names) & set(agent_names) & set(registered_names)


def build_temporary_host_tool_policy(registration: dict):
    """Build a connection-scoped policy without persisting or consulting allowlists."""
    name = registration.get("name")
    description = registration.get("description")
    input_schema = registration.get("inputSchema") or registration.get("input_schema")
    side_effect = (
        registration.get("sideEffect") or registration.get("side_effect") or "none"
    )
    if not isinstance(name, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.-]{0,127}", name
    ):
        raise ValueError("temporary host tool name is invalid")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 1000
    ):
        raise ValueError("temporary host tool description is invalid")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        raise ValueError("temporary host tool schema must be an object")
    if len(json.dumps(input_schema, separators=(",", ":"))) > 64 * 1024:
        raise ValueError("temporary host tool schema is too large")
    if side_effect not in {"none", "navigation", "write", "financial", "external"}:
        raise ValueError("temporary host tool side effect is invalid")
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=None,
        schema_fingerprint=canonical_fingerprint(input_schema),
        side_effect=side_effect,
        confirmation_policy="auto",
    )


def transition_status(
    current: HostToolStatus | str, target: HostToolStatus | str
) -> str:
    if target not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid host tool status transition: {current} -> {target}")
    return target


def canonical_fingerprint(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_arguments(schema: dict, arguments: dict) -> None:
    try:
        validate(instance=arguments, schema=schema or {"type": "object"})
    except ValidationError as exc:
        raise ValueError("host tool arguments are invalid") from exc


def validate_registration(policy, registration: dict) -> None:
    if registration.get("name") != policy.name:
        raise ValueError("host tool is not allowed")
    if (
        canonical_fingerprint(
            registration.get("inputSchema") or registration.get("input_schema") or {}
        )
        != policy.schema_fingerprint
    ):
        raise ValueError("host tool schema does not match policy")


def redact_sensitive(value):
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    marker in key.lower()
                    for marker in (
                        "password",
                        "token",
                        "secret",
                        "api_key",
                        "authorization",
                        "cookie",
                    )
                )
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value
