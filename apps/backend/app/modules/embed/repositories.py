from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embed.models import PlatformEmbedClient, PlatformEndUser


class EmbedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_client(self, platform_id: int, client_id: str):
        return await self.session.scalar(
            select(PlatformEmbedClient).where(
                PlatformEmbedClient.platform_id == platform_id,
                PlatformEmbedClient.client_id == client_id,
            )
        )

    async def get_end_user(self, platform_id: int, external_user_id: str):
        return await self.session.scalar(
            select(PlatformEndUser).where(
                PlatformEndUser.platform_id == platform_id,
                PlatformEndUser.external_user_id == external_user_id,
            )
        )

    async def create_end_user(
        self, platform_id: int, external_user_id: str, display_name: str | None
    ):
        end_user = PlatformEndUser(
            platform_id=platform_id,
            external_user_id=external_user_id,
            display_name=display_name,
        )
        self.session.add(end_user)
        await self.session.flush()
        return end_user
