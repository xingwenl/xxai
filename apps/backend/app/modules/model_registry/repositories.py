from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.model_registry.models import AgentModelBinding, PlatformModel
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PaginationParams, build_page_data


class ModelRegistryRepository(BaseRepository[PlatformModel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PlatformModel)

    async def get_for_platform(
        self, model_id: int, platform_id: int
    ) -> PlatformModel | None:
        result = await self.session.execute(
            select(PlatformModel).where(
                PlatformModel.id == model_id,
                PlatformModel.platform_id == platform_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_type_and_name(
        self, platform_id: int, model_type: str, model_name: str
    ) -> PlatformModel | None:
        result = await self.session.execute(
            select(PlatformModel).where(
                PlatformModel.platform_id == platform_id,
                PlatformModel.model_type == model_type,
                PlatformModel.model_name == model_name,
            )
        )
        return result.scalar_one_or_none()

    async def list_models(
        self, platform_id: int, params: PaginationParams, model_type: str | None
    ):
        filters = [PlatformModel.platform_id == platform_id]
        if model_type:
            filters.append(PlatformModel.model_type == model_type)
        statement = (
            select(PlatformModel)
            .where(*filters)
            .order_by(PlatformModel.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(statement)
        items = list(result.scalars().all())
        total = await self.session.scalar(
            select(func.count()).select_from(PlatformModel).where(*filters)
        )
        return build_page_data(items, params, int(total or 0))

    async def count_bindings(self, model_id: int) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(AgentModelBinding)
            .where(AgentModelBinding.model_id == model_id)
        )
        return int(total or 0)


class AgentModelBindingRepository(BaseRepository[AgentModelBinding]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AgentModelBinding)

    async def list_for_agent(self, agent_id: int) -> list[AgentModelBinding]:
        result = await self.session.execute(
            select(AgentModelBinding)
            .options(selectinload(AgentModelBinding.model))
            .where(AgentModelBinding.agent_id == agent_id)
            .order_by(AgentModelBinding.role.asc())
        )
        return list(result.scalars().all())

    async def get_for_agent_role(
        self, agent_id: int, role: str
    ) -> AgentModelBinding | None:
        result = await self.session.execute(
            select(AgentModelBinding).where(
                AgentModelBinding.agent_id == agent_id,
                AgentModelBinding.role == role,
            )
        )
        return result.scalar_one_or_none()

    async def delete_for_agent(self, agent_id: int) -> None:
        result = await self.session.execute(
            select(AgentModelBinding).where(AgentModelBinding.agent_id == agent_id)
        )
        for binding in result.scalars().all():
            await self.session.delete(binding)
