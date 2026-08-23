"""微信机器人会话状态持久化单元测试（不依赖真实 SDK）。"""

import asyncio
from pathlib import Path

from app.modules.wechat_bot.session import (
    WeChatBotSession,
    install_cursor_persistence,
)


def test_cursor_roundtrip(tmp_path: Path) -> None:
    session = WeChatBotSession(tmp_path)
    assert session.cursor == ""
    asyncio.run(session.save_cursor("cursor-1"))
    reloaded = WeChatBotSession(tmp_path)
    assert reloaded.cursor == "cursor-1"


def test_corrupted_state_falls_back_to_empty(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text("{broken", encoding="utf-8")
    session = WeChatBotSession(tmp_path)
    assert session.cursor == ""


def test_install_cursor_persistence_saves_cursor(tmp_path: Path) -> None:
    class _FakeApi:
        def __init__(self) -> None:
            self.calls = 0

        async def get_updates(self, *args, **kwargs):
            self.calls += 1
            return {"get_updates_buf": f"buf-{self.calls}"}

    class _FakeBot:
        def __init__(self) -> None:
            self._api = _FakeApi()

    session = WeChatBotSession(tmp_path)
    bot = _FakeBot()
    install_cursor_persistence(bot, session)

    asyncio.run(bot._api.get_updates(None, None, ""))
    assert session.cursor == "buf-1"


def test_conversation_mapping_roundtrip(tmp_path: Path) -> None:
    session = WeChatBotSession(tmp_path)
    assert session.get_conversation_id("wx-user-1") is None
    asyncio.run(session.save_conversation_id("wx-user-1", 42))
    reloaded = WeChatBotSession(tmp_path)
    assert reloaded.get_conversation_id("wx-user-1") == 42
    # 不同用户互不影响
    assert reloaded.get_conversation_id("wx-user-2") is None


def test_conversation_mapping_clear(tmp_path: Path) -> None:
    session = WeChatBotSession(tmp_path)
    asyncio.run(session.save_conversation_id("wx-user-1", 42))
    asyncio.run(session.clear_conversation_id("wx-user-1"))
    reloaded = WeChatBotSession(tmp_path)
    assert reloaded.get_conversation_id("wx-user-1") is None


def test_cursor_and_conversation_share_state_file(tmp_path: Path) -> None:
    session = WeChatBotSession(tmp_path)
    asyncio.run(session.save_cursor("cursor-9"))
    asyncio.run(session.save_conversation_id("wx-user-1", 42))
    reloaded = WeChatBotSession(tmp_path)
    assert reloaded.cursor == "cursor-9"
    assert reloaded.get_conversation_id("wx-user-1") == 42
