from __future__ import annotations

import hashlib
import json
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


def allowed_host_tool_names(
    *,
    token_names: Iterable[str],
    agent_names: Iterable[str],
    registered_names: Iterable[str],
) -> set[str]:
    return set(token_names) & set(agent_names) & set(registered_names)


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
