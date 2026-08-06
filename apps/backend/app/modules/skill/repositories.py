from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.agent.models import Agent
from app.modules.skill.models import (
    AgentSkill,
    Skill,
    SkillPackage,
    SkillPackageFile,
    SkillScriptExecution,
)
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

    async def list_packages(self, platform_id: int, params: PaginationParams):
        statement = (
            select(SkillPackage)
            .where(SkillPackage.platform_id == platform_id)
            .order_by(SkillPackage.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        items = list((await self.session.execute(statement)).scalars().all())
        total = await self.session.scalar(
            select(func.count())
            .select_from(SkillPackage)
            .where(SkillPackage.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

    async def get_package(self, package_id: int, platform_id: int):
        return await self.session.scalar(
            select(SkillPackage)
            .options(
                selectinload(SkillPackage.files),
                selectinload(SkillPackage.skills),
            )
            .where(SkillPackage.id == package_id, SkillPackage.platform_id == platform_id)
        )

    async def get_package_by_slug(self, platform_id: int, slug: str):
        return await self.session.scalar(
            select(SkillPackage).where(
                SkillPackage.platform_id == platform_id, SkillPackage.slug == slug
            )
        )

    async def create_package_with_assets(
        self,
        platform_id: int,
        *,
        package_values: dict,
        file_values: list[dict],
        skill_values: list[dict],
    ):
        package = SkillPackage(platform_id=platform_id, **package_values)
        self.session.add(package)
        await self.session.flush()
        for values in file_values:
            self.session.add(SkillPackageFile(package_id=package.id, **values))
        for values in skill_values:
            self.session.add(Skill(platform_id=platform_id, package_id=package.id, **values))
        await self.session.commit()
        await self.session.refresh(package, attribute_names=["files", "skills"])
        return package

    async def update_package(self, package: SkillPackage, values: dict):
        for key, value in values.items():
            setattr(package, key, value)
        await self.session.commit()
        # 权限更新接口只返回包的标量字段；不要在提交后刷新集合关系，
        # 避免异步 ORM 在不同 SQLAlchemy 版本下触发额外的懒加载。
        await self.session.refresh(package)
        return package

    async def list_enabled_for_agent(self, agent_id: int, platform_id: int):
        result = await self.session.execute(
            select(AgentSkill)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .outerjoin(SkillPackage, SkillPackage.id == Skill.package_id)
            .options(
                selectinload(AgentSkill.skill)
                .selectinload(Skill.package)
                .selectinload(SkillPackage.files),
            )
            .where(
                AgentSkill.agent_id == agent_id,
                AgentSkill.is_enabled.is_(True),
                Skill.platform_id == platform_id,
                Skill.is_active.is_(True),
                or_(Skill.package_id.is_(None), SkillPackage.is_active.is_(True)),
            )
            .order_by(AgentSkill.sort_order, AgentSkill.id)
        )
        return list(result.scalars().all())

    async def get_enabled_skill_for_agent(self, agent_id: int, platform_id: int, slug: str):
        result = await self.session.execute(
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .outerjoin(SkillPackage, SkillPackage.id == Skill.package_id)
            .options(selectinload(Skill.package))
            .where(
                AgentSkill.agent_id == agent_id,
                AgentSkill.is_enabled.is_(True),
                Skill.platform_id == platform_id,
                Skill.slug == slug,
                Skill.is_active.is_(True),
                or_(Skill.package_id.is_(None), SkillPackage.is_active.is_(True)),
            )
        )
        return result.scalar_one_or_none()

    async def get_allowed_script(
        self,
        *,
        platform_id: int,
        agent_id: int,
        package_id: int,
        skill_id: int,
        script_path: str,
    ):
        statement = (
            select(SkillPackage, SkillPackageFile)
            .join(Skill, Skill.package_id == SkillPackage.id)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .join(SkillPackageFile, SkillPackageFile.package_id == SkillPackage.id)
            .where(
                SkillPackage.id == package_id,
                SkillPackage.platform_id == platform_id,
                SkillPackage.is_active.is_(True),
                SkillPackage.allow_script_execution.is_(True),
                Skill.id == skill_id,
                Skill.is_active.is_(True),
                AgentSkill.agent_id == agent_id,
                AgentSkill.is_enabled.is_(True),
                SkillPackageFile.relative_path == script_path,
                SkillPackageFile.role == "script",
            )
        )
        return (await self.session.execute(statement)).one_or_none()

    async def create_script_execution(self, **values):
        execution = SkillScriptExecution(
            status="running", started_at=datetime.now(UTC), **values
        )
        self.session.add(execution)
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def complete_script_execution(self, execution, result):
        execution.status = result.status
        execution.exit_code = result.exit_code
        execution.stdout = result.stdout
        execution.stderr = result.stderr
        execution.error = result.error
        execution.duration_ms = result.duration_ms
        execution.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def fail_script_execution(self, execution, error: str):
        execution.status = "failed"
        execution.error = error[:2000]
        execution.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def list_script_executions(
        self, platform_id: int, params: PaginationParams
    ):
        statement = (
            select(SkillScriptExecution)
            .where(SkillScriptExecution.platform_id == platform_id)
            .order_by(SkillScriptExecution.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        items = list((await self.session.execute(statement)).scalars().all())
        total = await self.session.scalar(
            select(func.count())
            .select_from(SkillScriptExecution)
            .where(SkillScriptExecution.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

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
