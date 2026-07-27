from app.modules.embed.security import EmbedTokenRevocationStore, decode_embed_token
from app.shared.exceptions import UnauthorizedException

PROTOCOL_SUBPROTOCOL = "ai-agent.v1"


def validate_handshake(
    origin: str | None, allowed_origins: list[str], subprotocols: list[str]
) -> bool:
    return bool(
        origin
        and origin.rstrip("/") in allowed_origins
        and PROTOCOL_SUBPROTOCOL in subprotocols
    )


async def authenticate_embed_token(
    token: str,
    *,
    agent_id: int,
    origin: str,
    revocation_store: EmbedTokenRevocationStore | None = None,
):
    payload = decode_embed_token(token)
    if payload.get("agent_id") != agent_id or payload.get("origin") != origin.rstrip(
        "/"
    ):
        raise UnauthorizedException("embed token scope mismatch")
    if revocation_store is not None and await revocation_store.is_revoked(
        payload["jti"]
    ):
        raise UnauthorizedException("embed token revoked")
    return payload
