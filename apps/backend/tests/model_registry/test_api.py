"""模型注册表与 Agent 绑定路由注册测试。"""

from main import app


def test_model_registry_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms/{platform_id}/models" in paths
    assert "/api/v1/platforms/{platform_id}/models/{model_id}" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/models" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/models/{role}" in paths
    assert "post" in paths["/api/v1/platforms/{platform_id}/models"]
    assert "patch" in paths["/api/v1/platforms/{platform_id}/models/{model_id}"]
    assert "delete" in paths["/api/v1/platforms/{platform_id}/models/{model_id}"]
    assert "put" in paths["/api/v1/platforms/{platform_id}/agents/{agent_id}/models"]
    assert (
        "delete"
        in paths["/api/v1/platforms/{platform_id}/agents/{agent_id}/models/{role}"]
    )


def test_model_registry_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"]["/api/v1/platforms/{platform_id}/models"]["get"][
        "security"
    ] == [{"HTTPBearer": []}]
    assert openapi["paths"]["/api/v1/platforms/{platform_id}/agents/{agent_id}/models"][
        "get"
    ]["security"] == [{"HTTPBearer": []}]
