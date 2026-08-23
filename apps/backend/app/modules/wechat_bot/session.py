"""微信机器人会话状态持久化。

- 登录凭据（bot_token / account_id 等）由 wechatbot-sdk 负责持久化到
  credentials.json（权限 0600），重启后可免扫码复用；
- 长轮询游标 get_updates_buf 由 SDK 保存在内存中，进程重启后会丢失，
  导致服务器重新下发已消费消息（重复回复），因此这里单独把游标写盘；
- 后台会话映射：每个微信用户（私聊联系人 / 群聊房间）对应一个后台
  conversation_id，聊天时携带该 id 以复用历史上下文；写入本地 state.json，
  进程重启后仍能延续上下文；
- 会话过期（errcode -14）时 SDK 会清除凭据并重新扫码，旧游标会在下一次
  轮询成功后被新游标覆盖，无需额外处理。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class WeChatBotSession:
    """持久化 wechat-bot-worker 的运行状态（长轮询游标 + 微信用户会话映射）。"""

    def __init__(self, state_dir: str | Path) -> None:
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / "state.json"
        # 状态文件是读-改-写整文件，异步并发下用锁保证原子性
        self._lock = asyncio.Lock()

    @property
    def cursor(self) -> str:
        data = self._load()
        return data.get("cursor", "")

    def get_conversation_id(self, user_id: str) -> int | None:
        """返回该微信用户的最近一次后台会话 id；无记录时返回 None。"""
        value = self._load().get("conversations", {}).get(user_id)
        if not isinstance(value, int) or value <= 0:
            return None
        return value

    async def save_cursor(self, cursor: str) -> None:
        async with self._lock:
            data = self._load()
            data["cursor"] = cursor
            self._write(data)

    async def save_conversation_id(self, user_id: str, conversation_id: int) -> None:
        """记录微信用户与后台会话的映射，后续消息复用同一会话。"""
        async with self._lock:
            data = self._load()
            data.setdefault("conversations", {})[user_id] = conversation_id
            self._write(data)

    async def clear_conversation_id(self, user_id: str) -> None:
        """会话失效（如后台删除/换智能体）时清除映射，下次自动新建会话。"""
        async with self._lock:
            data = self._load()
            conversations = data.get("conversations", {})
            if user_id in conversations:
                del conversations[user_id]
                self._write(data)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_file.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self._state_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def install_cursor_persistence(bot: Any, session: WeChatBotSession) -> None:
    """包装 SDK 长轮询接口，每次拿到新游标后写盘，重启时由调用方恢复。

    wechatbot-sdk 未提供游标持久化钩子，这里对其内部 get_updates 做包装；
    bot 类型标注为 Any，避免后端主依赖引入 wechatbot-sdk（仅 worker 镜像安装）。
    """
    original_get_updates = bot._api.get_updates

    async def get_updates_with_persist(*args: Any, **kwargs: Any) -> dict[str, Any]:
        updates = await original_get_updates(*args, **kwargs)
        buf = updates.get("get_updates_buf")
        if buf:
            await session.save_cursor(buf)
        return updates

    bot._api.get_updates = get_updates_with_persist
