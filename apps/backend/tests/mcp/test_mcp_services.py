import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.mcp.services import (
    expire_tool_confirmation,
    invoke_tool,
    resolve_tool_confirmation,
)
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException


@dataclass
class FakeTool:
    id: int
    server_id: int
    name: str
    input_schema: dict
    side_effect: str


@dataclass
class FakeConfirmation:
    id: int
    platform_id: int
    agent_id: int
    user_id: int | None
    platform_end_user_id: int | None
    tool: FakeTool
    arguments: dict
    audit_id: int
    status: str = "pending"
    expires_at: datetime | None = None


class FakeMcpRepository:
    def __init__(self, tool: FakeTool | None) -> None:
        self.tool = tool
        self.confirmations: list[FakeConfirmation] = []
        self.audits: dict[int, dict] = {}
        self.claim_allowed = True

    async def get_allowed_tool(self, platform_id, agent_id, server_id, tool_name):
        if (
            self.tool
            and self.tool.server_id == server_id
            and self.tool.name == tool_name
        ):
            return self.tool
        return None

    async def create_audit(self, **values):
        audit_id = len(self.audits) + 1
        self.audits[audit_id] = {"id": audit_id, **values}
        return self.audits[audit_id]

    async def create_confirmation(self, **values):
        confirmation = FakeConfirmation(id=len(self.confirmations) + 1, **values)
        self.confirmations.append(confirmation)
        return confirmation

    async def complete_audit(self, audit_id, *, status, result=None, error=None):
        self.audits[audit_id].update(status=status, result=result, error=error)

    async def get_confirmation(
        self,
        confirmation_id,
        platform_id,
        *,
        user_id=None,
        platform_end_user_id=None,
    ):
        return next(
            (
                item
                for item in self.confirmations
                if item.id == confirmation_id
                and item.platform_id == platform_id
                and item.user_id == user_id
                and item.platform_end_user_id == platform_end_user_id
            ),
            None,
        )

    async def claim_confirmation(self, confirmation, status):
        if not self.claim_allowed or confirmation.status != "pending":
            return False
        confirmation.status = status
        return True


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, dict]] = []

    async def __call__(self, server_id: int, tool_name: str, arguments: dict):
        self.calls.append((server_id, tool_name, arguments))
        return {"ok": True}


def test_unlisted_tool_is_rejected_without_execution() -> None:
    async def run() -> None:
        executor = FakeExecutor()
        with pytest.raises(NotFoundException, match="MCP tool not found"):
            await invoke_tool(
                FakeMcpRepository(None),
                executor,
                platform_id=1,
                agent_id=2,
                user_id=3,
                server_id=4,
                tool_name="delete_order",
                arguments={"id": "A-1"},
            )
        assert executor.calls == []

    asyncio.run(run())


def test_read_only_tool_executes_and_writes_completed_audit() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "get_order", {"type": "object"}, "none")
        )
        executor = FakeExecutor()

        outcome = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="get_order",
            arguments={"id": "A-1"},
        )

        assert outcome.status == "completed"
        assert outcome.result == {"ok": True}
        assert repo.audits[outcome.audit_id]["status"] == "completed"
        assert len(executor.calls) == 1

    asyncio.run(run())


def test_embed_principal_executes_and_is_written_to_audit() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "get_order", {"type": "object"}, "none")
        )

        outcome = await invoke_tool(
            repo,
            FakeExecutor(),
            platform_id=1,
            agent_id=2,
            platform_end_user_id=9,
            server_id=4,
            tool_name="get_order",
            arguments={},
        )

        assert repo.audits[outcome.audit_id]["user_id"] is None
        assert repo.audits[outcome.audit_id]["platform_end_user_id"] == 9

    asyncio.run(run())


def test_invocation_requires_exactly_one_principal() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "get_order", {"type": "object"}, "none")
        )
        with pytest.raises(BadRequestException, match="exactly one"):
            await invoke_tool(
                repo,
                FakeExecutor(),
                platform_id=1,
                agent_id=2,
                server_id=4,
                tool_name="get_order",
                arguments={},
            )
        with pytest.raises(BadRequestException, match="exactly one"):
            await invoke_tool(
                repo,
                FakeExecutor(),
                platform_id=1,
                agent_id=2,
                user_id=3,
                platform_end_user_id=9,
                server_id=4,
                tool_name="get_order",
                arguments={},
            )

    asyncio.run(run())


