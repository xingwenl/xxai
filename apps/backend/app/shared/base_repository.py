from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, item_id: Any) -> ModelT | None:
        return await self.session.get(self.model, item_id)

    async def get_one_by(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: ColumnElement[Any] | None = None,
    ) -> list[ModelT]:
        stmt = select(self.model)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: ColumnElement[Any] | None = None,
        **filters: Any,
    ) -> list[ModelT]:
        stmt = select(self.model).filter_by(**filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def exists(self, **filters: Any) -> bool:
        stmt = select(self.model).filter_by(**filters).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create(self, **kwargs: Any) -> ModelT:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelT, **kwargs: Any) -> ModelT:
        for field, value in kwargs.items():
            setattr(instance, field, value)

        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.commit()
