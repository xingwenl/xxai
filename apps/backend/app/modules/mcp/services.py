import json
from datetime import UTC, datetime

from jsonschema import ValidationError, validate

from app.modules.agent.services import encrypt_secret
from app.modules.mcp.runtime import validate_mcp_url
from app.modules.mcp.schemas import ToolInvocationOutcome
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)


def _record_id(record) -> int:
    return record["id"] if isinstance(record, dict) else record.id


def _record_value(record, name: str):
    return record.get(name) if isinstance(record, dict) else getattr(record, name)


def _principal_values(
    *, user_id: int | None, platform_end_user_id: int | None
) -> dict[str, int | None]:
    if (user_id is None) == (platform_end_user_id is None):
        raise BadRequestException("exactly one MCP invocation principal is required")
    return {
        "user_id": user_id,
        "platform_end_user_id": platform_end_user_id,
    }


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
                    )
                )
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


async def create_mcp_server(repo, platform_id: int, payload):
    if await repo.get_server_by_slug(platform_id, payload.slug) is not None:
        raise ConflictException("MCP server slug already exists")
    validate_mcp_url(payload.endpoint_url)
    stored = payload.model_copy(
        update={
            "auth_headers": (
                encrypt_secret(json.dumps(payload.auth_headers, separators=(",", ":")))
                if payload.auth_headers
                else None
            )
        }
    )
    return await repo.create_server(platform_id, stored)


async def sync_mcp_tools(repo, client, server):
    discovered = await client.list_tools(server)
    return await repo.sync_tools(server.id, discovered)


async def update_mcp_server(repo, platform_id: int, server_id: int, payload):
    server = await repo.get_server(server_id, platform_id)
    if server is None:
        raise NotFoundException("MCP server not found")
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "endpoint_url" in values:
        validate_mcp_url(values["endpoint_url"])
    if "auth_headers" in values:
        values["auth_headers_encrypted"] = (
            encrypt_secret(json.dumps(values.pop("auth_headers"), separators=(",", ":")))
            if values["auth_headers"]
            else None
        )
    return await repo.update_server(server, values)


async def delete_mcp_server(repo, platform_id: int, server_id: int) -> None:
    server = await repo.get_server(server_id, platform_id)
    if server is None:
        raise NotFoundException("MCP server not found")
    if await repo.has_audits(server_id):
        raise ConflictException(
            "MCP server has audit records and can only be disabled"
        )
    await repo.delete_server(server)


async def unbind_mcp_server(repo, platform_id: int, agent_id: int, server_id: int):
    if not await repo.unbind_server(platform_id, agent_id, server_id):
        raise NotFoundException("agent MCP server binding not found")


def policy_after_schema_sync(
    *,
    previous_schema: dict,
    discovered_schema: dict,
    is_allowed: bool,
    side_effect: str,
) -> tuple[bool, str]:
    if previous_schema != discovered_schema:
        return False, "external"
    return is_allowed, side_effect


def _validate_arguments(schema: dict, arguments: dict) -> None:
    try:
        validate(instance=arguments, schema=schema or {"type": "object"})
    except ValidationError as exc:
        raise BadRequestException("MCP tool arguments are invalid") from exc


async def _execute_and_audit(repo, executor, audit_id, tool, arguments):
    try:
        result = await executor(tool.server_id, tool.name, arguments)
    except Exception as exc:
        await repo.complete_audit(audit_id, status="failed", error=str(exc))
        raise
    await repo.complete_audit(
        audit_id, status="completed", result=redact_sensitive(result)
    )
    return ToolInvocationOutcome(status="completed", audit_id=audit_id, result=result)


async def invoke_tool(
    repo,
    executor,
    *,
    platform_id: int,
    agent_id: int,
    server_id: int,
    tool_name: str,
    arguments: dict,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
) -> ToolInvocationOutcome:
    principal = _principal_values(
        user_id=user_id, platform_end_user_id=platform_end_user_id
    )
    tool = await repo.get_allowed_tool(platform_id, agent_id, server_id, tool_name)
    if tool is None:
        raise NotFoundException("MCP tool not found")
    _validate_arguments(tool.input_schema, arguments)
    audit = await repo.create_audit(
        platform_id=platform_id,
        agent_id=agent_id,
        **principal,
        tool=tool,
        arguments=redact_sensitive(arguments),
        status="awaiting_confirmation" if tool.side_effect != "none" else "running",
    )
    audit_id = _record_id(audit)
    if tool.side_effect == "none":
        return await _execute_and_audit(repo, executor, audit_id, tool, arguments)

    confirmation = await repo.create_confirmation(
        platform_id=platform_id,
        agent_id=agent_id,
        **principal,
        tool=tool,
        arguments=arguments,
        audit_id=audit_id,
    )
    return ToolInvocationOutcome(
        status="confirmation_required",
        audit_id=audit_id,
        confirmation_id=_record_id(confirmation),
        expires_at=_record_value(confirmation, "expires_at"),
    )


async def resolve_tool_confirmation(
    repo,
    executor,
    *,
    confirmation_id: int,
    platform_id: int,
    approved: bool,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
) -> ToolInvocationOutcome:
    principal = _principal_values(
        user_id=user_id, platform_end_user_id=platform_end_user_id
    )
    confirmation = await repo.get_confirmation(
        confirmation_id, platform_id, **principal
    )
    if confirmation is None:
        raise NotFoundException("tool confirmation not found")
    if confirmation.status != "pending":
        raise ConflictException("tool confirmation already resolved")
    if confirmation.expires_at and confirmation.expires_at <= datetime.now(UTC):
        if await repo.claim_confirmation(confirmation, "expired"):
            await repo.complete_audit(confirmation.audit_id, status="expired")
        return ToolInvocationOutcome(
            status="expired", audit_id=confirmation.audit_id
        )
    claimed = await repo.claim_confirmation(
        confirmation, "approved" if approved else "rejected"
    )
    if not claimed:
        raise ConflictException("tool confirmation already resolved")
    if not approved:
        await repo.complete_audit(confirmation.audit_id, status="rejected")
        return ToolInvocationOutcome(status="rejected", audit_id=confirmation.audit_id)

    return await _execute_and_audit(
        repo,
        executor,
        confirmation.audit_id,
        confirmation.tool,
        confirmation.arguments,
    )


async def expire_tool_confirmation(
    repo,
    *,
    confirmation_id: int,
    platform_id: int,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
) -> ToolInvocationOutcome:
    principal = _principal_values(
        user_id=user_id, platform_end_user_id=platform_end_user_id
    )
    confirmation = await repo.get_confirmation(
        confirmation_id, platform_id, **principal
    )
    if confirmation is None:
        raise NotFoundException("tool confirmation not found")
    if confirmation.status != "pending":
        raise ConflictException("tool confirmation already resolved")
    if not await repo.claim_confirmation(confirmation, "expired"):
        raise ConflictException("tool confirmation already resolved")
    await repo.complete_audit(confirmation.audit_id, status="expired")
    return ToolInvocationOutcome(status="expired", audit_id=confirmation.audit_id)
