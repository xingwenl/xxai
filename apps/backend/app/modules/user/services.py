from __future__ import annotations

from app.modules.user.repositories import UserRepository
from app.modules.user.schemas import UserCreate, UserListData, UserRead, UserUpdate
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams, build_page_data


async def create_user(repo: UserRepository, payload: UserCreate):
    existing_user = await repo.get_by_email(payload.email)
    if existing_user is not None:
        raise ConflictException("user email already exists")

    return await repo.create_user(payload)


async def get_user_detail(repo: UserRepository, user_id: int):
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    return user


async def list_users(repo: UserRepository, params: PaginationParams) -> UserListData:
    users = await repo.list_users(params)
    total = await repo.count_users()
    return UserListData(
        **build_page_data(
            items=[UserRead.model_validate(user) for user in users],
            params=params,
            total=total,
        ).model_dump()
    )


async def update_user(repo: UserRepository, user_id: int, payload: UserUpdate):
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise BadRequestException("no fields to update")

    if "email" in updates and updates["email"] != user.email:
        existing_user = await repo.get_by_email(updates["email"])
        if existing_user is not None and existing_user.id != user_id:
            raise ConflictException("user email already exists")

    return await repo.update_user(user, payload)


async def delete_user(repo: UserRepository, user_id: int) -> None:
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("user not found")

    await repo.delete_user(user)
