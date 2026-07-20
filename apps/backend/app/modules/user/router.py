from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.user.repositories import UserRepository
from app.modules.user.schemas import UserCreate, UserListData, UserRead, UserUpdate
from app.modules.user.services import (
    create_user,
    delete_user,
    get_user_detail,
    list_users,
    update_user,
)
from app.shared.pagination import PageResponse, PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response


router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=ApiResponse[UserRead], status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    repo = UserRepository(session)
    user = await create_user(repo, payload)
    return success_response(data=UserRead.model_validate(user), message="user created")


@router.get("/{user_id}", response_model=ApiResponse[UserRead])
async def get_user_detail_endpoint(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    repo = UserRepository(session)
    user = await get_user_detail(repo, user_id)
    return success_response(data=UserRead.model_validate(user))


@router.get("", response_model=PageResponse[UserListData])
async def list_users_endpoint(
    params: PaginationParams = Depends(pagination_dependency),
    session: AsyncSession = Depends(get_db_session),
) -> PageResponse[UserListData]:
    repo = UserRepository(session)
    payload = await list_users(repo, params)
    return PageResponse(data=payload)


@router.put("/{user_id}", response_model=ApiResponse[UserRead])
async def update_user_endpoint(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    repo = UserRepository(session)
    user = await update_user(repo, user_id, payload)
    return success_response(data=UserRead.model_validate(user), message="user updated")


@router.delete("/{user_id}", response_model=ApiResponse[None])
async def delete_user_endpoint(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    repo = UserRepository(session)
    await delete_user(repo, user_id)
    return success_response(message="user deleted")
