from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.skill.models import AgentSkill, Skill
from app.modules.skill.schemas import AgentSkillBind, SkillCreate, SkillUpdate
from app.shared.pagination import PaginationParams, build_page_data


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_slug(self, platform_id: int, slug: str):
        result = await self.session.execute(
            select(Skill).where(Skill.platform_id == platform_id, Skill.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_skills(self, platform_id: int, params: PaginationParams):
        statement = (
            select(Skill)
            .where(Skill.platform_id == platform_id)
            .order_by(Skill.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        items = list((await self.session.execute(statement)).scalars().all())
        total = await self.session.scalar(
            select(func.count()).select_from(Skill).where(Skill.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

    async def get_skill(self, skill_id: int, platform_id: int):
        return await self.session.scalar(
            select(Skill).where(Skill.id == skill_id, Skill.platform_id == platform_id)
        )

    async def create(self, platform_id: int, payload: SkillCreate):
        skill = Skill(platform_id=platform_id, **payload.model_dump())
        self.session.add(skill)
        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def list_enabled_for_agent(self, agent_id: int, platform_id: int):
        result = await self.session.execute(
            select(AgentSkill)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .where(
                AgentSkill.agent_id == agent_id,
                AgentSkill.is_enabled.is_(True),
                Skill.platform_id == platform_id,
                Skill.is_active.is_(True),
            )
            .order_by(AgentSkill.sort_order, AgentSkill.id)
        )
        return list(result.scalars().all())

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

    async def list_bindings(self, platform_id: int, agent_id: int):
        result = await self.session.execute(
            select(AgentSkill)
            .join(Agent, Agent.id == AgentSkill.agent_id)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .where(
                AgentSkill.agent_id == agent_id,
                Agent.platform_id == platform_id,
                Skill.platform_id == platform_id,
            )
            .order_by(AgentSkill.sort_order, AgentSkill.id)
        )
        return list(result.scalars().all())

    async def update_skill(self, skill: Skill, payload: SkillUpdate):
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(skill, key, value)
        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def delete_skill(self, skill: Skill) -> None:
        await self.session.delete(skill)
        await self.session.commit()

    async def unbind(self, platform_id: int, agent_id: int, skill_id: int):
        binding = await self.session.scalar(
            select(AgentSkill)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .where(
                AgentSkill.agent_id == agent_id,
                AgentSkill.skill_id == skill_id,
                Skill.platform_id == platform_id,
            )
        )
        if binding is None:
            return False
        await self.session.delete(binding)
        await self.session.commit()
        return True
