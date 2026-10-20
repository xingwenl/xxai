"""用户记忆的单元测试：写入判定、索引行、回显、检索，以及审批闸口的白名单直通。

这里的重点是「规则由代码执行」：白名单 key、敏感类别、无人值守拒绝这三件事
不能只写在提示词里，所以每条规则都有一处断言。数据库不参与测试——服务层只依赖
仓储的三个方法，用 Fake 替代即可。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.memory.services import (
    INFERRED_FACT_MAX_CHARS,
    SELF_SCOPED_WRITE_TOOLS,
    build_memory_index_line,
    format_remember_message,
    remember_memory,
    search_memory,
    truncate_payloads,
    validate_write,
)
from app.modules.tool_approval.contracts import ConfirmationDecision
from app.shared.exceptions import BadRequestException


# --------------------------------------------------------------------------- #
# 写入判定
# --------------------------------------------------------------------------- #


def test_inferred_allows_whitelisted_fact() -> None:
    kind, key = validate_write(kind="fact", key=" 城市 ", content="上海", mode="inferred")
    assert (kind, key) == ("fact", "城市")


def test_inferred_rejects_event() -> None:
    """经历只能显式写：写错了无法被下一条覆盖，会在时间线上留下假历史。"""

    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="event", key=None, content="昨天去了杭州", mode="inferred")
    assert excinfo.value.error_code == "memory_inferred_requires_fact"


def test_inferred_rejects_sensitive_content() -> None:
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="fact", key="城市", content="详细地址：某小区 3 栋 501", mode="inferred")
    assert excinfo.value.error_code == "memory_sensitive_requires_explicit"


def test_explicit_write_allows_sensitive_content() -> None:
    kind, key = validate_write(kind="fact", key="用药", content="每天一片", mode="explicit")
    assert (kind, key) == ("fact", "用药")


def test_inferred_rejects_key_outside_whitelist() -> None:
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="fact", key="车牌号", content="沪 A12345", mode="inferred")
    assert excinfo.value.error_code == "memory_key_not_allowed_for_inferred"


def test_inferred_rejects_overlong_fact() -> None:
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(
            kind="fact",
            key="长期项目",
            content="很长" * (INFERRED_FACT_MAX_CHARS // 2 + 1),
            mode="inferred",
        )
    assert excinfo.value.error_code == "memory_content_too_long"


def test_fact_requires_key_and_event_forbids_it() -> None:
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="fact", key=None, content="上海", mode="explicit")
    assert excinfo.value.error_code == "memory_key_required"


def test_blank_content_and_unknown_kind_are_rejected() -> None:
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="fact", key="城市", content="   ", mode="explicit")
    assert excinfo.value.error_code == "memory_empty"
    with pytest.raises(BadRequestException) as excinfo:
        validate_write(kind="note", key="城市", content="上海", mode="explicit")
    assert excinfo.value.error_code == "memory_kind_invalid"


# --------------------------------------------------------------------------- #
# 索引行与回显
# --------------------------------------------------------------------------- #


def test_index_line_reports_counts_without_any_memory_content() -> None:
    """唯一串断言：注入的是条数，不是事实值。"""

    line = build_memory_index_line(2, 1)
    assert "3 条个人记忆" in line
    assert "事实 2 条" in line and "经历 1 条" in line
    assert "memory_search" in line
    for leaked in ("上海", "李一", "北京"):
        assert leaked not in line


def test_index_line_for_empty_memory_says_nothing_saved() -> None:
    line = build_memory_index_line(0, 0)
    assert "还没有保存任何个人记忆" in line


def test_remember_message_shows_previous_value() -> None:
    message = format_remember_message(
        "fact",
        key="城市",
        content="上海",
        occurred_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        previous_content="北京",
    )
    assert "已记住：城市 = 上海" in message
    assert "原值：北京" in message


def test_truncate_payloads_drops_entries_over_budget() -> None:
    payloads = [{"content": "a" * 30}, {"content": "b" * 30}, {"content": "c" * 30}]
    kept = truncate_payloads(payloads, max_chars=70)
    assert [item["content"][0] for item in kept] == ["a", "b"]


# --------------------------------------------------------------------------- #
# 服务层：主体校验与覆盖语义
# --------------------------------------------------------------------------- #


class FakeMemoryRepository:
    """只实现服务层用到的方法的仓储替身。"""

    def __init__(self) -> None:
        self.facts: dict[str, SimpleNamespace] = {}
        self.events: list[SimpleNamespace] = []
        self._next_id = 1

    def _row(self, kind: str, key: str | None, content: str, occurred_at):
        row = SimpleNamespace(
            id=self._next_id,
            kind=kind,
            key=key,
            content=content,
            occurred_at=occurred_at,
            valid_until=None,
            source="explicit",
        )
        self._next_id += 1
        return row

    async def upsert_fact(self, *, platform_id, user_id, key, content, occurred_at, source, source_conversation_id):
        previous = self.facts.get(key)
        if previous is not None:
            previous.valid_until = datetime.now(timezone.utc)
        row = self._row("fact", key, content, occurred_at)
        self.facts[key] = row
        return row, previous

    async def create_event(self, *, platform_id, user_id, content, occurred_at, source, source_conversation_id):
        row = self._row("event", None, content, occurred_at)
        self.events.append(row)
        return row

    async def list_for_user(self, platform_id, user_id, *, kind=None, include_history=False, query=None, key=None, limit=200):
        rows = list(self.facts.values()) + self.events
        if not include_history:
            rows = [row for row in rows if row.valid_until is None]
        if kind is not None:
            rows = [row for row in rows if row.kind == kind]
        return rows[:limit]


def test_remember_memory_requires_a_present_principal() -> None:
    async def run() -> None:
        with pytest.raises(BadRequestException) as excinfo:
            await remember_memory(
                FakeMemoryRepository(),
                platform_id=1,
                user_id=None,
                kind="fact",
                key="城市",
                content="上海",
                occurred_at=None,
                mode="explicit",
            )
        assert excinfo.value.error_code == "memory_principal_required"

    asyncio.run(run())


def test_remember_fact_reports_previous_value() -> None:
    async def run() -> None:
        repo = FakeMemoryRepository()
        first = await remember_memory(
            repo,
            platform_id=1,
            user_id=7,
            kind="fact",
            key="城市",
            content="北京",
            occurred_at=None,
            mode="explicit",
        )
        assert first["previous_content"] is None

        second = await remember_memory(
            repo,
            platform_id=1,
            user_id=7,
            kind="fact",
            key="城市",
            content="上海",
            occurred_at=None,
            mode="inferred",
        )
        assert second["previous_content"] == "北京"
        assert "原值：北京" in second["message"]

    asyncio.run(run())


def test_search_memory_requires_principal_and_explains_empty_result() -> None:
    async def run() -> None:
        with pytest.raises(BadRequestException) as excinfo:
            await search_memory(
                FakeMemoryRepository(), platform_id=1, user_id=None, query="城市"
            )
        assert excinfo.value.error_code == "memory_principal_required"

        empty = await search_memory(
            FakeMemoryRepository(), platform_id=1, user_id=7, query="城市"
        )
        assert empty["items"] == []
        assert "不要编造" in empty["message"]

    asyncio.run(run())


def test_router_only_exposes_self_view() -> None:
    from app.modules.memory.router import router

    paths = {route.path for route in router.routes}
    assert paths == {
        "/platforms/{platform_id}/me/memories",
        "/platforms/{platform_id}/me/memories/{memory_id}",
        "/platforms/{platform_id}/me/memories/stats",
    }


# --------------------------------------------------------------------------- #
# 审批闸口：本人范围的写入直通，无人值守一律拒绝
# --------------------------------------------------------------------------- #


class FakeBuiltinRepository:
    async def is_enabled(self, platform_id, agent_id, tool_name):
        return True


async def _approve_everything(definition, call):
    return ConfirmationDecision(approved=True, reason="test_auto_approved")


async def _invoke_remember(*, user_id, unattended, decider, monkeypatch):
    from app.modules.tools.business import user_memory as user_memory_tools

    async def fake_remember_memory(memory_repo, **kwargs):
        return {"status": "remembered", "message": "已记住：城市 = 上海", "kind": "fact"}

    monkeypatch.setattr(user_memory_tools, "MemoryRepository", lambda session: object())
    monkeypatch.setattr(user_memory_tools, "remember_memory", fake_remember_memory)
    return await invoke_builtin_tool(
        FakeBuiltinRepository(),
        None,
        tool=SimpleNamespace(name="remember_user_memory"),
        call={"args": {"kind": "fact", "key": "城市", "content": "上海"}},
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=user_id,
        session=None,
        confirmation_decider=decider,
        unattended=unattended,
    )


def test_self_scoped_write_skips_confirmation_in_interactive_session(monkeypatch) -> None:
    """交互会话里写自己的记忆不弹确认卡：handler 直接执行就是直通的证明。"""

    async def run() -> None:
        outcome = await _invoke_remember(
            user_id=7, unattended=False, decider=None, monkeypatch=monkeypatch
        )
        assert outcome.status == "completed"
        assert outcome.result["message"] == "已记住：城市 = 上海"

    asyncio.run(run())


def test_self_scoped_write_still_asks_when_unattended(monkeypatch) -> None:
    """无人值守不是直通：工具必须拒绝，且原因是「没有在场主体」而不是静默写入。"""

    async def run() -> None:
        outcome = await _invoke_remember(
            user_id=7,
            unattended=True,
            decider=_approve_everything,
            monkeypatch=monkeypatch,
        )
        assert outcome.status == "failed"
        assert outcome.result["error"]["code"] == "memory_principal_required"

    asyncio.run(run())


def test_self_scoped_write_is_not_bypassed_without_a_backend_user(monkeypatch) -> None:
    """端用户会话（user_id 为空）没有可写的记忆主体，仍然走确认闸口并被拒绝。"""

    async def run() -> None:
        outcome = await _invoke_remember(
            user_id=None, unattended=False, decider=None, monkeypatch=monkeypatch
        )
        assert outcome.status == "rejected"
        assert outcome.result["reason"] == "no_confirmation_channel"

    asyncio.run(run())


def test_self_scoped_write_tools_are_the_memory_ones() -> None:
    """白名单集合本身就是安全边界，改动必须被这条断言拦下。"""

    assert SELF_SCOPED_WRITE_TOOLS == frozenset(
        {"remember_user_memory", "forget_user_memory"}
    )
