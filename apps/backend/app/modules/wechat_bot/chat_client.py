"""微信消息经后台 chat 接口转发客户端。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class ConversationNotFoundError(Exception):
    """携带的 conversation_id 已不存在（如后台删除会话或切换智能体）。"""


@dataclass(frozen=True)
class ChatReply:
    content: str
    conversation_id: int | None


class WeChatChatClient:
    """以绑定用户的服务 token 调用 /api/v1/agents/{agent_id}/chat 获取纯文本回复。"""

    def __init__(self, api_base_url: str, *, timeout: float = 120.0) -> None:
        self._base_url = api_base_url.rstrip("/")
        self._timeout = timeout

    async def send_chat(
        self,
        *,
        api_token: str,
        agent_id: int,
        message: str,
        conversation_id: int | None = None,
    ) -> ChatReply:
        url = f"{self._base_url}/api/v1/agents/{agent_id}/chat"
        headers = {"Authorization": f"Bearer {api_token}"}
        payload = {"message": message, "stream": False}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 404:
                    raise ConversationNotFoundError(
                        f"conversation {conversation_id} not found for agent {agent_id}"
                    )
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            if isinstance(exc, ConversationNotFoundError):
                logger.warning("wechat chat conversation invalid agent_id=%s err=%s", agent_id, exc)
            else:
                logger.error("wechat chat api call failed agent_id=%s err=%s", agent_id, exc)
            raise

        data = (body or {}).get("data") or {}
        content = (data.get("content") or "").strip()
        conversation_id = data.get("conversation_id") or conversation_id
        if not content:
            logger.warning("wechat chat api returned empty content agent_id=%s", agent_id)
            return ChatReply(
                content="抱歉，我没有生成有效回答，请稍后再试。",
                conversation_id=conversation_id,
            )
        return ChatReply(content=content, conversation_id=conversation_id)
