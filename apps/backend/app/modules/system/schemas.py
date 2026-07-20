from __future__ import annotations

from pydantic import BaseModel


class HealthPayload(BaseModel):
    service: str
    version: str
    environment: str
    status: str
