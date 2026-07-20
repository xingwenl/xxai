from main import app


def test_user_routes_are_registered_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/users" in paths
    assert "/api/v1/users/{user_id}" in paths
    assert "patch" in paths["/api/v1/users/{user_id}"]
    assert "delete" in paths["/api/v1/users/{user_id}"]
