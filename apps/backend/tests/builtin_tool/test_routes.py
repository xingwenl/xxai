import asyncio
from types import SimpleNamespace

import pytest

from app.modules.builtin_tool import router as builtin_router
from app.shared.exceptions import NotFoundException
from main import app


def test_builtin_tool_and_asset_routes_are_registered_with_bearer_auth() -> None:
    paths = app.openapi()["paths"]
    catalog = paths["/api/v1/platforms/{platform_id}/builtin-tools"]
    binding = paths[
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/builtin-tools/{tool_name}"
    ]
    asset = paths["/api/v1/assets/{asset_id}"]

    assert "get" in catalog
    assert "put" in binding
    assert catalog["get"]["security"] == [{"HTTPBearer": []}]
    assert binding["put"]["security"] == [{"HTTPBearer": []}]
    assert asset["get"]["security"] == [{"HTTPBearer": []}]


def test_list_agent_tools_rejects_unknown_agent(monkeypatch) -> None:
    class FakePlatformRepository:
        def __init__(self, _session):
            pass

        async def get_by_id_for_user(self, _platform_id, _user_id):
            return object()

    class FakeAgentRepository:
        def __init__(self, _session):
            pass

        async def get_agent(self, _agent_id, _platform_id):
            return None

    monkeypatch.setattr(builtin_router, "PlatformRepository", FakePlatformRepository)
    monkeypatch.setattr(builtin_router, "AgentRepository", FakeAgentRepository)

    with pytest.raises(NotFoundException, match="agent not found"):
        asyncio.run(
            builtin_router.list_agent_tools_endpoint(
                1,
                2,
                current_user=SimpleNamespace(id=3),
                session=object(),
            )
        )
