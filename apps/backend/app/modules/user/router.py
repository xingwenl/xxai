from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.role.repositories import RoleRepository
from app.modules.user.repositories import UserRepository
from app.modules.user.schemas import (
    UserCreate,
    UserListData,
    UserListField,
    UserListQuery,
    UserRead,
    UserUpdate,
)
from app.modules.user.services import (
    create_user,
    delete_user,
    get_user_detail,
    list_users,
    update_user,
)
from app.shared.pagination import PageResponse, PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response


router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_current_active_user)],
)


def user_list_query_dependency(
    name: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    email: Annotated[str | None, Query(min_length=3, max_length=255)] = None,
    role_id: Annotated[int | None, Query(ge=1)] = None,
    role_code: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Annotated[str, Query(pattern=r"^-?created_at$")] = "-created_at",
    fields: Annotated[str | None, Query(description="comma-separated user fields")] = None,
) -> UserListQuery:
    parsed_fields: list[UserListField] | None = None
    if fields is not None:
        raw_fields = [item.strip() for item in fields.split(",") if item.strip()]
        if not raw_fields:
            raise HTTPException(status_code=422, detail="fields must not be empty")

        allowed_fields = set(UserListField.__args__)
        invalid_fields = [item for item in raw_fields if item not in allowed_fields]
        if invalid_fields:
            raise HTTPException(
                status_code=422,
                detail=f"unsupported fields: {', '.join(invalid_fields)}",
            )

        parsed_fields = list(dict.fromkeys(raw_fields))  # type: ignore[arg-type]

    return UserListQuery(
        name=name,
        email=email,
        role_id=role_id,
        role_code=role_code,
        sort=sort,
        fields=parsed_fields,
    )


@router.post("", response_model=ApiResponse[UserRead], status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)
    user = await create_user(user_repo, role_repo, payload)
    return success_response(data=user, message="user created")


@router.get("/{user_id}", response_model=ApiResponse[UserRead])
async def get_user_detail_endpoint(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)
    user = await get_user_detail(user_repo, role_repo, user_id)
    return success_response(data=user)


@router.get("", response_model=PageResponse[UserListData])
async def list_users_endpoint(
    params: PaginationParams = Depends(pagination_dependency),
    query: UserListQuery = Depends(user_list_query_dependency),
    session: AsyncSession = Depends(get_db_session),
) -> PageResponse[UserListData]:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)
    payload = await list_users(user_repo, role_repo, params, query)
    return PageResponse(data=payload)


@router.patch("/{user_id}", response_model=ApiResponse[UserRead])
async def update_user_endpoint(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)
    user = await update_user(user_repo, role_repo, user_id, payload)
    return success_response(data=user, message="user updated")


@router.delete("/{user_id}", response_model=ApiResponse[None])
async def delete_user_endpoint(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    repo = UserRepository(session)
    await delete_user(repo, user_id)
    return success_response(message="user deleted")
