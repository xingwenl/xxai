from main import app


def test_knowledge_management_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms/{platform_id}/knowledge-bases" in paths
    assert "/api/v1/platforms/{platform_id}/knowledge-bases/{base_id}" in paths
    assert (
        "/api/v1/platforms/{platform_id}/knowledge-bases/{base_id}/documents"
        in paths
    )
    assert (
        "/api/v1/platforms/{platform_id}/knowledge-bases/{base_id}/documents/{document_id}/retry"
        in paths
    )
    assert "get" in paths["/api/v1/platforms/{platform_id}/knowledge-bases"]
    assert "delete" in paths["/api/v1/platforms/{platform_id}/knowledge-bases/{base_id}"]
    assert "delete" in paths[
        "/api/v1/platforms/{platform_id}/knowledge-bases/{base_id}/documents/{document_id}"
    ]


def test_knowledge_management_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"][
        "/api/v1/platforms/{platform_id}/knowledge-bases"
    ]["get"]["security"] == [{"HTTPBearer": []}]


def test_agent_knowledge_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    list_path = (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/knowledge-bases"
    )
    unbind_path = (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/knowledge-bases/{base_id}"
    )
    assert list_path in paths
    assert unbind_path in paths
    assert "get" in paths[list_path]
    assert "delete" in paths[unbind_path]
