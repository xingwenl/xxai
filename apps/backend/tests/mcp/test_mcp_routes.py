from main import app


def test_mcp_management_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms/{platform_id}/mcp-servers" in paths
    assert "/api/v1/platforms/{platform_id}/mcp-servers/{server_id}" in paths
    assert "/api/v1/platforms/{platform_id}/mcp-servers/{server_id}/tools" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/mcp-servers" in paths
    assert (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/mcp-servers/{server_id}"
        in paths
    )
    assert "get" in paths["/api/v1/platforms/{platform_id}/mcp-servers"]
    assert "patch" in paths[
        "/api/v1/platforms/{platform_id}/mcp-servers/{server_id}"
    ]
    assert "delete" in paths[
        "/api/v1/platforms/{platform_id}/mcp-servers/{server_id}"
    ]


def test_mcp_management_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"]["/api/v1/platforms/{platform_id}/mcp-servers"]["get"][
        "security"
    ] == [{"HTTPBearer": []}]
