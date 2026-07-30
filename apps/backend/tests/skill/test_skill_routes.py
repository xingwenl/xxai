from main import app


def test_skill_management_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms/{platform_id}/skills" in paths
    assert "/api/v1/platforms/{platform_id}/skills/{skill_id}" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills" in paths
    assert (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills/{skill_id}"
        in paths
    )
    assert "get" in paths["/api/v1/platforms/{platform_id}/skills"]
    assert "patch" in paths["/api/v1/platforms/{platform_id}/skills/{skill_id}"]
    assert "delete" in paths["/api/v1/platforms/{platform_id}/skills/{skill_id}"]
    assert "delete" in paths[
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills/{skill_id}"
    ]


def test_skill_management_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"]["/api/v1/platforms/{platform_id}/skills"]["get"][
        "security"
    ] == [{"HTTPBearer": []}]
