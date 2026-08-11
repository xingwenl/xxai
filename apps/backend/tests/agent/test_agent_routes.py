from main import app


def test_agent_management_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms" in paths
    assert "/api/v1/platforms/{platform_id}/agents" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/versions" in paths
    assert "get" in paths["/api/v1/platforms/{platform_id}/agents"]
    assert "patch" in paths["/api/v1/platforms/{platform_id}/agents/{agent_id}"]
    assert "delete" in paths["/api/v1/platforms/{platform_id}/agents/{agent_id}"]


def test_agent_management_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"]["/api/v1/platforms"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
    assert openapi["paths"]["/api/v1/platforms/{platform_id}/agents"]["get"][
        "security"
    ] == [{"HTTPBearer": []}]


def test_agent_detail_route_requires_get() -> None:
    paths = app.openapi()["paths"]
    path = "/api/v1/platforms/{platform_id}/agents/{agent_id}"
    assert "get" in paths[path]
