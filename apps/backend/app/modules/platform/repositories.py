from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import Platform, PlatformAdmin
from app.modules.platform.schemas import PlatformCreate
from app.shared.base_repository import BaseRepository


class PlatformRepository(BaseRepository[Platform]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Platform)

    async def get_by_code(self, code: str) -> Platform | None:
        result = await self.session.execute(select(Platform).where(Platform.code == code))
        return result.scalar_one_or_none()

    async def get_by_id_for_user(self, platform_id: int, user_id: int) -> Platform | None:
        statement = (
            select(Platform)
            .join(PlatformAdmin, PlatformAdmin.platform_id == Platform.id)
            .where(Platform.id == platform_id, PlatformAdmin.user_id == user_id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create_platform(self, payload: PlatformCreate, owner_id: int) -> Platform:
        platform = Platform(name=payload.name, code=payload.code)
        self.session.add(platform)
        await self.session.flush()
        self.session.add(PlatformAdmin(platform_id=platform.id, user_id=owner_id))
        await self.session.commit()
        await self.session.refresh(platform)
        return platform
