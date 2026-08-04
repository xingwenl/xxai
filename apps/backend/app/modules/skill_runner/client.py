import hashlib
import hmac

import httpx

from app.core.config import get_settings
from app.modules.skill_runner.schemas import ScriptExecuteRequest, ScriptExecuteResponse


class SkillRunnerClient:
    async def execute(self, payload: ScriptExecuteRequest) -> ScriptExecuteResponse:
        settings = get_settings()
        body = payload.model_dump_json().encode()
        signature = hmac.new(
            settings.skill_runner_shared_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        async with httpx.AsyncClient(
            timeout=settings.skill_runner_timeout_seconds + 5
        ) as client:
            response = await client.post(
                f"{settings.skill_runner_url.rstrip('/')}/execute",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Skill-Runner-Signature": signature,
                },
            )
        response.raise_for_status()
        return ScriptExecuteResponse.model_validate(response.json())

    async def health(self) -> bool:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(
                    f"{settings.skill_runner_url.rstrip('/')}/health"
                )
            return response.status_code == 200
        except httpx.HTTPError:
            return False
