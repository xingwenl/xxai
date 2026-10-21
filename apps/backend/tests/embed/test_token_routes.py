def test_embed_token_route_contract_is_scoped_to_embed_audience():
    """The route module must expose an independent token exchange contract."""
    from app.modules.embed.router import router

    paths = {route.path for route in router.routes}
    assert "/embed/tokens" in paths


def test_embed_client_management_routes_are_platform_scoped():
    from app.modules.embed.router import router

    paths = {route.path for route in router.routes}
    assert "/platforms/{platform_id}/embed-clients" in paths
    assert "/platforms/{platform_id}/embed-clients/{client_id}/agents" in paths
    assert "/platforms/{platform_id}/embed-clients/{client_id}/rotate-secret" in paths
    assert (
        "/platforms/{platform_id}/embed-clients/{client_id}/agents/{agent_id}" in paths
    )


def test_demo_agent_token_route_is_registered_outside_embed_exchange():
    from app import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/api/agent-token" in paths


def test_authenticated_agent_token_route_is_registered_under_api_v1():
    from app import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/embed/agent-token" in paths


def test_authenticated_agent_token_requires_current_active_user():
    from app.modules.embed.router import router

    route = next(
        item for item in router.routes if item.path == "/embed/agent-token"
    )
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }
    assert "require_current_active_user" in dependency_names


def test_demo_agent_token_requires_current_active_user():
    """`/api/agent-token` 曾无任何鉴权依赖，任何人可为任意终端用户签发 token。"""
    from app.modules.embed.token_router import router

    route = next(item for item in router.routes if item.path == "/agent-token")
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }
    assert "require_current_active_user" in dependency_names


class _FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _call_demo_token_route(*, app_env, external_user_id, current_user_id=7):
    """直接调用路由函数，捕获它交给 service 的 token 主体。"""
    import asyncio
    from types import SimpleNamespace

    from app.modules.embed import token_router

    captured = {}

    async def fake_issue_configured_agent_token(session, **kwargs):
        captured.update(kwargs)
        return "fake-token"

    original_settings = token_router.get_settings
    original_issue = token_router.issue_configured_agent_token
    token_router.get_settings = lambda: SimpleNamespace(app_env=app_env)
    token_router.issue_configured_agent_token = fake_issue_configured_agent_token
    try:
        asyncio.run(
            token_router.get_agent_token(
                external_user_id=external_user_id,
                display_name=None,
                origin=None,
                host_tool_names=[],
                current_user=SimpleNamespace(id=current_user_id, name="张三"),
                session=_FakeSession(),
            )
        )
    finally:
        token_router.get_settings = original_settings
        token_router.issue_configured_agent_token = original_issue
    return captured


def test_demo_agent_token_allows_external_user_id_override_outside_production():
    captured = _call_demo_token_route(app_env="development", external_user_id="999")
    assert captured["external_user_id"] == "999"
    assert captured["display_name"] == "张三"


def test_demo_agent_token_ignores_external_user_id_override_in_production():
    captured = _call_demo_token_route(app_env="production", external_user_id="999")
    assert captured["external_user_id"] == "7"


def test_demo_agent_token_falls_back_to_current_user_without_override():
    captured = _call_demo_token_route(app_env="development", external_user_id=None)
    assert captured["external_user_id"] == "7"


def _call_authenticated_token_route(*, agent_id):
    """直接调用路由函数，检查 agent_id 是否原样透传给 service。"""
    import asyncio
    from types import SimpleNamespace

    from app.modules.embed import router as embed_router

    captured = {}

    async def fake_issue_configured_agent_token(session, **kwargs):
        captured.update(kwargs)
        return "fake-token"

    original_issue = embed_router.issue_configured_agent_token
    embed_router.issue_configured_agent_token = fake_issue_configured_agent_token
    try:
        response = asyncio.run(
            embed_router.get_authenticated_agent_token_endpoint(
                display_name=None,
                origin=None,
                host_tool_names=[],
                agent_id=agent_id,
                current_user=SimpleNamespace(id=7, name="张三"),
                session=_FakeSession(),
            )
        )
    finally:
        embed_router.issue_configured_agent_token = original_issue
    return captured, response


def test_authenticated_agent_token_passes_explicit_agent_id_through():
    """切换智能体后 SDK 会带 agent_id 重新换 token；路由只负责透传。"""
    captured, response = _call_authenticated_token_route(agent_id=11)

    assert captured["agent_id"] == 11
    assert response.data == "fake-token"


def test_authenticated_agent_token_omits_agent_id_when_not_provided():
    captured, _ = _call_authenticated_token_route(agent_id=None)

    assert captured["agent_id"] is None
