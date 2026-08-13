import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.modules.embed.security import create_embed_token
from app.modules.gateway.auth import (
    authenticate_embed_token,
)
from app.shared.exceptions import UnauthorizedException


def _token(*, agent_id=11, origin="https://app.acme.test"):
    token, _ = create_embed_token(
        subject="22",
        platform_id=7,
        agent_id=agent_id,
        client_id="client_acme",
        origin=origin,
        expires_in=600,
    )
    return token


def test_authentication_rejects_agent_or_origin_mismatch():
    async def run():
        with pytest.raises(UnauthorizedException):
            await authenticate_embed_token(
                _token(agent_id=12), agent_id=11, origin="https://app.acme.test"
            )
        with pytest.raises(UnauthorizedException):
            await authenticate_embed_token(
                _token(), agent_id=11, origin="https://other.acme.test"
            )

    asyncio.run(run())


def test_authentication_rejects_revoked_token_and_wrong_audience():
    async def run():
        class Revoked:
            async def is_revoked(self, _jti):
                return True

        with pytest.raises(UnauthorizedException):
            await authenticate_embed_token(
                _token(),
                agent_id=11,
                origin="https://app.acme.test",
                revocation_store=Revoked(),
            )

        settings = get_settings()
        bad = jwt.encode(
            {
                "iss": settings.embed_token_issuer,
                "aud": "wrong",
                "sub": "22",
                "platform_id": 7,
                "agent_id": 11,
                "client_id": "client_acme",
                "origin": "https://app.acme.test",
                "protocol_version": 1,
                "jti": "bad",
                "iat": datetime.now(UTC),
                "nbf": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            settings.embed_jwt_secret_key,
            algorithm=settings.embed_jwt_algorithm,
        )
        with pytest.raises(UnauthorizedException):
            await authenticate_embed_token(
                bad, agent_id=11, origin="https://app.acme.test"
            )

    asyncio.run(run())
