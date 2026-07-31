from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.model_usage.repositories import ModelUsageRepository
from app.modules.model_usage.schemas import (
    ModelUsagePage,
    ModelUsageSummary,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(
    prefix="/platforms/{platform_id}/model-usage-records",
    tags=["model-usage"],
)


async def _require_admin(
    platform_id: int,
    user_id: int,
    session: AsyncSession,
) -> None:
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _validate_dates(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise BadRequestException("start_date must be before or equal to end_date")


@router.get("", response_model=ApiResponse[ModelUsagePage])
async def list_model_usage_endpoint(
    platform_id: int,
    start_date: date = Query(...),
    end_date: date = Query(...),
    agent_id: int | None = Query(default=None),
    client_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ModelUsagePage]:
    _validate_dates(start_date, end_date)
    await _require_admin(platform_id, current_user.id, session)
    data = await ModelUsageRepository(session).list_records(
        platform_id=platform_id,
        agent_id=agent_id,
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return success_response(data=data, message="model usage listed")


@router.get("/summary", response_model=ApiResponse[ModelUsageSummary])
async def summarize_model_usage_endpoint(
    platform_id: int,
    start_date: date = Query(...),
    end_date: date = Query(...),
    agent_id: int | None = Query(default=None),
    client_id: str | None = Query(default=None),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ModelUsageSummary]:
    _validate_dates(start_date, end_date)
    await _require_admin(platform_id, current_user.id, session)
    data = await ModelUsageRepository(session).summary(
        platform_id=platform_id,
        agent_id=agent_id,
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
    )
    return success_response(data=data, message="model usage summarized")
