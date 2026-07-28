import secrets

from app.core.security import hash_password, verify_password
from app.modules.embed.schemas import (
    EmbedTokenRequest,
    EmbedTokenResponse,
    PlatformEmbedClientCreate,
    PlatformEmbedClientCreated,
    PlatformEmbedClientUpdate,
)
from app.modules.embed.security import create_embed_token
from app.shared.exceptions import (
    ConflictException,
    NotFoundException,
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
    embed_repo, agent_repo, request: EmbedTokenRequest, *, platform_id: int
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
    )
    return EmbedTokenResponse(
        access_token=token, expires_in=client.token_ttl_seconds, jti=jti
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
    return messages
