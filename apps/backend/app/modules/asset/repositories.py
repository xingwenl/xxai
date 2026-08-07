from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.asset.models import ConversationAsset


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values) -> ConversationAsset:
        asset = ConversationAsset(**values)
        self.session.add(asset)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def get_for_user(
        self, asset_id: str, user_id: int
    ) -> ConversationAsset | None:
        return await self.session.scalar(
            select(ConversationAsset).where(
                ConversationAsset.asset_id == asset_id,
                ConversationAsset.user_id == user_id,
            )
        )

    async def get_for_embed(
        self,
        asset_id: str,
        *,
        platform_id: int,
        agent_id: int,
        end_user_id: int,
    ) -> ConversationAsset | None:
        return await self.session.scalar(
            select(ConversationAsset).where(
                ConversationAsset.asset_id == asset_id,
                ConversationAsset.platform_id == platform_id,
                ConversationAsset.agent_id == agent_id,
                ConversationAsset.platform_end_user_id == end_user_id,
            )
        )
