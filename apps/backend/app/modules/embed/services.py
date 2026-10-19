import secrets

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.modules.agent.repositories import AgentRepository
from app.modules.conversation.serializers import (
    build_message_snapshots,
    conversation_preview,
)
from app.modules.embed.repositories import EmbedRepository
from app.modules.embed.schemas import (
    EmbedConversationPage,
    EmbedConversationRead,
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
    agent_id: int | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
):
    """使用服务端 Embed 配置为受信任业务入口签发短期 Agent token。

    浏览器只携带后台登录态，Embed Client secret 和默认 Agent 配置始终留在服务端。
    ``agent_id`` 缺省时使用服务端配置的默认 Agent；显式传入时仍必须通过
    Embed Client 的 Agent 绑定校验（见 ``issue_embed_token``），调用方无法越权
    指定未绑定到该 Client 的 Agent。

    调用方也可以携带自己的 Embed Client 凭证（``client_id`` + ``client_secret``），
    用于一个部署接入多个 Embed Client。这两个值共同构成凭证，必须同时提供；
    由于它们等同于签发权限，只能由服务端持有，不能下发给浏览器或客户端。
    此时必须显式给出 ``agent_id`` 与 ``origin``，避免默认 Agent 或默认来源与
    目标 Client 不匹配而拿到难以理解的报错。
    """
    settings = get_settings()
    if (client_id is None) != (client_secret is None):
        raise BadRequestException("client_id 与 client_secret 必须同时提供")
    effective_client_id = client_id or settings.embed_client_id
    effective_client_secret = client_secret or settings.embed_client_secret
    if not effective_client_id or not effective_client_secret:
        raise BadRequestException(
            "EMBED_CLIENT_ID and EMBED_CLIENT_SECRET are not configured"
        )
    if client_id is not None:
        if agent_id is None:
            raise BadRequestException("携带 client_id 时必须显式指定 agent_id")
        if not origin:
            raise BadRequestException("携带 client_id 时必须显式指定 origin")
    target_agent_id = agent_id if agent_id is not None else settings.embed_agent_id
    if target_agent_id < 1 or not (origin or settings.embed_origin):
        raise BadRequestException("EMBED_AGENT_ID and EMBED_ORIGIN are not configured")

    embed_repo = EmbedRepository(session)
    client = await embed_repo.get_client_by_id(effective_client_id)
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
                client_id=effective_client_id,
                client_secret=effective_client_secret,
                agent_id=target_agent_id,
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
    """embed 主体视角的消息快照。

    投影构造与后台会话记录接口共用 `build_message_snapshots`，两处返回逐字段
    相同，前端也就能用同一套渲染组件。
    """
    messages = await repo.list_messages_for_principal(
        conversation_id,
        int(claims["platform_id"]),
        end_user_id=int(claims["sub"]),
    )
    if messages is None:
        raise NotFoundException("conversation not found")
    return await build_message_snapshots(
        repo, conversation_id=conversation_id, messages=messages
    )


async def list_embed_conversations(
    repo,
    *,
    claims: dict,
    page: int = 1,
    page_size: int = 20,
) -> EmbedConversationPage:
    """列出 embed token 主体在指定 Agent 下的会话。

    隔离条件完全取自 token claim：平台、最终用户与 Agent 都不可由调用方
    指定，避免通过改参数枚举他人会话。
    """
    platform_id = int(claims["platform_id"])
    agent_id = int(claims["agent_id"])
    end_user_id = int(claims["sub"])
    rows = await repo.list_for_principal(
        platform_id,
        agent_id,
        end_user_id=end_user_id,
        page=page,
        page_size=page_size,
    )
    total = await repo.count_for_principal(
        platform_id, agent_id, end_user_id=end_user_id
    )
    return EmbedConversationPage(
        items=[
            EmbedConversationRead(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                message_count=message_count,
                last_message_preview=conversation_preview(preview),
            )
            for conversation, message_count, preview in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def soft_delete_embed_conversation(repo, *, conversation_id: int, claims: dict):
    """软删除本主体的会话；非本主体或已删除一律按不存在处理。

    返回 404 而非 403 是有意为之：与消息快照接口保持一致，不向调用方
    泄露「这个会话 ID 存在但不属于你」。
    """
    deleted = await repo.soft_delete_for_principal(
        conversation_id,
        int(claims["platform_id"]),
        end_user_id=int(claims["sub"]),
    )
    if not deleted:
        raise NotFoundException("conversation not found")
    return None


async def compact_embed_conversation(
    repo,
    *,
    session,
    conversation_id: int,
    claims: dict,
    instructions: str | None = None,
) -> dict:
    """手动压缩本主体某个会话的模型上下文，返回压缩结果投影。

    这是 ``POST /embed/conversations/{id}/context/compact`` 的业务实现。压缩
    本身（切点、摘要、落库）全在 conversation 模块的 ``compact_conversation``
    里，这里只做三件入口该做的事：按 token claim 校验会话归属、解析该 Agent
    当前生效的对话模型、把结果翻译成 REST 投影。

    幂等：没有新的可压缩内容时返回 ``compacted=False`` 与 ``nothing_to_compact``，
    不写库、不报错——客户端重复点击「压缩」按钮不应该看到错误。
    """

    # 延迟导入：conversation 模块在模块层依赖 agent/model_registry，顶层静态
    # 导入会把 embed 拖进更长的初始化链，也无谓地扩大了模块环的范围。
    from app.modules.agent.services import build_chat_model
    from app.modules.conversation.compaction import compact_conversation
    from app.modules.conversation.runtime import resolve_context_window_tokens
    from app.modules.model_registry.resolver import resolve_chat_model

    platform_id = int(claims["platform_id"])
    end_user_id = int(claims["sub"])
    conversation = await repo.get_for_principal(
        conversation_id, platform_id, end_user_id=end_user_id
    )
    if conversation is None:
        raise NotFoundException("conversation not found")

    agent = await AgentRepository(session).get_published_agent(
        conversation.agent_id, platform_id
    )
    version = agent.default_version if agent is not None else None
    if version is None:
        # 会话所属 Agent 已下架或没有版本：宁可报「不可压缩」，也不要凭空
        # 造一个没有版本参数的模型客户端去发摘要请求。
        raise NotFoundException("agent version not found")

    resolved = await resolve_chat_model(
        session, platform_id=platform_id, agent_id=conversation.agent_id
    )
    model = build_chat_model(
        version,
        resolved=resolved,
        session_id_provider=lambda: conversation_id,
    )
    window_tokens = resolve_context_window_tokens(
        version, model_name=getattr(model, "model_name", None)
    )
    outcome = await compact_conversation(
        repo=repo,
        conversation_id=conversation_id,
        model=model,
        trigger="manual",
        instructions=instructions,
        window_tokens=window_tokens,
    )
    return outcome.as_rest()
