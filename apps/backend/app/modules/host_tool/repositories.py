from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.host_tool.models import (
    AgentHostTool,
    EmbedClientHostTool,
    HostToolCallAudit,
    HostToolPolicy,
)
from app.modules.host_tool.services import canonical_fingerprint, transition_status


class HostToolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_policies(self, platform_id: int):
        result = await self.session.execute(
            select(HostToolPolicy)
            .where(HostToolPolicy.platform_id == platform_id)
            .order_by(HostToolPolicy.id)
        )
        return list(result.scalars().all())

    async def get_policy(self, platform_id: int, tool_id: int):
        return await self.session.scalar(
            select(HostToolPolicy).where(
                HostToolPolicy.id == tool_id,
                HostToolPolicy.platform_id == platform_id,
            )
        )

    async def get_policy_by_name(self, platform_id: int, name: str):
        return await self.session.scalar(
            select(HostToolPolicy).where(
                HostToolPolicy.platform_id == platform_id,
                HostToolPolicy.name == name,
            )
        )

    async def create_policy(self, platform_id: int, payload):
        policy = HostToolPolicy(
            platform_id=platform_id,
            schema_fingerprint=canonical_fingerprint(payload.input_schema),
            **payload.model_dump(),
        )
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def update_policy(self, policy, values: dict):
        schema_changed = "input_schema" in values
        for key, value in values.items():
            setattr(policy, key, value)
        if schema_changed:
            policy.schema_fingerprint = canonical_fingerprint(policy.input_schema)
            policy.is_enabled = False
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def list_agent_tool_names(self, platform_id: int, agent_id: int) -> set[str]:
        result = await self.session.execute(
            select(HostToolPolicy.name)
            .join(AgentHostTool, AgentHostTool.tool_id == HostToolPolicy.id)
            .where(
                HostToolPolicy.platform_id == platform_id,
                HostToolPolicy.is_enabled.is_(True),
                AgentHostTool.agent_id == agent_id,
                AgentHostTool.is_enabled.is_(True),
            )
        )
        return set(result.scalars().all())

    async def list_client_tool_names(self, client_id: int) -> set[str]:
        result = await self.session.execute(
            select(HostToolPolicy.name)
            .join(EmbedClientHostTool, EmbedClientHostTool.tool_id == HostToolPolicy.id)
            .where(EmbedClientHostTool.client_id == client_id)
        )
        return set(result.scalars().all())

    async def list_authorized_policies(
        self, platform_id: int, agent_id: int, names: set[str]
    ):
        if not names:
            return []
        result = await self.session.execute(
            select(HostToolPolicy)
            .join(AgentHostTool, AgentHostTool.tool_id == HostToolPolicy.id)
            .where(
                HostToolPolicy.platform_id == platform_id,
                HostToolPolicy.name.in_(names),
                HostToolPolicy.is_enabled.is_(True),
                AgentHostTool.agent_id == agent_id,
                AgentHostTool.is_enabled.is_(True),
            )
        )
        return list(result.scalars().all())

    async def create_audit(self, **values):
        audit = HostToolCallAudit(**values)
        self.session.add(audit)
        await self.session.commit()
        await self.session.refresh(audit)
        return audit

    async def get_call(
        self, call_id: str, *, platform_id: int, agent_id: int, end_user_id: int
    ):
        return await self.session.scalar(
            select(HostToolCallAudit).where(
                HostToolCallAudit.call_id == call_id,
                HostToolCallAudit.platform_id == platform_id,
                HostToolCallAudit.agent_id == agent_id,
                HostToolCallAudit.platform_end_user_id == end_user_id,
            )
        )

    async def transition_call(self, audit, target: str, *, result=None, error=None):
        transition_status(audit.status, target)
        values = {"status": target}
        if target == "running":
            values["started_at"] = datetime.now(UTC)
        if target in {"succeeded", "failed", "rejected", "expired"}:
            values["completed_at"] = datetime.now(UTC)
        if result is not None:
            values["result"] = result
        if error is not None:
            values["error"] = error[:500]
        statement = (
            update(HostToolCallAudit)
            .where(
                HostToolCallAudit.id == audit.id,
                HostToolCallAudit.status == audit.status,
            )
            .values(**values)
        )
        updated = await self.session.execute(statement)
        await self.session.commit()
        if updated.rowcount != 1:
            raise ValueError("host tool call already resolved")
        await self.session.refresh(audit)
        return audit

    async def list_audits(self, platform_id: int, limit: int = 100):
        result = await self.session.execute(
            select(HostToolCallAudit)
            .where(HostToolCallAudit.platform_id == platform_id)
            .order_by(HostToolCallAudit.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def bind_agent(self, agent_id: int, tool_id: int):
        binding = await self.session.scalar(
            select(AgentHostTool).where(
                AgentHostTool.agent_id == agent_id,
                AgentHostTool.tool_id == tool_id,
            )
        )
        if binding is None:
            binding = AgentHostTool(agent_id=agent_id, tool_id=tool_id)
            self.session.add(binding)
        else:
            binding.is_enabled = True
        await self.session.commit()

    async def unbind_agent(self, agent_id: int, tool_id: int):
        binding = await self.session.scalar(
            select(AgentHostTool).where(
                AgentHostTool.agent_id == agent_id,
                AgentHostTool.tool_id == tool_id,
            )
        )
        if binding is not None:
            await self.session.delete(binding)
            await self.session.commit()

    async def bind_client(self, client_id: int, tool_id: int):
        binding = await self.session.scalar(
            select(EmbedClientHostTool).where(
                EmbedClientHostTool.client_id == client_id,
                EmbedClientHostTool.tool_id == tool_id,
            )
        )
        if binding is None:
            self.session.add(EmbedClientHostTool(client_id=client_id, tool_id=tool_id))
            await self.session.commit()

    async def unbind_client(self, client_id: int, tool_id: int):
        binding = await self.session.scalar(
            select(EmbedClientHostTool).where(
                EmbedClientHostTool.client_id == client_id,
                EmbedClientHostTool.tool_id == tool_id,
            )
        )
        if binding is not None:
            await self.session.delete(binding)
            await self.session.commit()
