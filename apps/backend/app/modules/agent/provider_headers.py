"""上游模型供应商的请求头兼容构造。

单一职责：判定端点是否属于 OpenCode，并按上游要求构造客户端标识与会话头。
非 OpenCode 端点一律不注入额外头，保证既有供应商（DeepSeek、中转站等）的
请求头与引入本模块之前完全一致。

上游依据（OpenCode Go 文档 "Where can I use it?"）：客户端需要用自己的
User-Agent 标识自己，并在 ``x-opencode-session`` 里为每个会话发送稳定的
session ID，用于优化路由与 prompt 缓存；缺失该头只会降级为
``cannot be routed efficiently``，不是鉴权失败。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 必须精确匹配主机名：子串匹配会把伪造域名或文档链接这类 base_url 误判为 OpenCode。
OPENCODE_HOST = "opencode.ai"
OPENCODE_CLIENT_TAG = "ai-base"
OPENCODE_USER_AGENT = f"{OPENCODE_CLIENT_TAG}/1.0"
OPENCODE_SESSION_HEADER = "x-opencode-session"

# 会话 id 由调用方以无参可调用对象提供，在真正发请求时求值；这样「创建新会话」
# 的第一轮也能取到本轮内刚创建的真实会话 id，而不是退回占位值。
SessionIdProvider = Callable[[], Any]


def is_opencode_endpoint(base_url: str | None) -> bool:
    """判断 base_url 是否指向 OpenCode 服务。"""

    if not base_url:
        return False
    try:
        return urlparse(base_url).hostname == OPENCODE_HOST
    except ValueError:
        return False


def merge_default_headers(
    base_url: str | None,
    configured: Mapping[str, str] | None,
) -> dict[str, str] | None:
    """合并静态请求头：OpenCode 端点补客户端标识与自有 UA，其他端点原样透传。

    ``configured`` 来自模型配置的 ``default_headers``，同名键优先，允许使用者
    覆盖默认值。返回 ``None`` 表示不设置任何请求头，与未启用本功能时一致。
    """

    if not is_opencode_endpoint(base_url):
        return dict(configured) if configured else None
    headers: dict[str, str] = {
        # 必须使用精确大小写 User-Agent：写成小写时 OpenAI SDK 会把它与自带的
        # "OpenAI/Python x.y.z" 合并成一个逗号拼接值，反而仍然带着通用 SDK 名。
        "User-Agent": OPENCODE_USER_AGENT,
        "x-opencode-client": OPENCODE_CLIENT_TAG,
    }
    if configured:
        headers.update(configured)
    return headers


def resolve_session_id(provider: SessionIdProvider | None) -> str | None:
    """安全求值会话 id；provider 缺失、抛异常或返回空值时统一返回 None。

    provider 异常不应中断对话，只记录日志并退化为「本次不发送会话头」。
    """

    if provider is None:
        return None
    try:
        value = provider()
    except Exception:
        logger.exception(
            "OpenCode 会话 id 求值失败，本次不发送 %s", OPENCODE_SESSION_HEADER
        )
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def session_headers(
    base_url: str | None,
    session_id: str | None,
    *,
    configured: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """构造按次发送的会话头；非 OpenCode 端点、无会话 id 或已显式配置时返回空字典。

    显式配置优先：若模型配置里已经写了 ``x-opencode-session``，说明使用者有意固定
    该值，此时不再覆盖，避免出现「配置被静默改掉」的意外行为。
    """

    if not is_opencode_endpoint(base_url) or not session_id:
        return {}
    if configured and any(key.lower() == OPENCODE_SESSION_HEADER for key in configured):
        return {}
    return {OPENCODE_SESSION_HEADER: session_id}
