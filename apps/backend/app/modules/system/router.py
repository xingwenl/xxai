from __future__ import annotations

from fastapi import APIRouter

from app.modules.system.schemas import HealthPayload
from app.modules.system.services import build_health_payload
from app.shared.responses import ApiResponse, success_response


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=ApiResponse[HealthPayload])
async def health_check() -> ApiResponse[HealthPayload]:
    payload = build_health_payload()
    return success_response(data=payload)
