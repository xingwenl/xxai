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


@router.post("/shop-agent/session", response_model=ApiResponse[EmbedTokenResponse])
async def create_shop_agent_session(
    payload: ShopAgentSessionRequest,
    origin: str | None = Query(default=None, max_length=500),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[EmbedTokenResponse]:
    """浏览器登录店铺系统后，把店铺 token 注入 ai-base 会话并签发 SDK token。

    - 先用店铺系统用户信息接口校验 shopToken 与 shopUserId 一致（防伪造）；
    - 再把店铺 token 写入 Redis（TTL 跟随店铺系统登录时效），
      业务工具执行时按 embed 终端用户读取；
    - 最后复用服务端 Embed 配置签发短期 access_token 返回给前端。
    """
    settings = get_settings()
    if not settings.store_ops_base_url:
        raise BadRequestException("STORE_OPS_BASE_URL is not configured")
    display_name = await verify_shop_token(
        settings.store_ops_base_url, payload.shop_token, payload.shop_user_id
    )
    token = await issue_configured_agent_token(
        session,
        external_user_id=payload.shop_user_id,
        display_name=display_name,
        origin=origin,
    )
    await session.commit()
    claims = decode_embed_token(token.access_token)
    await store_shop_context(
        int(claims["sub"]), payload.shop_token, payload.shop_user_id
    )
    return success_response(data=token, message="shop agent session issued")
