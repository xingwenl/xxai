from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from app.core.config import get_settings
from app.shared.exceptions import UnauthorizedException

embed_bearer_scheme = HTTPBearer(auto_error=False)


class EmbedTokenRevocationStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(jti: str) -> str:
        return f"agent:embed:revoked:{jti}"

    async def revoke(self, jti: str, expires_at: int) -> None:
        from time import time

        ttl = max(1, min(900, expires_at - int(time())))
        await self.redis.set(self._key(jti), "1", ex=ttl)

    async def is_revoked(self, jti: str) -> bool:
        return await self.redis.exists(self._key(jti)) == 1


def create_embed_token(
    *,
    subject: str,
    platform_id: int,
    agent_id: int,
    client_id: str,
    origin: str,
    expires_in: int,
    host_tools: list[str] | None = None,
    temporary_tools: bool = False,
    user_id: int | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    jti = str(uuid4())
    now = datetime.now(UTC)
    payload = {
        "iss": settings.embed_token_issuer,
        "aud": settings.embed_token_audience,
        "sub": subject,
        "platform_id": platform_id,
        "agent_id": agent_id,
        "client_id": client_id,
        "origin": origin,
        "host_tools": sorted(set(host_tools or [])),
        "temporary_tools": temporary_tools,
        "protocol_version": 1,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now.timestamp() + expires_in,
    }
    # 可选 claim：只有受信任入口（后台登录态）签发时才带，表示「这次会话代表
    # 哪位后台用户」。第三方公开入口不签这个字段，下游据此按终端用户隔离记忆。
    if user_id is not None:
        payload["user_id"] = int(user_id)
    return (
        jwt.encode(
            payload,
            settings.embed_jwt_secret_key,
            algorithm=settings.embed_jwt_algorithm,
        ),
        jti,
    )


def decode_embed_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.embed_jwt_secret_key,
            algorithms=[settings.embed_jwt_algorithm],
            issuer=settings.embed_token_issuer,
            audience=settings.embed_token_audience,
            options={
                "require": [
                    "sub",
                    "jti",
                    "exp",
                    "platform_id",
                    "agent_id",
                    "client_id",
                    "host_tools",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedException("invalid embed token") from exc
    if payload.get("protocol_version") != 1:
        raise UnauthorizedException("unsupported embed protocol")
    # user_id 决定记忆归属，必须是正整数；放行任意类型会让下游 int() 抛错或
    # 把布尔值当 ID，属于可控输入导致的行为漂移。
    if "user_id" in payload:
        user_id = payload["user_id"]
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise UnauthorizedException("invalid embed token")
    return payload


async def get_current_embed_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(embed_bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException("embed token required")
    return decode_embed_token(credentials.credentials)
