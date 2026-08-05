import secrets

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.modules.agent.repositories import AgentRepository
from app.modules.embed.repositories import EmbedRepository
from app.modules.embed.schemas import (
    EmbedTokenRequest,
    EmbedTokenResponse,
    PlatformEmbedClientCreate,
    PlatformEmbedClientCreated,
    PlatformEmbedClientUpdate,
)
from app.modules.embed.security import create_embed_token
from app.modules.observability.metrics import record_quota_rejection
from app.modules.quota.service import QuotaDimensions, QuotaService, RedisQuotaStore
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)


async def create_embed_client(
    repo, *, platform_id: int, payload: PlatformEmbedClientCreate
):
    client_id = f"client_{secrets.token_urlsafe(18)}"
    client_secret = secrets.token_urlsafe(32)
    client = await repo.create_client(
        platform_id=platform_id,
        client_id=client_id,
        name=payload.name,
        secret_hash=hash_password(client_secret),
        allowed_origins=payload.allowed_origins,
        token_ttl_seconds=payload.token_ttl_seconds,
        max_tokens_per_minute=payload.max_tokens_per_minute,
        max_connections=payload.max_connections,
    )
    return PlatformEmbedClientCreated(client=client, client_secret=client_secret)


async def issue_embed_token(
    embed_repo,
    agent_repo,
    request: EmbedTokenRequest,
    *,
    platform_id: int,
    quota_service=None,
):
    client = await embed_repo.get_client(platform_id, request.client_id)
    if (
        client is None
        or not client.is_active
        or not verify_password(request.client_secret, client.secret_hash)
    ):
        raise UnauthorizedException("invalid embed client credentials")
    if request.origin.rstrip("/") not in client.allowed_origins:
        raise UnauthorizedException("origin is not allowed")
    if not await embed_repo.is_agent_allowed(client.id, request.agent_id):
        raise UnauthorizedException("agent is not allowed for client")
    agent = await agent_repo.get_agent(request.agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    if quota_service is not None:
        decision = await quota_service.check(
            "token_issue",
            QuotaDimensions(
                platform_id=str(platform_id),
                client_id=client.client_id,
                agent_id=str(request.agent_id),
            ),
        )
        if not decision.allowed:
            record_quota_rejection("token_issue", decision.code)
            raise TooManyRequestsException(decision.code)
    end_user = await embed_repo.get_end_user(platform_id, request.external_user_id)
    if end_user is None:
        end_user = await embed_repo.create_end_user(
            platform_id, request.external_user_id, request.display_name
        )
    list_client_tool_names = getattr(embed_repo, "list_client_tool_names", None)
    client_tool_names = (
        await list_client_tool_names(client.id)
        if list_client_tool_names is not None
        else set()
    )
    token, jti = create_embed_token(
        subject=str(end_user.id),
        platform_id=platform_id,
        agent_id=request.agent_id,
        client_id=client.client_id,
        origin=request.origin.rstrip("/"),
        expires_in=client.token_ttl_seconds,
        host_tools=sorted(set(request.host_tool_names) & client_tool_names),
        temporary_tools=client.allow_temporary_tools,
    )
    return EmbedTokenResponse(
        access_token=token, expires_in=client.token_ttl_seconds, jti=jti
    )


async def issue_configured_agent_token(
    session,
    *,
    external_user_id: str,
    display_name: str | None = None,
    origin: str | None = None,
    host_tool_names: list[str] | None = None,
):
    """使用服务端 Embed 配置为受信任业务入口签发短期 Agent token。

    浏览器只携带后台登录态，Embed Client secret 和默认 Agent 配置始终留在服务端。
    """
    settings = get_settings()
    if not settings.embed_client_id or not settings.embed_client_secret:
        raise BadRequestException(
            "EMBED_CLIENT_ID and EMBED_CLIENT_SECRET are not configured"
        )
    if settings.embed_agent_id < 1 or not (origin or settings.embed_origin):
        raise BadRequestException("EMBED_AGENT_ID and EMBED_ORIGIN are not configured")

    embed_repo = EmbedRepository(session)
    client = await embed_repo.get_client_by_id(settings.embed_client_id)
    if client is None:
        raise NotFoundException("configured embed client not found")

    redis = (
        Redis.from_url(settings.celery_broker_url) if settings.quota_enabled else None
    )
    try:
        return await issue_embed_token(
            embed_repo,
            AgentRepository(session),
            EmbedTokenRequest(
                client_id=settings.embed_client_id,
                client_secret=settings.embed_client_secret,
                agent_id=settings.embed_agent_id,
                external_user_id=external_user_id,
                display_name=display_name,
                origin=(origin or settings.embed_origin),
                host_tool_names=host_tool_names or [],
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


def build_token_quota_service(client, settings, redis):
    """按 Client 配置建立 token 签发窗口；未配置时回退到全局默认值。"""
    limit = client.max_tokens_per_minute or settings.quota_token_issue_limit
    return QuotaService(
        RedisQuotaStore(redis),
        limits={"token_issue": limit},
        window_seconds={"token_issue": settings.quota_window_seconds},
    )


async def update_embed_client(
    repo, *, platform_id: int, client_id: str, payload: PlatformEmbedClientUpdate
):
    client = await repo.get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    return await repo.update_client(client, payload.model_dump(exclude_unset=True))


async def rotate_embed_client_secret(repo, *, platform_id: int, client_id: str):
    client = await repo.get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    secret = secrets.token_urlsafe(32)
    await repo.rotate_secret(client, hash_password(secret))
    return secret


async def bind_embed_client_agent(
    repo, agent_repo, *, platform_id: int, client_id: str, agent_id: int
):
    client = await repo.get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    agent = await agent_repo.get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    if await repo.is_agent_allowed(client.id, agent_id):
        raise ConflictException("agent already bound")
    return await repo.bind_agent(client.id, agent_id)


async def unbind_embed_client_agent(
    repo, *, platform_id: int, client_id: str, agent_id: int
):
    client = await repo.get_client(platform_id, client_id)
    if client is None:
        raise NotFoundException("embed client not found")
    await repo.unbind_agent(client.id, agent_id)


async def get_embed_message_snapshot(repo, *, conversation_id: int, claims: dict):
    messages = await repo.list_messages_for_principal(
        conversation_id,
        int(claims["platform_id"]),
        end_user_id=int(claims["sub"]),
    )
    if messages is None:
        raise NotFoundException("conversation not found")
    # 兼容轻量仓储替身和旧读取实现；真实仓储会返回完整内容块与 Loop 投影。
    if not hasattr(repo, "list_loops"):
        return messages
    loops = await repo.list_loops(conversation_id)
    loop_payloads = {}
    for loop in loops:
        steps = await repo.list_loop_steps(loop.id)
        loop_payloads[loop.assistant_message_id] = {
            "id": str(loop.id),
            "requestId": loop.request_id,
            "status": loop.status,
            "summary": loop.summary,
            "steps": [
                {
                    "id": str(step.id),
                    "sequence": step.sequence,
                    "stepType": step.step_type,
                    "title": step.title,
                    "status": step.status,
                    "outputSummary": step.output_summary,
                    "toolName": step.tool_name,
                    "skillName": step.skill_name,
                    "citationRefs": step.citation_refs,
                    "error": step.error,
                }
                for step in steps
            ],
        }
    return [
        {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "status": message.status,
            "content_blocks": message.content_blocks,
            "citations": message.citations,
            "knowledge_grounded": message.knowledge_grounded,
            "tool_call_id": message.tool_call_id,
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "loop": loop_payloads.get(message.id),
        }
        for message in messages
    ]
