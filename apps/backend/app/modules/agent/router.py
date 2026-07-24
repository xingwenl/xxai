from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.schemas import (
    AgentCreate,
    AgentRead,
    AgentVersionCreate,
    AgentVersionRead,
)
from app.modules.agent.services import (
    create_agent,
    create_agent_version,
    publish_agent_version,
    rollback_agent,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}/agents", tags=["agents"])


async def _require_platform_admin(
    platform_id: int, user_id: int, session: AsyncSession
) -> None:
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, user_id
    )
    if platform is None:
        raise NotFoundException("platform not found")


def _version_read(version) -> AgentVersionRead:
    return AgentVersionRead.model_validate(
        {**version.__dict__, "has_api_key": bool(version.api_key_encrypted)}
    )


@router.post(
    "", response_model=ApiResponse[AgentRead], status_code=status.HTTP_201_CREATED
)
async def create_agent_endpoint(
    platform_id: int,
    payload: AgentCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    agent = await create_agent(
        AgentRepository(session), payload, platform_id=platform_id
    )
    return success_response(
        data=AgentRead.model_validate(agent), message="agent created"
    )


@router.post(
    "/{agent_id}/versions",
    response_model=ApiResponse[AgentVersionRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_version_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentVersionCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await create_agent_version(
        AgentRepository(session), agent_id, payload, platform_id=platform_id
    )
    return success_response(
        data=_version_read(version), message="agent version created"
    )


@router.post(
    "/{agent_id}/versions/{version_id}/publish",
    response_model=ApiResponse[AgentVersionRead],
)
async def publish_agent_version_endpoint(
    platform_id: int,
    agent_id: int,
    version_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await publish_agent_version(
        AgentRepository(session), agent_id, version_id, platform_id=platform_id
    )
    return success_response(
        data=_version_read(version), message="agent version published"
    )


@router.post(
    "/{agent_id}/versions/{version_id}/rollback",
    response_model=ApiResponse[AgentVersionRead],
)
async def rollback_agent_endpoint(
    platform_id: int,
    agent_id: int,
    version_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await rollback_agent(
        AgentRepository(session), agent_id, version_id, platform_id=platform_id
    )
    return success_response(data=_version_read(version), message="agent rolled back")
