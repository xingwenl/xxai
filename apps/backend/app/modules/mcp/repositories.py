from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.agent.services import encrypt_secret
from app.modules.mcp.models import (
    AgentMcpServer,
    McpServer,
    McpTool,
    McpToolCallAudit,
    McpToolConfirmation,
)
from app.modules.mcp.services import policy_after_schema_sync


class McpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_server_by_slug(self, platform_id: int, slug: str):
        return await self.session.scalar(
            select(McpServer).where(
                McpServer.platform_id == platform_id, McpServer.slug == slug
            )
        )

    async def get_server(self, server_id: int, platform_id: int | None = None):
        statement = select(McpServer).where(McpServer.id == server_id)
        if platform_id is not None:
            statement = statement.where(McpServer.platform_id == platform_id)
        return await self.session.scalar(statement)

    async def create_server(self, platform_id: int, payload):
        values = payload.model_dump(exclude={"auth_headers"})
        values["auth_headers_encrypted"] = payload.auth_headers
        server = McpServer(platform_id=platform_id, **values)
        self.session.add(server)
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def sync_tools(self, server_id: int, tools):
        existing = {
            item.name: item
            for item in (
                await self.session.execute(
                    select(McpTool).where(McpTool.server_id == server_id)
                )
            ).scalars()
        }
        discovered_names = set()
        for discovered in tools:
            discovered_names.add(discovered.name)
            tool = existing.get(discovered.name)
            if tool is None:
                tool = McpTool(server_id=server_id, name=discovered.name)
                self.session.add(tool)
                existing[discovered.name] = tool
            else:
                tool.is_allowed, tool.side_effect = policy_after_schema_sync(
                    previous_schema=tool.input_schema,
                    discovered_schema=discovered.input_schema,
                    is_allowed=tool.is_allowed,
                    side_effect=tool.side_effect,
                )
            tool.description = discovered.description
            tool.input_schema = discovered.input_schema
        for name, tool in existing.items():
            if name not in discovered_names:
                tool.is_allowed = False
                tool.side_effect = "external"
        await self.session.commit()
        return list(existing.values())

    async def update_tool_policy(self, tool_id: int, platform_id: int, payload):
        tool = await self.session.scalar(
            select(McpTool)
            .join(McpServer, McpServer.id == McpTool.server_id)
            .where(McpTool.id == tool_id, McpServer.platform_id == platform_id)
        )
        if tool is None:
            return None
        tool.is_allowed = payload.is_allowed
        tool.side_effect = payload.side_effect
        await self.session.commit()
        await self.session.refresh(tool)
        return tool

    async def bind_server(self, platform_id: int, agent_id: int, server_id: int):
        agent = await self.session.scalar(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        server = await self.get_server(server_id, platform_id)
        if agent is None or server is None:
            return None
        binding = await self.session.scalar(
            select(AgentMcpServer).where(
                AgentMcpServer.agent_id == agent_id,
                AgentMcpServer.server_id == server_id,
            )
        )
        if binding is None:
            binding = AgentMcpServer(agent_id=agent_id, server_id=server_id)
            self.session.add(binding)
        else:
            binding.is_enabled = True
        await self.session.commit()
        return binding

    async def get_allowed_tool(self, platform_id, agent_id, server_id, tool_name):
        return await self.session.scalar(
            select(McpTool)
            .join(McpServer, McpServer.id == McpTool.server_id)
            .join(AgentMcpServer, AgentMcpServer.server_id == McpServer.id)
            .where(
                McpServer.id == server_id,
                McpServer.platform_id == platform_id,
                McpServer.is_active.is_(True),
                AgentMcpServer.agent_id == agent_id,
                AgentMcpServer.is_enabled.is_(True),
                McpTool.name == tool_name,
                McpTool.is_allowed.is_(True),
            )
        )

    async def create_audit(self, *, tool, **values):
        audit = McpToolCallAudit(
            server_id=tool.server_id,
            tool_id=tool.id,
            tool_name=tool.name,
            started_at=datetime.now(UTC),
            **values,
        )
        self.session.add(audit)
        await self.session.commit()
        await self.session.refresh(audit)
        return audit

    async def create_confirmation(self, *, tool, arguments, **values):
        confirmation = McpToolConfirmation(
            tool_id=tool.id,
            arguments_encrypted=encrypt_secret(
                json.dumps(arguments, separators=(",", ":"))
            ),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            **values,
        )
        self.session.add(confirmation)
        await self.session.commit()
        await self.session.refresh(confirmation)
        return confirmation

    async def complete_audit(self, audit_id, *, status, result=None, error=None):
        audit = await self.session.get(McpToolCallAudit, audit_id)
        if audit is None:
            return
        audit.status = status
        audit.result = result
        audit.error = error[:2000] if error else None
        audit.completed_at = datetime.now(UTC)
        await self.session.commit()

    async def get_confirmation(self, confirmation_id, platform_id, user_id):
        return await self.session.scalar(
            select(McpToolConfirmation).where(
                McpToolConfirmation.id == confirmation_id,
                McpToolConfirmation.platform_id == platform_id,
                McpToolConfirmation.user_id == user_id,
            )
        )

    async def claim_confirmation(self, confirmation, status) -> bool:
        result = await self.session.execute(
            update(McpToolConfirmation)
            .where(
                McpToolConfirmation.id == confirmation.id,
                McpToolConfirmation.status == "pending",
            )
            .values(status=status, resolved_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def list_audits(self, platform_id: int, limit: int = 100):
        result = await self.session.execute(
            select(McpToolCallAudit)
            .where(McpToolCallAudit.platform_id == platform_id)
            .order_by(McpToolCallAudit.id.desc())
            .limit(limit)
        )
        return list(result.scalars())
