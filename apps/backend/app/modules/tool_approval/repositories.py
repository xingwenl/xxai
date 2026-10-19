from __future__ import annotations

from datetime import UTC, datetime
import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.services import encrypt_secret
from app.modules.tool_approval.models import ToolConfirmation


class ToolConfirmationRepository:
    """`tool_confirmations` 表的存储层：只做读写与 CAS 抢占，不含业务裁决。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        platform_id: int,
        agent_id: int,
        tool_name: str,
        tool_type: str,
        side_effect: str,
        arguments: dict,
        expires_at: datetime,
        conversation_id: int | None = None,
        user_id: int | None = None,
        platform_end_user_id: int | None = None,
    ) -> ToolConfirmation:
        confirmation = ToolConfirmation(
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
            tool_name=tool_name,
            tool_type=tool_type,
            side_effect=side_effect,
            arguments_encrypted=encrypt_secret(
                json.dumps(arguments, ensure_ascii=False)
            ),
            expires_at=expires_at,
        )
        self.session.add(confirmation)
        # 确认记录必须立刻对其它连接可见（等待确认的请求与处理确认的请求分属不同
        # 请求/事务），所以这里直接提交并回读，而不是只 flush。
        await self.session.commit()
        await self.session.refresh(confirmation)
        return confirmation

    async def get(self, confirmation_id: int) -> ToolConfirmation | None:
        return await self.session.scalar(
            select(ToolConfirmation).where(ToolConfirmation.id == confirmation_id)
        )

    async def claim(
        self,
        confirmation_id: int,
        status: str,
        *,
        resolved_by: str | None = None,
    ) -> bool:
        """CAS 抢占：只有仍处于 pending 的行才会被改成目标状态，返回是否抢到。

        用「状态仍为 pending」作为比较条件，是为了让并发的两个解决请求（用户点击
        与 TTL 过期扫描）只有一个能生效，避免同一个确认被批准两次或批准后又过期。
        """

        values: dict = {"status": status, "resolved_at": datetime.now(UTC)}
        if resolved_by is not None:
            values["resolved_by"] = resolved_by
        result = await self.session.execute(
            update(ToolConfirmation)
            .where(
                ToolConfirmation.id == confirmation_id,
                ToolConfirmation.status == "pending",
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def find_recent_approved(
        self,
        *,
        platform_id: int,
        conversation_id: int,
        tool_name: str,
        side_effects: set[str] | frozenset[str],
        since: datetime,
    ) -> ToolConfirmation | None:
        """查同会话、同工具名、副作用匹配且在 `since` 之后被批准的最新一条记录。

        只按会话维度记忆：跨会话复用批准会让「用户在 A 会话点过同意」变成在 B 会话
        静默放行的依据，超出用户当时表达的意图范围。
        """

        return await self.session.scalar(
            select(ToolConfirmation)
            .where(
                ToolConfirmation.platform_id == platform_id,
                ToolConfirmation.conversation_id == conversation_id,
                ToolConfirmation.tool_name == tool_name,
                ToolConfirmation.status == "approved",
                ToolConfirmation.side_effect.in_(side_effects),
                ToolConfirmation.resolved_at >= since,
            )
            .order_by(ToolConfirmation.id.desc())
            .limit(1)
        )
