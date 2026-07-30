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
