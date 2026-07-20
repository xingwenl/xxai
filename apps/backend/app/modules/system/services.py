from __future__ import annotations

from app.core.config import get_settings
from app.modules.system.schemas import HealthPayload


def build_health_payload() -> HealthPayload:
    settings = get_settings()
    return HealthPayload(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        status="ok",
    )
