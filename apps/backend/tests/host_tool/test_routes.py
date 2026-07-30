import pytest
import asyncio

from app.modules.host_tool.schemas import HostToolPolicyCreate
from app.shared.exceptions import ConflictException


def test_host_tool_management_routes_include_binding_read_contracts():
    from app.modules.host_tool.router import router

    paths = {route.path for route in router.routes}
    assert "/platforms/{platform_id}/host-tools" in paths
    assert "/platforms/{platform_id}/agents/{agent_id}/host-tools" in paths
    assert "/platforms/{platform_id}/embed-clients/{client_id}/host-tools" in paths
    assert "/platforms/{platform_id}/host-tool-audits" in paths


def test_create_host_tool_duplicate_raises_stable_conflict(monkeypatch):
    from app.modules.host_tool import router as host_tool_router

    class FakePlatformRepository:
        def __init__(self, session):
            pass

        async def get_by_id_for_user(self, platform_id, user_id):
            return object()

    class FakeHostToolRepository:
        def __init__(self, session):
            pass

        async def get_policy_by_name(self, platform_id, name):
            return object()

    monkeypatch.setattr(host_tool_router, "PlatformRepository", FakePlatformRepository)
    monkeypatch.setattr(host_tool_router, "HostToolRepository", FakeHostToolRepository)

    payload = HostToolPolicyCreate(
        name="orders.get_status",
        description="Read order status",
        input_schema={"type": "object"},
        side_effect="none",
    )

    with pytest.raises(ConflictException):
        asyncio.run(
            host_tool_router.create_host_tool(
                1, payload, current_user=type("User", (), {"id": 10})(), session=object()
            )
        )