def test_embed_confirmation_can_expire_without_execution() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "write")
        )
        executor = FakeExecutor()
        pending = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            platform_end_user_id=9,
            server_id=4,
            tool_name="cancel_order",
            arguments={},
        )

        expired = await expire_tool_confirmation(
            repo,
            confirmation_id=pending.confirmation_id,
            platform_id=1,
            platform_end_user_id=9,
        )

        assert expired.status == "expired"
        assert repo.audits[pending.audit_id]["status"] == "expired"
        assert executor.calls == []

    asyncio.run(run())


def test_audit_redacts_sensitive_arguments_but_executor_receives_originals() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(FakeTool(1, 4, "lookup", {"type": "object"}, "none"))
        executor = FakeExecutor()
        arguments = {
            "account": "alice",
            "password": "plain-secret",
            "nested": {"api_key": "sk-secret"},
        }

        outcome = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="lookup",
            arguments=arguments,
        )

        audited = repo.audits[outcome.audit_id]["arguments"]
        assert audited["account"] == "alice"
        assert audited["password"] == "[REDACTED]"
        assert audited["nested"]["api_key"] == "[REDACTED]"
        assert executor.calls[0][2] == arguments

    asyncio.run(run())


def test_side_effect_tool_waits_for_confirmation() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "write")
        )
        executor = FakeExecutor()

        outcome = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="cancel_order",
            arguments={"id": "A-1"},
        )

        assert outcome.status == "confirmation_required"
        assert outcome.confirmation_id == 1
        assert executor.calls == []
        assert repo.audits[outcome.audit_id]["status"] == "awaiting_confirmation"

    asyncio.run(run())


def test_approved_confirmation_executes_once() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "write")
        )
        executor = FakeExecutor()
        pending = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="cancel_order",
            arguments={"id": "A-1"},
        )

        completed = await resolve_tool_confirmation(
            repo,
            executor,
            confirmation_id=pending.confirmation_id,
            platform_id=1,
            user_id=3,
            approved=True,
        )

        assert completed.status == "completed"
        assert len(executor.calls) == 1
        with pytest.raises(ConflictException, match="already resolved"):
            await resolve_tool_confirmation(
                repo,
                executor,
                confirmation_id=pending.confirmation_id,
                platform_id=1,
                user_id=3,
                approved=True,
            )

    asyncio.run(run())


def test_rejected_confirmation_does_not_execute() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "external")
        )
        executor = FakeExecutor()
        pending = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="cancel_order",
            arguments={},
        )

        rejected = await resolve_tool_confirmation(
            repo,
            executor,
            confirmation_id=pending.confirmation_id,
            platform_id=1,
            user_id=3,
            approved=False,
        )

        assert rejected.status == "rejected"
        assert executor.calls == []
        assert repo.audits[pending.audit_id]["status"] == "rejected"

    asyncio.run(run())


def test_confirmation_that_loses_atomic_claim_does_not_execute() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "write")
        )
        executor = FakeExecutor()
        pending = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="cancel_order",
            arguments={},
        )
        repo.claim_allowed = False

        with pytest.raises(ConflictException, match="already resolved"):
            await resolve_tool_confirmation(
                repo,
                executor,
                confirmation_id=pending.confirmation_id,
                platform_id=1,
                user_id=3,
                approved=True,
            )

        assert executor.calls == []

    asyncio.run(run())


def test_expired_confirmation_does_not_execute() -> None:
    async def run() -> None:
        repo = FakeMcpRepository(
            FakeTool(1, 4, "cancel_order", {"type": "object"}, "write")
        )
        executor = FakeExecutor()
        pending = await invoke_tool(
            repo,
            executor,
            platform_id=1,
            agent_id=2,
            user_id=3,
            server_id=4,
            tool_name="cancel_order",
            arguments={},
        )
        repo.confirmations[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)

        expired = await resolve_tool_confirmation(
            repo,
            executor,
            confirmation_id=pending.confirmation_id,
            platform_id=1,
            user_id=3,
            approved=True,
        )

        assert expired.status == "expired"
        assert executor.calls == []
        assert repo.audits[pending.audit_id]["status"] == "expired"

    asyncio.run(run())
