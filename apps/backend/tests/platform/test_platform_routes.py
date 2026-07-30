from main import app


def test_platform_list_route_is_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms" in paths
    assert "get" in paths["/api/v1/platforms"]
