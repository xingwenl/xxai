from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.repositories import EmbedRepository
from app.modules.embed.schemas import (
    EmbedTokenRequest,
    EmbedTokenResponse,
    ConversationMessageRead,
    PlatformEmbedClientCreate,
    PlatformEmbedClientCreated,
    PlatformEmbedClientAgentRead,
    PlatformEmbedClientRead,
    PlatformEmbedClientUpdate,
)
from app.modules.embed.services import (
    bind_embed_client_agent,
    create_embed_client,
    build_token_quota_service,
    issue_embed_token,
    get_embed_message_snapshot,
    rotate_embed_client_secret,
    unbind_embed_client_agent,
    update_embed_client,
)
from app.modules.embed.security import get_current_embed_claims
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["embed"])


async def require_platform_admin(platform_id: int, current_user, session: AsyncSession):
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, current_user.id
    )
    if platform is None:
        raise NotFoundException("platform not found")
    return platform


@router.post(
    "/platforms/{platform_id}/embed-clients",
    response_model=ApiResponse[PlatformEmbedClientCreated],
    status_code=status.HTTP_201_CREATED,
)
async def create_client_endpoint(
    platform_id: int,
    payload: PlatformEmbedClientCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    result = await create_embed_client(
        EmbedRepository(session), platform_id=platform_id, payload=payload
    )
    await session.commit()
    return success_response(data=result, message="embed client created")


@router.get(
    "/platforms/{platform_id}/embed-clients",
    response_model=ApiResponse[list[PlatformEmbedClientRead]],
)
async def list_clients_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    clients = await EmbedRepository(session).list_clients(platform_id)
    return success_response(data=clients)


@router.patch(
    "/platforms/{platform_id}/embed-clients/{client_id}",
    response_model=ApiResponse[PlatformEmbedClientRead],
)
async def update_client_endpoint(
    platform_id: int,
    client_id: str,
    payload: PlatformEmbedClientUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    client = await update_embed_client(
        EmbedRepository(session),
        platform_id=platform_id,
        client_id=client_id,
        payload=payload,
    )
    return success_response(data=client)


@router.get(
    "/platforms/{platform_id}/embed-clients/{client_id}/agents",
    response_model=ApiResponse[list[PlatformEmbedClientAgentRead]],
)
async def list_client_agents_endpoint(
    platform_id: int,
    client_id: str,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    repo = EmbedRepository(session)
    client = await repo.get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    return success_response(data=await repo.list_client_agents(client.id))


@router.post(
    "/platforms/{platform_id}/embed-clients/{client_id}/rotate-secret",
    response_model=ApiResponse[dict[str, str]],
)
async def rotate_secret_endpoint(
    platform_id: int,
    client_id: str,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    secret = await rotate_embed_client_secret(
        EmbedRepository(session), platform_id=platform_id, client_id=client_id
    )
    return success_response(data={"client_secret": secret})


@router.put(
    "/platforms/{platform_id}/embed-clients/{client_id}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def bind_agent_endpoint(
    platform_id: int,
    client_id: str,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    await bind_embed_client_agent(
        EmbedRepository(session),
        AgentRepository(session),
        platform_id=platform_id,
        client_id=client_id,
        agent_id=agent_id,
    )


@router.delete(
    "/platforms/{platform_id}/embed-clients/{client_id}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_agent_endpoint(
    platform_id: int,
    client_id: str,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_platform_admin(platform_id, current_user, session)
    await unbind_embed_client_agent(
        EmbedRepository(session),
        platform_id=platform_id,
        client_id=client_id,
        agent_id=agent_id,
    )


@router.post("/embed/tokens", response_model=ApiResponse[EmbedTokenResponse])
async def issue_token_endpoint(
    payload: EmbedTokenRequest,
    session: AsyncSession = Depends(get_db_session),
):
    embed_repo = EmbedRepository(session)
    client = await embed_repo.get_client_by_id(payload.client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    settings = get_settings()
    redis = Redis.from_url(settings.celery_broker_url) if settings.quota_enabled else None
    try:
        token = await issue_embed_token(
            embed_repo,
            AgentRepository(session),
            payload,
            platform_id=client.platform_id,
            quota_service=(
                build_token_quota_service(client, settings, redis)
                if redis is not None
                else None
            ),
        )
    finally:
        if redis is not None:
            await redis.aclose()
    await session.commit()
    return success_response(data=token, message="embed token issued")


@router.get(
    "/embed/conversations/{conversation_id}/messages",
    response_model=ApiResponse[list[ConversationMessageRead]],
)
async def get_message_snapshot_endpoint(
    conversation_id: int,
    claims=Depends(get_current_embed_claims),
    session: AsyncSession = Depends(get_db_session),
):
    messages = await get_embed_message_snapshot(
        ConversationRepository(session), conversation_id=conversation_id, claims=claims
    )
    return success_response(data=messages)
