"""Embed WebSocket 的认证和协议入口校验。"""

from app.modules.embed.security import EmbedTokenRevocationStore, decode_embed_token
from app.shared.exceptions import UnauthorizedException

PROTOCOL_SUBPROTOCOL = "ai-agent.v1"
SUPPORTED_PROTOCOL_VERSION = 1
SERVER_VERSION = "0.1.0"
MINIMUM_SDK_VERSION = "0.1.0"
CAPABILITIES = frozenset({"replay", "host_tools", "cancellation"})


class CompatibilityResult:
    def __init__(self, allowed: bool, code: str = "compatible"):
        self.allowed = allowed
        self.code = code
        self.retryable = False


def _version_tuple(version: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in version.split(".")[:3])
    except (AttributeError, ValueError):
        return (-1, -1, -1)
    return (parts + (0, 0, 0))[:3]


def check_client_compatibility(
    *, protocol_version: int, sdk_version: str
) -> CompatibilityResult:
    if protocol_version != SUPPORTED_PROTOCOL_VERSION:
        return CompatibilityResult(False, "unsupported_protocol_version")
    if _version_tuple(sdk_version) < _version_tuple(MINIMUM_SDK_VERSION):
        return CompatibilityResult(False, "unsupported_sdk_version")
    return CompatibilityResult(True)


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
