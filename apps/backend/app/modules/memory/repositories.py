from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.modules.memory.models import UserMemory
from app.shared.base_repository import BaseRepository
from app.shared.exceptions import ConflictException


class MemoryRepository(BaseRepository[UserMemory]):
    def __init__(self, session) -> None:
        super().__init__(session, UserMemory)

    async def list_for_user(
        self,
        platform_id: int,
        user_id: int,
        *,
        kind: str | None = None,
        include_history: bool = False,
        query: str | None = None,
        key: str | None = None,
        limit: int = 200,
    ) -> list[UserMemory]:
        """按主体列出记忆。

        ``include_history=False`` 只返回当前有效的行（``valid_until IS NULL``）；
        被新值覆盖的旧事实只有在显式要求历史时才出现，这样「现在是什么」与
        「以前是什么」两种问题各有一条确定路径。
        """

        stmt = select(UserMemory).where(
            UserMemory.platform_id == platform_id,
            UserMemory.user_id == user_id,
        )
        if not include_history:
            stmt = stmt.where(UserMemory.valid_until.is_(None))
        if kind is not None:
            stmt = stmt.where(UserMemory.kind == kind)
        if key is not None:
            stmt = stmt.where(UserMemory.key == key)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    UserMemory.key.ilike(pattern),
                    UserMemory.content.ilike(pattern),
                )
            )
        stmt = stmt.order_by(
            UserMemory.kind.asc(),
            UserMemory.occurred_at.desc().nullslast(),
            UserMemory.id.desc(),
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_events_recent(
        self, platform_id: int, user_id: int, *, limit: int = 50
    ) -> list[UserMemory]:
        """最近发生的经历，按发生时间倒序，供「我干过什么」类问题取用。"""

        stmt = (
            select(UserMemory)
            .where(
                UserMemory.platform_id == platform_id,
                UserMemory.user_id == user_id,
                UserMemory.kind == "event",
            )
            .order_by(UserMemory.occurred_at.desc().nullslast(), UserMemory.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_fact(
        self, platform_id: int, user_id: int, key: str
    ) -> UserMemory | None:
        stmt = select(UserMemory).where(
            UserMemory.platform_id == platform_id,
            UserMemory.user_id == user_id,
            UserMemory.kind == "fact",
            UserMemory.key == key,
            UserMemory.valid_until.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_fact(
        self,
        *,
        platform_id: int,
        user_id: int,
        key: str,
        content: str,
        occurred_at: datetime | None,
        source: str,
        source_conversation_id: int | None = None,
    ) -> tuple[UserMemory, UserMemory | None]:
        """写入事实：关闭同 key 的旧值并插入新行，返回 (新行, 旧行)。

        关闭与插入在**同一个事务**里提交：分两次提交时若插入失败，旧值已经被
        关闭，用户会得到「什么都不知道」的空档；这条路径不允许中间态。

        并发下两个写入都可能看不到旧值（都插有效行），此时由部分唯一索引
        拦下第二条并在这里转成明确的冲突错误，而不是写坏时间线。
        """

        now = datetime.now(timezone.utc)
        previous = await self.find_active_fact(platform_id, user_id, key)
        if previous is not None:
            previous.valid_until = now
        row = UserMemory(
            platform_id=platform_id,
            user_id=user_id,
            kind="fact",
            key=key,
            content=content,
            occurred_at=occurred_at or now,
            source=source,
            source_conversation_id=source_conversation_id,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(
                "memory fact conflict", error_code="memory_fact_conflict"
            ) from exc
        await self.session.refresh(row)
        return row, previous

    async def create_event(
        self,
        *,
        platform_id: int,
        user_id: int,
        content: str,
        occurred_at: datetime,
        source: str,
        source_conversation_id: int | None = None,
    ) -> UserMemory:
        row = UserMemory(
            platform_id=platform_id,
            user_id=user_id,
            kind="event",
            key=None,
            content=content,
            occurred_at=occurred_at,
            source=source,
            source_conversation_id=source_conversation_id,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_content(
        self, row: UserMemory, *, content: str, occurred_at: datetime | None = None
    ) -> UserMemory:
        row.content = content
        if occurred_at is not None:
            row.occurred_at = occurred_at
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def count_active_by_kind(
        self, platform_id: int, user_id: int
    ) -> tuple[int, int]:
        """返回当前有效记忆的 (事实数, 经历数)，只用于注入索引行。"""

        stmt = (
            select(UserMemory.kind, func.count())
            .where(
                UserMemory.platform_id == platform_id,
                UserMemory.user_id == user_id,
                UserMemory.valid_until.is_(None),
            )
            .group_by(UserMemory.kind)
        )
        result = await self.session.execute(stmt)
        counts = {kind: int(count) for kind, count in result.all()}
        return counts.get("fact", 0), counts.get("event", 0)

    async def delete_all_for_user(self, platform_id: int, user_id: int) -> int:
        stmt = delete(UserMemory).where(
            UserMemory.platform_id == platform_id,
            UserMemory.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(result.rowcount or 0)
