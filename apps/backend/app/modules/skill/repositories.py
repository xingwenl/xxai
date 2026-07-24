from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.skill.models import AgentSkill, Skill
from app.modules.skill.schemas import AgentSkillBind, SkillCreate


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_slug(self, platform_id: int, slug: str):
        result = await self.session.execute(
            select(Skill).where(Skill.platform_id == platform_id, Skill.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create(self, platform_id: int, payload: SkillCreate):
        skill = Skill(platform_id=platform_id, **payload.model_dump())
        self.session.add(skill)
        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def bind(self, platform_id: int, agent_id: int, payload: AgentSkillBind):
        agent = await self.session.scalar(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        skill = await self.session.scalar(
            select(Skill).where(
                Skill.id == payload.skill_id, Skill.platform_id == platform_id
            )
        )
        if agent is None or skill is None:
            return None
        binding = await self.session.scalar(
            select(AgentSkill).where(
                AgentSkill.agent_id == agent_id, AgentSkill.skill_id == payload.skill_id
            )
        )
        if binding is None:
            binding = AgentSkill(agent_id=agent_id, **payload.model_dump())
            self.session.add(binding)
        else:
            binding.sort_order = payload.sort_order
            binding.is_enabled = True
        await self.session.commit()
        await self.session.refresh(binding)
        return binding
