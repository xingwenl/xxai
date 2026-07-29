"""Embed WebSocket 的认证和协议入口校验。"""

from app.modules.embed.security import EmbedTokenRevocationStore, decode_embed_token
from app.shared.exceptions import UnauthorizedException

PROTOCOL_SUBPROTOCOL = "ai-agent.v1"


def validate_handshake(
    origin: str | None, allowed_origins: list[str], subprotocols: list[str]
) -> bool:
    """校验握手阶段的来源和子协议。

    WebSocket 握手发生在 HTTP 鉴权之前，因此这里只做最早期的协议门禁：
    页面必须来自后台允许的 Origin，并且声明当前 SDK 支持的子协议。
    真正的身份、Agent 和 token 撤销校验由 ``authenticate_embed_token`` 完成。
    """
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
    """解码并校验 Embed token 的连接作用域。

    token 中的 ``agent_id`` 和 ``origin`` 是服务端签发时确定的约束，
    这里重新与当前 WebSocket 路径和请求头比对，防止页面自行修改
    Agent ID 或把一个页面的 token 用到另一个来源。可选的 revocation store
    用于在 token 尚未过期时立即撤销连接权限。
    """
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
