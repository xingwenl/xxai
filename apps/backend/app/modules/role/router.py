from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.role.repositories import RoleRepository
from app.modules.role.schemas import RoleCreate, RoleListData, RoleListQuery, RoleRead, RoleUpdate
from app.modules.role.services import create_role, delete_role, get_role_detail, list_roles, update_role
from app.shared.pagination import PageResponse, PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response


router = APIRouter(
    prefix="/roles",
    tags=["roles"],
    dependencies=[Depends(require_current_active_user)],
)


def role_list_query_dependency(
    name: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    code: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Annotated[str, Query(pattern=r"^-?created_at$")] = "-created_at",
) -> RoleListQuery:
    return RoleListQuery(name=name, code=code, sort=sort)


@router.post("", response_model=ApiResponse[RoleRead], status_code=status.HTTP_201_CREATED)
async def create_role_endpoint(
    payload: RoleCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[RoleRead]:
    repo = RoleRepository(session)
    role = await create_role(repo, payload)
    return success_response(data=role, message="role created")


@router.get("/{role_id}", response_model=ApiResponse[RoleRead])
async def get_role_detail_endpoint(
    role_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[RoleRead]:
    repo = RoleRepository(session)
    role = await get_role_detail(repo, role_id)
    return success_response(data=role)


@router.get("", response_model=PageResponse[RoleListData])
async def list_roles_endpoint(
    params: PaginationParams = Depends(pagination_dependency),
    query: RoleListQuery = Depends(role_list_query_dependency),
    session: AsyncSession = Depends(get_db_session),
) -> PageResponse[RoleListData]:
    repo = RoleRepository(session)
    payload = await list_roles(repo, params, query)
    return PageResponse(data=payload)


@router.patch("/{role_id}", response_model=ApiResponse[RoleRead])
async def update_role_endpoint(
    role_id: int,
    payload: RoleUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[RoleRead]:
    repo = RoleRepository(session)
    role = await update_role(repo, role_id, payload)
    return success_response(data=role, message="role updated")


@router.delete("/{role_id}", response_model=ApiResponse[None])
async def delete_role_endpoint(
    role_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    repo = RoleRepository(session)
    await delete_role(repo, role_id)
    return success_response(message="role deleted")
