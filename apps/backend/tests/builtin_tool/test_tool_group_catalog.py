"""工具组只读目录接口（管理台按组展示）的契约测试。

分组判定必须与运行期同源：这里既钉住「内置工具一个不漏」，也钉住宿主工具的
组名来自 ``agent_runtime.tool_groups.tool_group()``（同一函数，不另起一套规则）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.agent_runtime.tool_groups import tool_group
from app.modules.builtin_tool import router as builtin_router
from app.modules.builtin_tool.registry import list_builtin_tools
from app.modules.host_tool import repositories as host_repositories
from app.shared.exceptions import NotFoundException
from main import app


def _fake_policies() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(name="note_save_note"),
        SimpleNamespace(name="ledger_add_entry"),
        SimpleNamespace(name="page_click"),
        SimpleNamespace(name="debug_ping"),
    ]


def _catalog(monkeypatch):
    class FakeHostToolRepository:
        def __init__(self, _session):
            pass

        async def list_policies(self, _platform_id):
            return _fake_policies()

    monkeypatch.setattr(
        host_repositories, "HostToolRepository", FakeHostToolRepository
    )
    return asyncio.run(builtin_router._tool_group_catalog(1, object()))


def test_tool_groups_route_is_registered_with_bearer_auth() -> None:
    paths = app.openapi()["paths"]
    path = paths["/api/v1/platforms/{platform_id}/tool-groups"]

    assert "get" in path
    assert path["get"]["security"] == [{"HTTPBearer": []}]


def test_catalog_covers_every_builtin_tool_exactly_once(monkeypatch) -> None:
    catalog = _catalog(monkeypatch)

    listed = [name for group in catalog.builtin for name in group.tool_names]
    expected = {tool.name for tool in list_builtin_tools()}

    # 一个不漏、一个不多：漏了就是页面上看不见那个工具，多了就是把别的组算进来。
    assert sorted(listed) == sorted(expected)
    assert len(listed) == len(set(listed))

    by_group = {tool.name: tool.group for tool in list_builtin_tools()}
    for group in catalog.builtin:
        for name in group.tool_names:
            assert by_group[name] == group.group
        title, description = group.title, group.description
        assert title and description


def test_catalog_marks_always_bound_groups_eager(monkeypatch) -> None:
    catalog = _catalog(monkeypatch)
    eager = {group.group: group.eager for group in catalog.builtin}

    # basic 组按构造始终绑定；其余内置组默认异步加载。
    assert eager["basic"] is True
    assert eager["ops"] is False and eager["memory"] is False
    assert catalog.builtin[0].group == "basic"


def test_host_groups_reuse_runtime_classification(monkeypatch) -> None:
    catalog = _catalog(monkeypatch)

    by_name = {
        name: group.group for group in catalog.host for name in group.tool_names
    }
    assert by_name == {policy.name: tool_group(policy) for policy in _fake_policies()}
    # 登记前缀各自成组，未登记前缀落 host 兜底组且标常驻。
    assert by_name["note_save_note"] == "note"
    assert by_name["ledger_add_entry"] == "ledger"
    assert by_name["page_click"] == "page"
    assert by_name["debug_ping"] == "host"
    host = next(group for group in catalog.host if group.group == "host")
    assert host.eager is True
    assert catalog.host[-1].group == "host"


def test_tool_groups_endpoint_rejects_other_platform(monkeypatch) -> None:
    class FakePlatformRepository:
        def __init__(self, _session):
            pass

        async def get_by_id_for_user(self, _platform_id, _user_id):
            return None

    monkeypatch.setattr(builtin_router, "PlatformRepository", FakePlatformRepository)

    with pytest.raises(NotFoundException, match="platform not found"):
        asyncio.run(
            builtin_router.list_tool_groups_endpoint(
                1, current_user=SimpleNamespace(id=2), session=object()
            )
        )
