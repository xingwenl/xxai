from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.platform.schemas import PlatformCreate, PlatformRead, PlatformUpdate
from app.modules.platform.services import (
    create_platform,
    delete_platform,
    get_platform,
    update_platform,
)
from app.shared.responses import ApiResponse, success_response


router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("", response_model=ApiResponse[list[PlatformRead]])
async def list_platforms_endpoint(
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[PlatformRead]]:
    platforms = await PlatformRepository(session).list_for_user(current_user.id)
    return success_response(data=[PlatformRead.model_validate(item) for item in platforms])


@router.post("", response_model=ApiResponse[PlatformRead], status_code=status.HTTP_201_CREATED)
async def create_platform_endpoint(
    payload: PlatformCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformRead]:
    platform = await create_platform(
        PlatformRepository(session), payload, user_id=current_user.id
    )
    return success_response(data=platform, message="platform created")


@router.get("/{platform_id}", response_model=ApiResponse[PlatformRead])
async def get_platform_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformRead]:
    platform = await get_platform(
        PlatformRepository(session), platform_id=platform_id, user_id=current_user.id
    )
    return success_response(data=platform)


@router.patch("/{platform_id}", response_model=ApiResponse[PlatformRead])
async def update_platform_endpoint(
    platform_id: int,
    payload: PlatformUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformRead]:
    platform = await update_platform(
        PlatformRepository(session),
        platform_id=platform_id,
        payload=payload,
        user_id=current_user.id,
    )
    return success_response(data=platform, message="platform updated")


@router.delete("/{platform_id}", response_model=ApiResponse[None])
async def delete_platform_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    await delete_platform(
        PlatformRepository(session), platform_id=platform_id, user_id=current_user.id
    )
    return success_response(message="platform deleted")
