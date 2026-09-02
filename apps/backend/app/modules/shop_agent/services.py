"""店铺运营平台（hua8）智能体会话：token 校验与 Redis 注入。"""

from __future__ import annotations

import json

import httpx
from redis.asyncio import Redis

from app.core.config import get_settings
from app.shared.exceptions import UnauthorizedException


async def verify_shop_token(
    base_url: str, shop_token: str, shop_user_id: str
) -> str | None:
    """用店铺系统用户信息接口校验 token 与用户 ID，返回显示名（nickName）。

    校验失败（token 失效、用户不匹配、接口不可达）抛出 UnauthorizedException，
    避免浏览器伪造 shopUserId 获取其他用户的会话。
    """
    url = base_url.rstrip("/") + "/hua8-api/system/user/getInfo"
    try:
        async with httpx.AsyncClient(
            timeout=get_settings().store_ops_http_timeout_seconds
        ) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {shop_token}"}
            )
    except httpx.HTTPError as exc:
        raise UnauthorizedException("店铺系统不可达，请稍后重试") from exc
    if response.status_code != 200:
        raise UnauthorizedException(
            f"店铺系统校验失败（HTTP {response.status_code}），请重新登录"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise UnauthorizedException("店铺系统校验失败：响应格式异常") from exc
    user = (body or {}).get("user") if isinstance(body, dict) else None
    user_id = user.get("userId") if isinstance(user, dict) else None
    if not isinstance(body, dict) or body.get("code") != 200 or user_id is None:
        raise UnauthorizedException("店铺系统校验失败：登录状态无效，请重新登录")
    if str(user_id) != str(shop_user_id):
        raise UnauthorizedException("店铺系统用户不匹配，请重新登录")
    nick_name = user.get("nickName")
    return str(nick_name).strip() if nick_name else None


async def store_shop_context(
    end_user_id: int, shop_token: str, shop_user_id: str
) -> None:
    """把店铺会话写入 Redis，TTL 跟随店铺系统登录时效（默认 43200 秒）。"""
    settings = get_settings()
    redis = Redis.from_url(settings.celery_broker_url)
    try:
        await redis.set(
            f"shop-agent:end-user:{end_user_id}",
            json.dumps(
                {"shop_token": shop_token, "shop_user_id": shop_user_id},
                ensure_ascii=False,
            ),
            ex=settings.store_ops_redis_ttl_seconds,
        )
    finally:
        await redis.aclose()
