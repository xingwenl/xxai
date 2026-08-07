from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.builtin_tool.models import AgentBuiltinTool
from app.modules.builtin_tool.registry import get_builtin_tool


class BuiltinToolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_binding(
        self, platform_id: int, agent_id: int, tool_name: str, *, is_enabled: bool
    ) -> AgentBuiltinTool | None:
        agent = await self.session.scalar(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        if agent is None or get_builtin_tool(tool_name) is None:
            return None
        binding = await self.session.scalar(
            select(AgentBuiltinTool).where(
                AgentBuiltinTool.agent_id == agent_id,
                AgentBuiltinTool.tool_name == tool_name,
            )
        )
        if binding is None:
            binding = AgentBuiltinTool(
                platform_id=platform_id,
                agent_id=agent_id,
                tool_name=tool_name,
                is_enabled=is_enabled,
            )
            self.session.add(binding)
        else:
            binding.is_enabled = is_enabled
        await self.session.commit()
        await self.session.refresh(binding)
        return binding

    async def list_bindings(
        self, platform_id: int, agent_id: int
    ) -> list[AgentBuiltinTool]:
        result = await self.session.execute(
            select(AgentBuiltinTool)
            .join(Agent, Agent.id == AgentBuiltinTool.agent_id)
            .where(
                AgentBuiltinTool.platform_id == platform_id,
                AgentBuiltinTool.agent_id == agent_id,
                Agent.platform_id == platform_id,
            )
            .order_by(AgentBuiltinTool.tool_name)
        )
        return list(result.scalars().all())

    async def list_enabled_tools_for_agent(
        self, agent_id: int, platform_id: int
    ) -> list:
        bindings = await self.list_bindings(platform_id, agent_id)
        return [
            tool
            for binding in bindings
            if binding.is_enabled
            and (tool := get_builtin_tool(binding.tool_name)) is not None
        ]

    async def is_enabled(self, platform_id: int, agent_id: int, tool_name: str) -> bool:
        return bool(
            await self.session.scalar(
                select(AgentBuiltinTool.id).where(
                    AgentBuiltinTool.platform_id == platform_id,
                    AgentBuiltinTool.agent_id == agent_id,
                    AgentBuiltinTool.tool_name == tool_name,
                    AgentBuiltinTool.is_enabled.is_(True),
                )
            )
        )
