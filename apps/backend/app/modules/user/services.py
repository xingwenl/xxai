from __future__ import annotations

from app.core.security import hash_password
from app.modules.role.schemas import RoleSummary
from app.modules.user.repositories import UserRepository
from app.modules.user.schemas import (
    DEFAULT_USER_LIST_FIELDS,
    UserCreate,
    UserListData,
    UserListField,
    UserListQuery,
    UserRead,
    UserUpdate,
)
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams, build_page_data


def build_user_read(user, roles: list[RoleSummary]) -> UserRead:
    return UserRead.model_validate(
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "account": user.account,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "roles": roles,
        }
    )


def build_role_summaries(roles) -> list[RoleSummary]:
    return [RoleSummary.model_validate(role) for role in roles]


async def load_role_summaries(repo, role_ids: list[int]) -> list[RoleSummary]:
    roles = await repo.get_by_ids(role_ids)
    if len(roles) != len(set(role_ids)):
        raise NotFoundException("role not found")
    return build_role_summaries(roles)


async def create_user(repo: UserRepository, role_repo, payload: UserCreate) -> UserRead:
    existing_user = await repo.get_by_email(payload.email)
    if existing_user is not None:
        raise ConflictException("user email already exists")

    existing_account = await repo.get_by_account(payload.account)
    if existing_account is not None:
        raise ConflictException("user account already exists")

    role_summaries = await load_role_summaries(role_repo, payload.role_ids)
    user = await repo.create_user(payload, password=hash_password(payload.password))
    await repo.replace_user_roles(user.id, payload.role_ids)
    return build_user_read(user, role_summaries)


async def get_user_detail(repo: UserRepository, role_repo, user_id: int) -> UserRead:
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    return build_user_read(user, build_role_summaries(user.roles))


def build_user_list_item(user: UserRead, fields: list[UserListField] | None) -> dict[str, str | int | bool]:
    payload = user.model_dump()
    selected_fields = fields or list(DEFAULT_USER_LIST_FIELDS)
    return {field: payload[field] for field in selected_fields}


async def list_users(
    repo: UserRepository,
    role_repo,
    params: PaginationParams,
    query: UserListQuery,
) -> UserListData:
    users = await repo.list_users(params, query)
    total = await repo.count_users(query)

    items: list[dict[str, str | int | bool | list[RoleSummary]]] = []
    for user in users:
        user_read = build_user_read(user, build_role_summaries(user.roles))
        items.append(build_user_list_item(user_read, query.fields))

    return UserListData(
        **build_page_data(
            items=items,
            params=params,
            total=total,
        ).model_dump()
    )


async def update_user(repo: UserRepository, role_repo, user_id: int, payload: UserUpdate) -> UserRead:
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True, exclude={"role_ids"})
    has_role_update = payload.role_ids is not None
    if not updates and not has_role_update:
        raise BadRequestException("no fields to update")

    if "email" in updates and updates["email"] != user.email:
        existing_user = await repo.get_by_email(updates["email"])
        if existing_user is not None and existing_user.id != user_id:
            raise ConflictException("user email already exists")

    if "account" in updates and updates["account"] != user.account:
        existing_account = await repo.get_by_account(updates["account"])
        if existing_account is not None and existing_account.id != user_id:
            raise ConflictException("user account already exists")

    role_summaries: list[RoleSummary] | None = None
    if has_role_update:
        role_summaries = await load_role_summaries(role_repo, payload.role_ids or [])
        await repo.replace_user_roles(user_id, payload.role_ids or [])

    if updates:
        user = await repo.update_user(user, payload)
        user = await repo.get_by_id(user_id)
        if user is None:
            raise NotFoundException("user not found")

    if role_summaries is None:
        role_summaries = build_role_summaries(user.roles)

    return build_user_read(user, role_summaries)


async def delete_user(repo: UserRepository, user_id: int) -> None:
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    await repo.delete_user(user)
