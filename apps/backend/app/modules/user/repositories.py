from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user.models import User
from app.modules.user.schemas import UserCreate, UserUpdate
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PaginationParams


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        return await self.get_one_by(email=email)

    async def list_users(self, params: PaginationParams) -> list[User]:
        return await self.list(
            offset=params.offset,
            limit=params.limit,
            order_by=User.id.desc(),
        )

    async def count_users(self) -> int:
        return await self.count()

    async def create_user(self, payload: UserCreate) -> User:
        return await self.create(name=payload.name, email=payload.email)

    async def update_user(self, user: User, payload: UserUpdate) -> User:
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        return await self.update(user, **updates)

    async def delete_user(self, user: User) -> None:
        await self.delete(user)
