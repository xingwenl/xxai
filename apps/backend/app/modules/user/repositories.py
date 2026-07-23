from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement

from app.modules.role.models import Role, UserRole
from app.modules.user.models import User
from app.modules.user.schemas import UserCreate, UserListQuery, UserUpdate
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PaginationParams


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).options(selectinload(User.roles)).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_account(self, account: str) -> User | None:
        stmt = select(User).options(selectinload(User.roles)).where(User.account == account)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, item_id: int) -> User | None:
        stmt = select(User).options(selectinload(User.roles)).where(User.id == item_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _build_filters(self, query: UserListQuery) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if query.name:
            filters.append(User.name.ilike(f"%{query.name}%"))
        if query.email:
            filters.append(User.email == query.email)
        if query.role_id is not None:
            filters.append(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_id == query.role_id))
            )
        if query.role_code:
            filters.append(
                User.id.in_(
                    select(UserRole.user_id)
                    .join(Role, UserRole.role_id == Role.id)
                    .where(Role.code == query.role_code)
                )
            )
        return filters

    def _build_order_by(self, query: UserListQuery) -> ColumnElement[object]:
        if query.sort == "created_at":
            return User.created_at.asc()
        return User.created_at.desc()

    async def list_users(self, params: PaginationParams, query: UserListQuery) -> list[User]:
        stmt = (
            select(User)
            .options(selectinload(User.roles))
            .where(*self._build_filters(query))
            .order_by(self._build_order_by(query))
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_users(self, query: UserListQuery) -> int:
        return await self.count_by_filters(self._build_filters(query))

    async def create_user(self, payload: UserCreate, *, password: str | None = None) -> User:
        payload_dict = payload.model_dump(exclude={"role_ids"})
        if password is not None:
            payload_dict["password"] = password
        return await self.create(**payload_dict)

    async def update_user(self, user: User, payload: UserUpdate) -> User:
        updates = payload.model_dump(exclude_unset=True, exclude_none=True, exclude={"role_ids"})
        return await self.update(user, **updates)

    async def delete_user(self, user: User) -> None:
        await self.delete(user)

    async def replace_user_roles(self, user_id: int, role_ids: list[int]) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        if role_ids:
            self.session.add_all([UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids])
        await self.session.commit()
