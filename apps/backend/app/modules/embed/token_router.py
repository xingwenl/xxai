from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.modules.agent.repositories import AgentRepository
from app.modules.embed.repositories import EmbedRepository
from app.modules.embed.schemas import EmbedTokenRequest, EmbedTokenResponse
from app.modules.embed.services import build_token_quota_service, issue_embed_token
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["embed"])


@router.get("/agent-token", response_model=ApiResponse[EmbedTokenResponse])
async def get_agent_token(
    external_user_id: str = Query(min_length=1, max_length=255),
    display_name: str | None = Query(default=None, max_length=120),
    origin: str | None = Query(default=None, max_length=500),
    host_tool_names: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[EmbedTokenResponse]:
    """为本地 Demo/业务后端代理签发短期 SDK token。

    Client secret 只从服务端环境变量读取，不接受浏览器提交的 secret。
    生产环境应将 external_user_id 绑定到业务登录态后再开放此代理接口。
    """
    settings = get_settings()
    if not settings.embed_client_id or not settings.embed_client_secret:
        raise BadRequestException(
            "EMBED_CLIENT_ID and EMBED_CLIENT_SECRET are not configured"
        )
    if settings.embed_agent_id < 1 or not (origin or settings.embed_origin):
        raise BadRequestException(
            "EMBED_AGENT_ID and EMBED_ORIGIN are not configured"
        )

    embed_repo = EmbedRepository(session)
    client = await embed_repo.get_client_by_id(settings.embed_client_id)
    if client is None:
        raise NotFoundException("configured embed client not found")

    redis = Redis.from_url(settings.celery_broker_url) if settings.quota_enabled else None
    try:
        token = await issue_embed_token(
            embed_repo,
            AgentRepository(session),
            EmbedTokenRequest(
                client_id=settings.embed_client_id,
                client_secret=settings.embed_client_secret,
                agent_id=settings.embed_agent_id,
                external_user_id=external_user_id,
                display_name=display_name,
                origin=(origin or settings.embed_origin),
                host_tool_names=host_tool_names,
            ),
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
    return success_response(data=token, message="agent token issued")
