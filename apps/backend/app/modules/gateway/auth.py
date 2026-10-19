"""Embed WebSocket 的认证和协议入口校验。"""

from app.modules.embed.security import EmbedTokenRevocationStore, decode_embed_token
from app.shared.exceptions import UnauthorizedException

PROTOCOL_SUBPROTOCOL = "ai-agent.v1"
SUPPORTED_PROTOCOL_VERSION = 1
SERVER_VERSION = "0.1.0"
MINIMUM_SDK_VERSION = "0.1.0"


class CompatibilityResult:
    """协议与 SDK 版本协商结果。

    不兼容时 ``code`` 是会直接出站的稳定错误码，``details`` 让客户端能读到
    「服务端支持什么」，从而自行判断该升级到哪个版本。``retryable`` 恒为
    False：版本不匹配在同一个连接上重试不会自愈。
    """

    def __init__(
        self,
        allowed: bool,
        code: str = "compatible",
        details: dict[str, str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.code = code
        self.retryable = False
        self.details = details or {}


def compatibility_details() -> dict[str, str]:
    """服务端版本信息，随不兼容错误一并出站。"""

    return {
        "serverVersion": SERVER_VERSION,
        "minimumSdkVersion": MINIMUM_SDK_VERSION,
        "supportedProtocolVersion": str(SUPPORTED_PROTOCOL_VERSION),
    }


def _version_tuple(version: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in version.split(".")[:3])
    except (AttributeError, ValueError):
        return (-1, -1, -1)
    return (parts + (0, 0, 0))[:3]


def check_client_compatibility(
    *, protocol_version: int | None, sdk_version: str | None
) -> CompatibilityResult:
    """校验客户端声明的协议主版本与 SDK 版本。

    缺失字段按不兼容处理。早期实现用 ``auth_payload.get("protocolVersion", 1)``
    这类默认值取参，会让「客户端根本没声明版本」被当成「声明了兼容版本」放行，
    等于把版本协商这道门禁关掉，因此这里对 ``None`` 与非整型一律拒绝。
    """

    if (
        not isinstance(protocol_version, int)
        or isinstance(protocol_version, bool)
        or protocol_version != SUPPORTED_PROTOCOL_VERSION
    ):
        return CompatibilityResult(
            False, "unsupported_protocol_version", compatibility_details()
        )
    if not isinstance(sdk_version, str) or _version_tuple(sdk_version) < _version_tuple(
        MINIMUM_SDK_VERSION
    ):
        return CompatibilityResult(
            False, "unsupported_sdk_version", compatibility_details()
        )
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
