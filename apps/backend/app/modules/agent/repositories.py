from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent, AgentVersion
from app.modules.platform.models import PlatformAdmin
from app.modules.agent.schemas import AgentCreate, AgentUpdate, AgentVersionCreate
from app.shared.pagination import PaginationParams, build_page_data
from app.shared.base_repository import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Agent)

    async def get_by_slug(self, platform_id: int, slug: str) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.platform_id == platform_id, Agent.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_agent(self, agent_id: int, platform_id: int) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        return result.scalar_one_or_none()

    async def list_agents(self, platform_id: int, params: PaginationParams):
        statement = (
            select(Agent)
            .where(Agent.platform_id == platform_id)
            .order_by(Agent.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(statement)
        items = list(result.scalars().all())
        total = await self.session.scalar(
            select(func.count()).select_from(Agent).where(Agent.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

    async def list_versions(self, agent_id: int):
        result = await self.session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version.desc())
        )
        return list(result.scalars().all())

    async def update_agent(self, agent: Agent, payload: AgentUpdate) -> Agent:
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(agent, key, value)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def delete_agent(self, agent: Agent) -> None:
        await self.session.delete(agent)
        await self.session.commit()

    async def get_published_agent(
        self, agent_id: int, platform_id: int
    ) -> Agent | None:
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.id == agent_id,
                Agent.platform_id == platform_id,
                Agent.default_version_id.is_not(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.default_version is None:
            return None
        return agent if agent.default_version.published_at is not None else None

    async def get_published_agent_for_user(self, agent_id: int, user_id: int):
        result = await self.session.execute(
            select(Agent)
            .join(PlatformAdmin, PlatformAdmin.platform_id == Agent.platform_id)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.id == agent_id,
                PlatformAdmin.user_id == user_id,
                Agent.default_version_id.is_not(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.default_version is None:
            return None
        return agent if agent.default_version.published_at is not None else None

    async def create_agent(self, payload: AgentCreate, platform_id: int) -> Agent:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.platform_id == platform_id)
        )
        agent = Agent(
            platform_id=platform_id,
            is_default=(count or 0) == 0,
            **payload.model_dump(),
        )
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def create_version(
        self, agent_id: int, payload: AgentVersionCreate
    ) -> AgentVersion:
        latest = await self.session.scalar(
            select(func.max(AgentVersion.version)).where(
                AgentVersion.agent_id == agent_id
            )
        )
        values = payload.model_dump(exclude={"api_key"})
        values["api_key_encrypted"] = payload.api_key
        version = AgentVersion(
            agent_id=agent_id,
            version=(latest or 0) + 1,
            created_at=datetime.now(UTC),
            **values,
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def get_version(self, agent_id: int, version_id: int) -> AgentVersion | None:
        result = await self.session.execute(
            select(AgentVersion).where(
                AgentVersion.id == version_id, AgentVersion.agent_id == agent_id
            )
        )
        return result.scalar_one_or_none()

    async def publish_version(self, agent: Agent, version_id: int) -> AgentVersion:
        version = await self.get_version(agent.id, version_id)
        if version is None:
            raise LookupError("agent version not found")
        version.published_at = datetime.now(UTC)
        agent.default_version_id = version.id
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def rollback(self, agent: Agent, version_id: int) -> AgentVersion:
        return await self.publish_version(agent, version_id)
