from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.database import get_db_session
from app.modules.user.repositories import UserRepository
from app.shared.exceptions import UnauthorizedException


bearer_scheme = HTTPBearer(auto_error=False)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )
    return f"scrypt${_b64url_encode(salt)}${_b64url_encode(derived_key)}"


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        algorithm, salt_b64, key_b64 = hashed_password.split("$", 2)
    except ValueError:
        return False

    if algorithm != "scrypt":
        return False

    salt = _b64url_decode(salt_b64)
    expected_key = _b64url_decode(key_b64)
    actual_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=len(expected_key),
    )
    return hmac.compare_digest(actual_key, expected_key)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    if settings.jwt_algorithm != "HS256":
        raise ValueError("unsupported jwt algorithm")

    expire_at = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    payload = {"sub": subject, "exp": int(expire_at.timestamp())}
    signing_input = ".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if settings.jwt_algorithm != "HS256":
        raise UnauthorizedException("invalid token")

    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise UnauthorizedException("invalid token") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise UnauthorizedException("invalid token")

    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (json.JSONDecodeError, ValueError) as exc:
        raise UnauthorizedException("invalid token") from exc

    subject = payload.get("sub")
    expire_at = payload.get("exp")
    if not isinstance(subject, str) or not isinstance(expire_at, int):
        raise UnauthorizedException("invalid token")

    if expire_at < int(datetime.now(UTC).timestamp()):
        raise UnauthorizedException("token expired")

    return payload


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session=Depends(get_db_session),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException("not authenticated")

    payload = decode_access_token(credentials.credentials)
    subject = payload["sub"]
    if not subject.isdigit():
        raise UnauthorizedException("invalid token")

    repo = UserRepository(session)
    user = await repo.get_by_id(int(subject))
    if user is None:
        raise UnauthorizedException("user not found")
    return user


async def get_current_user_or_wechat_service(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session=Depends(get_db_session),
):
    """优先解析用户 JWT；否则按微信助手服务 token 解析为绑定用户。

    微信 worker 持绑定记录签发的长期服务 token 调用对话接口时使用：
    token 命中 wechat_bot_bindings.api_token_hash 后，以绑定记录的 user_id
    作为当前用户，后续权限校验（如 get_published_agent_for_user）沿用原链路。
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException("not authenticated")

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if isinstance(subject, str) and subject.isdigit():
            repo = UserRepository(session)
            user = await repo.get_by_id(int(subject))
            if user is not None:
                return user
    except UnauthorizedException:
        pass

    from app.modules.wechat_bot.repositories import WeChatBotBindingRepository
    from app.modules.wechat_bot.services import hash_api_token

    binding = await WeChatBotBindingRepository(session).get_by_api_token_hash(
        hash_api_token(token)
    )
    if binding is not None:
        user = await UserRepository(session).get_by_id(binding.user_id)
        if user is not None:
            return user

    raise UnauthorizedException("not authenticated")


async def require_current_active_user(current_user=Depends(get_current_user)):
    if not current_user.is_active:
        raise UnauthorizedException("user is inactive")
    return current_user


async def require_current_active_user_or_wechat_service(
    current_user=Depends(get_current_user_or_wechat_service),
):
    if not current_user.is_active:
        raise UnauthorizedException("user is inactive")
    return current_user


def get_security_placeholder() -> dict[str, str]:
    return {
        "status": "reserved",
        "message": "security strategy will be defined in a dedicated request",
    }
