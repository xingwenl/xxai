from __future__ import annotations

from app.modules.role.repositories import RoleRepository
from app.modules.role.schemas import RoleCreate, RoleListData, RoleListQuery, RoleRead, RoleUpdate
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams, build_page_data


async def create_role(repo: RoleRepository, payload: RoleCreate) -> RoleRead:
    existing_role = await repo.get_by_code(payload.code)
    if existing_role is not None:
        raise ConflictException("role code already exists")

    role = await repo.create_role(payload)
    return RoleRead.model_validate(role)


async def get_role_detail(repo: RoleRepository, role_id: int) -> RoleRead:
    role = await repo.get_by_id(role_id)
    if role is None:
        raise NotFoundException("role not found")
    return RoleRead.model_validate(role)


async def list_roles(repo: RoleRepository, params: PaginationParams, query: RoleListQuery) -> RoleListData:
    roles = await repo.list_roles(params, query)
    total = await repo.count_roles(query)
    return RoleListData(
        **build_page_data(
            items=[RoleRead.model_validate(role) for role in roles],
            params=params,
            total=total,
        ).model_dump()
    )


async def update_role(repo: RoleRepository, role_id: int, payload: RoleUpdate) -> RoleRead:
    role = await repo.get_by_id(role_id)
    if role is None:
        raise NotFoundException("role not found")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise BadRequestException("no fields to update")

    if "code" in updates and updates["code"] != role.code:
        existing_role = await repo.get_by_code(updates["code"])
        if existing_role is not None and existing_role.id != role_id:
            raise ConflictException("role code already exists")

    updated_role = await repo.update_role(role, payload)
    return RoleRead.model_validate(updated_role)


async def delete_role(repo: RoleRepository, role_id: int) -> None:
    role = await repo.get_by_id(role_id)
    if role is None:
        raise NotFoundException("role not found")

    bindings = await repo.count_user_bindings(role_id)
    if bindings > 0:
        raise ConflictException("role is still assigned to users")

    await repo.delete(role)
