"""微信助手后台管理接口注册与认证测试。"""

from main import app


def test_wechat_bot_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    prefix = "/api/v1/platforms/{platform_id}/wechat-bots"
    assert prefix in paths
    assert f"{prefix}/{{binding_id}}/status" in paths
    assert f"{prefix}/{{binding_id}}/verify-code" in paths
    assert f"{prefix}/{{binding_id}}" in paths
    assert "get" in paths[prefix]
    assert "post" in paths[prefix]
    assert "patch" in paths[f"{prefix}/{{binding_id}}"]
    assert "delete" in paths[f"{prefix}/{{binding_id}}"]
    assert "post" in paths[f"{prefix}/{{binding_id}}/verify-code"]


def test_wechat_bot_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()
    prefix = "/api/v1/platforms/{platform_id}/wechat-bots"
    assert openapi["paths"][prefix]["post"]["security"] == [{"HTTPBearer": []}]
    assert openapi["paths"][f"{prefix}/{{binding_id}}"]["delete"]["security"] == [
        {"HTTPBearer": []}
    ]
