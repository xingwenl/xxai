from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.embed.repositories import EmbedRepository
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.schemas import (
    HostToolAuditRead,
    HostToolPolicyCreate,
    HostToolPolicyRead,
    HostToolPolicyUpdate,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["host-tools"])


async def require_platform_admin(platform_id: int, current_user, session: AsyncSession):
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, current_user.id
    )
    if platform is None:
        raise NotFoundException("platform not found")


@router.post(
    "/platforms/{platform_id}/host-tools",
    response_model=ApiResponse[HostToolPolicyRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_host_tool(
    platform_id: int,
    payload: HostToolPolicyCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    repo = HostToolRepository(session)
    if await repo.get_policy_by_name(platform_id, payload.name):
        raise ValueError("host tool already exists")
    return success_response(data=await repo.create_policy(platform_id, payload))


@router.get(
    "/platforms/{platform_id}/host-tools",
    response_model=ApiResponse[list[HostToolPolicyRead]],
)
async def list_host_tools(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    return success_response(
        data=await HostToolRepository(session).list_policies(platform_id)
    )


@router.patch(
    "/platforms/{platform_id}/host-tools/{tool_id}",
    response_model=ApiResponse[HostToolPolicyRead],
)
async def update_host_tool(
    platform_id: int,
    tool_id: int,
    payload: HostToolPolicyUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    policy = await HostToolRepository(session).get_policy(platform_id, tool_id)
    if policy is None:
        raise NotFoundException("host tool not found")
    return success_response(
        data=await HostToolRepository(session).update_policy(
            policy, payload.model_dump(exclude_unset=True)
        )
    )


@router.put(
    "/platforms/{platform_id}/agents/{agent_id}/host-tools/{tool_id}", status_code=204
)
async def bind_agent_host_tool(
    platform_id: int,
    agent_id: int,
    tool_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    policy = await HostToolRepository(session).get_policy(platform_id, tool_id)
    if policy is None:
        raise NotFoundException("host tool not found")
    await HostToolRepository(session).bind_agent(agent_id, tool_id)


@router.delete(
    "/platforms/{platform_id}/agents/{agent_id}/host-tools/{tool_id}", status_code=204
)
async def unbind_agent_host_tool(
    platform_id: int,
    agent_id: int,
    tool_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    await HostToolRepository(session).unbind_agent(agent_id, tool_id)


@router.put(
    "/platforms/{platform_id}/embed-clients/{client_id}/host-tools/{tool_id}",
    status_code=204,
)
async def bind_client_host_tool(
    platform_id: int,
    client_id: str,
    tool_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    policy = await HostToolRepository(session).get_policy(platform_id, tool_id)
    client = await EmbedRepository(session).get_client(platform_id, client_id)
    if policy is None or client is None:
        raise NotFoundException("host tool or embed client not found")
    await HostToolRepository(session).bind_client(client.id, tool_id)


@router.delete(
    "/platforms/{platform_id}/embed-clients/{client_id}/host-tools/{tool_id}",
    status_code=204,
)
async def unbind_client_host_tool(
    platform_id: int,
    client_id: str,
    tool_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    client = await EmbedRepository(session).get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    await HostToolRepository(session).unbind_client(client.id, tool_id)


@router.get(
    "/platforms/{platform_id}/host-tool-audits",
    response_model=ApiResponse[list[HostToolAuditRead]],
)
async def list_host_tool_audits(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    return success_response(
        data=await HostToolRepository(session).list_audits(platform_id)
    )
