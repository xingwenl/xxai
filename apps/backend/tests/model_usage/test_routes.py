def test_model_usage_routes_are_registered():
    from app import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/platforms/{platform_id}/model-usage-records" in paths
    assert (
        "/api/v1/platforms/{platform_id}/model-usage-records/summary" in paths
    )
