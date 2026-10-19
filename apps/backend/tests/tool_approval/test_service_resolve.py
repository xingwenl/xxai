"""`ToolApprovalService.resolve` 的状态回读回归测试。

覆盖一个实测出来的真缺陷：`claim()` 走 Core `UPDATE`（`synchronize_session=False`）
且会话工厂是 `expire_on_commit=False`，所以 identity map 里那条 `ToolConfirmation`
实例仍停留在 `pending`。若 `_reload()` 只查询不刷新，调用方会把「刚批准」读成
「未批准」——真进程里的表现是：数据库里 `status='approved'`，模型收到的工具结果
却是 `{"status":"rejected","reason":"user_rejected"}`。

这里的假仓储刻意复刻「库里的行已改、缓存实例没改」这一语义，并用
`FakeSession.refresh` 记录是否被显式刷新。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.tool_approval.services import ToolApprovalService
from app.shared.exceptions import ConflictException, NotFoundException


@dataclass
class _Row:
    id: int
    status: str = "pending"
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))


class _FakeSession:
    """只实现 `refresh`：把「库里的值」覆盖回缓存实例，并记录调用。"""

    def __init__(self, stored: dict[int, _Row]) -> None:
        self.stored = stored
        self.refreshed: list[int] = []

    async def refresh(self, instance) -> None:
        row = self.stored[instance.id]
        instance.status = row.status
        instance.resolved_by = row.resolved_by
        instance.resolved_at = row.resolved_at
        instance.expires_at = row.expires_at
        self.refreshed.append(instance.id)


class _FakeRepository:
    """`get()` 返回缓存实例（状态是旧的）；`claim()` 只改库里的行。"""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self._cache: dict[int, _Row] = {}

    async def get(self, confirmation_id: int):
        if confirmation_id not in self.session.stored:
            return None
        if confirmation_id not in self._cache:
            # 首次读取时拷一份快照当缓存实例；此后不再与库同步。
            self._cache[confirmation_id] = _Row(**vars(self.session.stored[confirmation_id]))
        return self._cache[confirmation_id]

    async def claim(self, confirmation_id: int, status: str, *, resolved_by: str | None = None) -> bool:
        row = self.session.stored[confirmation_id]
        if row.status != "pending":
            return False
        row.status = status
        row.resolved_by = resolved_by
        row.resolved_at = datetime.now(UTC)
        return True

    async def find_recent_approved(self, **_kwargs):
        return None


def _service(rows: list[_Row]) -> tuple[ToolApprovalService, _FakeSession, _FakeRepository]:
    stored = {row.id: row for row in rows}
    session = _FakeSession(stored)
    service = ToolApprovalService(session)  # type: ignore[arg-type]
    repository = _FakeRepository(session)
    service.repository = repository  # type: ignore[assignment]
    return service, session, repository


def test_resolve_approved_reads_back_fresh_status() -> None:
    service, session, _ = _service([_Row(id=1)])

    resolved = asyncio.run(service.resolve(confirmation_id=1, approved=True, actor="end_user"))

    assert resolved.status == "approved", "数据库已批准，但返回的实例仍是旧状态"
    assert resolved.resolved_by == "end_user"
    assert 1 in session.refreshed, "必须显式 refresh 才能越过 identity map 的旧值"


def test_resolve_rejected_reads_back_fresh_status() -> None:
    service, _, _ = _service([_Row(id=2)])

    resolved = asyncio.run(service.resolve(confirmation_id=2, approved=False, actor="end_user"))

    assert resolved.status == "rejected"


def test_resolve_expired_row_is_claimed_as_expired() -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    service, session, _ = _service([_Row(id=3, expires_at=past)])

    resolved = asyncio.run(service.resolve(confirmation_id=3, approved=True, actor="end_user"))

    assert resolved.status == "expired", "过期行绝不能被读成 approved"
    assert resolved.resolved_by == "timeout"
    assert 3 in session.refreshed


def test_resolve_uses_fresh_expires_at_not_cached_one() -> None:
    """缓存里的 expires_at 还在未来、库里的已被 TTL 改到过去时，必须按过期处理。

    这条复刻的是真实时序：`request()` 在本请求里创建并刷新过该行（缓存了 10 分钟
    后的 expires_at），随后 TTL 扫描或人工处置把库里的 expires_at 推到过去。
    """

    future = datetime.now(UTC) + timedelta(minutes=10)
    service, session, repository = _service([_Row(id=6, expires_at=future)])
    asyncio.run(repository.get(6))  # 先把「未来的 expires_at」装进缓存实例
    session.stored[6].expires_at = datetime.now(UTC) - timedelta(minutes=1)

    resolved = asyncio.run(service.resolve(confirmation_id=6, approved=True, actor="end_user"))

    assert resolved.status == "expired", "不能拿缓存里的旧 expires_at 放行"
    assert resolved.resolved_by == "timeout"


def test_resolve_already_resolved_raises_conflict() -> None:
    service, _, _ = _service([_Row(id=4, status="approved")])

    with pytest.raises(ConflictException):
        asyncio.run(service.resolve(confirmation_id=4, approved=True, actor="end_user"))


def test_resolve_missing_raises_not_found() -> None:
    service, _, _ = _service([])

    with pytest.raises(NotFoundException):
        asyncio.run(service.resolve(confirmation_id=99, approved=True, actor="end_user"))


def test_expire_marks_row_expired() -> None:
    service, session, _ = _service([_Row(id=5)])

    expired = asyncio.run(service.expire(confirmation_id=5))

    assert expired.status == "expired"
    assert session.refreshed == [5]
