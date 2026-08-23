"""微信助手绑定仓库。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wechat_bot.models import WeChatBotBinding
from app.shared.base_repository import BaseRepository


class WeChatBotBindingRepository(BaseRepository[WeChatBotBinding]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WeChatBotBinding)

    async def get_for_user(
        self, binding_id: int, platform_id: int, user_id: int
    ) -> WeChatBotBinding | None:
        """获取当前用户在某平台下的绑定记录（管理接口权限校验用）。"""
        result = await self.session.execute(
            select(WeChatBotBinding).where(
                WeChatBotBinding.id == binding_id,
                WeChatBotBinding.platform_id == platform_id,
                WeChatBotBinding.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_api_token_hash(
        self, token_hash: str
    ) -> WeChatBotBinding | None:
        """按服务 token 哈希查询启用中的绑定（chat 接口服务认证用）。"""
        result = await self.session.execute(
            select(WeChatBotBinding).where(
                WeChatBotBinding.api_token_hash == token_hash,
                WeChatBotBinding.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, platform_id: int, user_id: int
    ) -> list[WeChatBotBinding]:
        result = await self.session.execute(
            select(WeChatBotBinding)
            .where(
                WeChatBotBinding.platform_id == platform_id,
                WeChatBotBinding.user_id == user_id,
            )
            .order_by(WeChatBotBinding.id.desc())
        )
        return list(result.scalars().all())

    async def list_active(self, limit: int = 20) -> list[WeChatBotBinding]:
        """加载启用中且已生效的绑定（worker 多实例调度用）。"""
        result = await self.session.execute(
            select(WeChatBotBinding)
            .where(
                WeChatBotBinding.is_active.is_(True),
                WeChatBotBinding.status == "active",
            )
            .order_by(WeChatBotBinding.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
