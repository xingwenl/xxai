from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement

from app.modules.role.models import Role, UserRole
from app.modules.role.schemas import RoleCreate, RoleListQuery, RoleUpdate
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PaginationParams


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Role)

    async def get_by_code(self, code: str) -> Role | None:
        stmt = select(Role).options(selectinload(Role.users)).where(Role.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, role_ids: list[int]) -> list[Role]:
        if not role_ids:
            return []
        stmt = (
            select(Role)
            .options(selectinload(Role.users))
            .where(Role.id.in_(role_ids))
            .order_by(Role.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_roles_by_user_id(self, user_id: int) -> list[Role]:
        stmt = select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id).order_by(Role.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def _build_filters(self, query: RoleListQuery) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if query.name:
            filters.append(Role.name.ilike(f"%{query.name}%"))
        if query.code:
            filters.append(Role.code == query.code)
        return filters

    def _build_order_by(self, query: RoleListQuery) -> ColumnElement[object]:
        if query.sort == "created_at":
            return Role.created_at.asc()
        return Role.created_at.desc()

    async def list_roles(self, params: PaginationParams, query: RoleListQuery) -> list[Role]:
        return await self.list(
            offset=params.offset,
            limit=params.limit,
            filters=self._build_filters(query),
            order_by=self._build_order_by(query),
        )

    async def count_roles(self, query: RoleListQuery) -> int:
        return await self.count_by_filters(self._build_filters(query))

    async def create_role(self, payload: RoleCreate) -> Role:
        return await self.create(**payload.model_dump())

    async def update_role(self, role: Role, payload: RoleUpdate) -> Role:
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        return await self.update(role, **updates)

    async def count_user_bindings(self, role_id: int) -> int:
        stmt = select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def delete_role_bindings_for_user(self, user_id: int) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))

    async def attach_roles_to_user(self, user_id: int, role_ids: list[int]) -> None:
        if not role_ids:
            return
        self.session.add_all([UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids])
