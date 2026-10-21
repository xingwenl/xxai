"""嵌入会话的记忆主体与索引行注入。

两个关键口径必须一致：**写入**（内置工具）与**读取**（系统提示的「已有 N 条」）
用同一个主体，否则会出现「提示说有记忆、工具查出来 0 条」的错位。
"""

import asyncio
from types import SimpleNamespace

from app.modules.gateway.runtime import (
    load_embed_memory_index,
    resolve_embed_memory_principal,
)


def test_trusted_entry_session_uses_backend_user_principal() -> None:
    """带 user_id claim 的会话记忆归后台用户，管理台「我的记忆」可见。"""

    principal = resolve_embed_memory_principal(
        platform_id=1, user_id=7, client_id="client-a", end_user_id=65
    )
    assert principal is not None
    assert principal.kind == "user"
    assert principal.user_id == 7


def test_public_entry_session_uses_client_scoped_end_user() -> None:
    """公开入口没有后台用户，按 (client_id, end_user_id) 隔离。"""

    principal = resolve_embed_memory_principal(
        platform_id=1, user_id=None, client_id="client-a", end_user_id=65
    )
    assert principal is not None
    assert principal.kind == "end_user"
    assert (principal.client_id, principal.end_user_id) == ("client-a", 65)


def test_session_without_any_principal_gets_no_memory_index() -> None:
    """没有主体（旧 token 缺 claim）时不注入索引，也不报错。"""

    assert (
        resolve_embed_memory_principal(
            platform_id=1, user_id=None, client_id=None, end_user_id=65
        )
        is None
    )

    async def run() -> None:
        assert (
            await load_embed_memory_index(SimpleNamespace(session=None), None) is None
        )

    asyncio.run(run())
