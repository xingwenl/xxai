"""店铺运营平台（hua8）智能体会话接口：注入店铺 token 并签发 embed token。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.modules.embed.schemas import EmbedTokenResponse
from app.modules.embed.security import decode_embed_token
from app.modules.embed.services import issue_configured_agent_token
from app.modules.shop_agent.schemas import ShopAgentSessionRequest
from app.modules.shop_agent.services import store_shop_context, verify_shop_token
from app.shared.exceptions import BadRequestException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["shop-agent"])

# 本项目固定使用的 Embed Client：凭证只留在服务端，桌面端与浏览器都拿不到 client_secret。
# 留空则回退到 EMBED_CLIENT_* / EMBED_AGENT_ID / EMBED_ORIGIN 环境配置。
# 接入新项目时新增一组同名前缀的常量与独立接口方法，避免项目之间互相影响。
PROJECT_EMBED_CLIENT_ID = "client_5dG0kbQ0HoyrxrbRdsnP_GNr"
PROJECT_EMBED_CLIENT_SECRET = "lIi_fNg-RC635z-uBu1D3djvYojkMMkh4XYhGQ5YHBg"
PROJECT_EMBED_AGENT_ID = 35
PROJECT_EMBED_ORIGIN = "http://127.0.0.1:5390"


@router.post("/shop-agent/session", response_model=ApiResponse[EmbedTokenResponse])
async def create_shop_agent_session(
    payload: ShopAgentSessionRequest,
    origin: str | None = Query(default=None, max_length=500),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[EmbedTokenResponse]:
    """浏览器登录店铺系统后，把店铺 token 注入 ai-base 会话并签发 SDK token。

    - 先用店铺系统用户信息接口校验 shopToken 与 shopUserId 一致（防伪造）；
    - 可选指定 agentId 与 hostToolNames：前者支持同一 Client 下按调用方选择 Agent，
      后者是页面宿主工具的候选集合，最终范围由 Embed Client 绑定工具决定；
    - 可选携带调用方自己的 clientId / clientSecret：便于一个部署接入多个 Embed Client，
      两者必须同时提供并显式给出 agentId 与 origin；
    - 优先顺序为「请求携带的凭证 > PROJECT_EMBED_* 常量 > 环境变量配置」，
      因此项目固定的 Client 不需要下发到任何客户端；
    - 再把店铺 token 写入 Redis（TTL 跟随店铺系统登录时效），
      业务工具执行时按 embed 终端用户读取；
    - 最后复用服务端 Embed 配置签发短期 access_token 返回给前端。
    """
    settings = get_settings()
    if not settings.store_ops_base_url:
        raise BadRequestException("STORE_OPS_BASE_URL is not configured")
    client_id = payload.client_id or PROJECT_EMBED_CLIENT_ID or None
    client_secret = payload.client_secret or PROJECT_EMBED_CLIENT_SECRET or None
    agent_id = (
        payload.agent_id
        if payload.agent_id is not None
        else (PROJECT_EMBED_AGENT_ID or None)
    )
    effective_origin = origin or PROJECT_EMBED_ORIGIN or None
    # 固定 Client 必须连同 Agent 与来源一起给全，否则会退回到默认 Agent / 默认来源，
    # 报出「agent is not allowed for client」「origin is not allowed」这类难以定位的错误。
    if client_id is not None and (agent_id is None or not effective_origin):
        raise BadRequestException(
            "使用项目固定的 Embed Client 时必须同时配置 Agent 与来源"
        )
    display_name = await verify_shop_token(
        settings.store_ops_base_url, payload.shop_token, payload.shop_user_id
    )
    token = await issue_configured_agent_token(
        session,
        external_user_id=payload.shop_user_id,
        display_name=display_name,
        origin=effective_origin,
        host_tool_names=payload.host_tool_names,
        agent_id=agent_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    await session.commit()
    claims = decode_embed_token(token.access_token)
    await store_shop_context(
        int(claims["sub"]), payload.shop_token, payload.shop_user_id
    )
    return success_response(data=token, message="shop agent session issued")
