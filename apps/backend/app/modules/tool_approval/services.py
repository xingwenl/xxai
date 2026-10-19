from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tool_approval.contracts import (
    CONFIRMATION_TTL_SECONDS,
    MEMORY_EXEMPT_SIDE_EFFECTS,
)
from app.modules.tool_approval.models import ToolConfirmation
from app.modules.tool_approval.repositories import ToolConfirmationRepository
from app.shared.exceptions import ConflictException, NotFoundException


class ToolApprovalService:
    """工具确认的业务层：请求确认、解决确认、会话内确认记忆与 TTL 过期。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ToolConfirmationRepository(session)

    async def remember_check(
        self,
        *,
        platform_id: int,
        conversation_id: int,
        tool_name: str,
        side_effect: str,
    ) -> bool:
        """同一会话内刚刚批准过同类工具时返回 True，调用方据此跳过重复确认。

        只复用 TTL 窗口内的批准：窗口外的批准视为「当时那一次」的授权，
        不能让用户今天点的一次同意永久放行后续所有同名调用。
        """

        if side_effect in MEMORY_EXEMPT_SIDE_EFFECTS:
            # 涉及钱的副作用每次都必须单独批准，不参与记忆。
            return False
        since = datetime.now(UTC) - timedelta(seconds=CONFIRMATION_TTL_SECONDS)
        hit = await self.repository.find_recent_approved(
            platform_id=platform_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            side_effects={side_effect},
            since=since,
        )
        return hit is not None

    async def request(
        self,
        *,
        platform_id: int,
        agent_id: int,
        conversation_id: int | None,
        tool_name: str,
        tool_type: str,
        side_effect: str,
        arguments: dict,
        user_id: int | None = None,
        platform_end_user_id: int | None = None,
    ) -> ToolConfirmation:
        expires_at = datetime.now(UTC) + timedelta(seconds=CONFIRMATION_TTL_SECONDS)
        return await self.repository.create(
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            tool_type=tool_type,
            side_effect=side_effect,
            arguments=arguments,
            expires_at=expires_at,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
        )

    async def resolve(
        self,
        *,
        confirmation_id: int,
        approved: bool,
        actor: str,
    ) -> ToolConfirmation:
        """把一条 pending 确认变成 approved / rejected（已过期则记为 expired）。

        `actor` 写入 `resolved_by`（end_user / user / policy），用于审计回答
        「这次放行是谁批准的」。
        """

        confirmation = await self.repository.get(confirmation_id)
        if confirmation is None:
            raise NotFoundException("tool confirmation not found")
        # 先刷一次再判状态与过期：这条实例可能是在本请求更早的 `request()` 里创建并
        # 缓存在 identity map 中的（会话是 expire_on_commit=False），期间可能已被 TTL
        # 扫描或另一个解决请求改过。用缓存里的旧 `expires_at` 去判过期，会把「已经
        # 过期的确认」当成有效批准放行。
        await self.session.refresh(confirmation)
        if confirmation.status != "pending":
            raise ConflictException("tool confirmation already resolved")

        if confirmation.expires_at <= datetime.now(UTC):
            # 过期确认的解决动作只做归档：抢到就记为 expired，抢不到说明另一个
            # 请求已经处理过它，按冲突返回，绝不把过期记录当成批准。
            if not await self.repository.claim(
                confirmation_id, "expired", resolved_by="timeout"
            ):
                raise ConflictException("tool confirmation already resolved")
            return await self._reload(confirmation_id)

        claimed = await self.repository.claim(
            confirmation_id,
            "approved" if approved else "rejected",
            resolved_by=actor,
        )
        if not claimed:
            raise ConflictException("tool confirmation already resolved")
        return await self._reload(confirmation_id)

    async def expire(self, *, confirmation_id: int) -> ToolConfirmation:
        """把一条确认标记为过期（TTL 扫描或调用方主动收尾用）。"""

        confirmation = await self.repository.get(confirmation_id)
        if confirmation is None:
            raise NotFoundException("tool confirmation not found")
        await self.repository.claim(confirmation_id, "expired", resolved_by="timeout")
        return await self._reload(confirmation_id)

    async def _reload(self, confirmation_id: int) -> ToolConfirmation:
        # claim 内部已 commit，这里重新查一次拿到最新状态；同时让返回类型非空，
        # 避免调用方对 Optional 做额外处理。
        confirmation = await self.repository.get(confirmation_id)
        if confirmation is None:
            raise NotFoundException("tool confirmation not found")
        # 必须显式 refresh：claim 走的是 Core UPDATE（synchronize_session=False），
        # 而会话工厂是 expire_on_commit=False（app/core/database.py:33），因此这条
        # 被 identity map 缓存住的实例仍停留在 pending —— 只查不刷的话，调用方会
        # 把「刚批准」读成「未批准」，把「已过期」读成「未过期」。
        await self.session.refresh(confirmation)
        return confirmation
