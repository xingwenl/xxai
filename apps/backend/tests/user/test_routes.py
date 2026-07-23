from main import app


def test_user_routes_are_registered_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/users" in paths
    assert "/api/v1/users/{user_id}" in paths
    assert "/api/v1/roles" in paths
    assert "/api/v1/roles/{role_id}" in paths
    assert "patch" in paths["/api/v1/users/{user_id}"]
    assert "delete" in paths["/api/v1/users/{user_id}"]
    assert "patch" in paths["/api/v1/roles/{role_id}"]
    assert "delete" in paths["/api/v1/roles/{role_id}"]


def test_user_list_route_exposes_query_params_in_openapi() -> None:
    params = app.openapi()["paths"]["/api/v1/users"]["get"]["parameters"]
    names = {item["name"] for item in params}

    assert {"page", "page_size", "name", "email", "role_id", "role_code", "sort", "fields"} <= names
