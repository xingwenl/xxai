import asyncio
from datetime import UTC, datetime

from app.core.security import get_current_user
from app.modules.auth.router import get_current_user_endpoint
from app.modules.role.router import list_roles_endpoint
from app.modules.user.router import list_users_endpoint, user_list_query_dependency
from app.shared.exceptions import UnauthorizedException
from app.shared.pagination import PaginationParams
from main import app


class FakeCurrentUser:
    id = 1
    name = "Admin"
    email = "admin@example.com"
    account = "admin"
    is_active = True
    created_at = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
    updated_at = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
    roles = []


def test_auth_routes_are_registered_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/me" in paths


def test_user_and_role_routes_expose_bearer_security_in_openapi() -> None:
    openapi = app.openapi()

    user_security = openapi["paths"]["/api/v1/users"]["get"]["security"]
    role_security = openapi["paths"]["/api/v1/roles"]["get"]["security"]

    assert user_security == [{"HTTPBearer": []}]
    assert role_security == [{"HTTPBearer": []}]


def test_get_current_user_rejects_missing_bearer_token() -> None:
    async def run() -> None:
        try:
            await get_current_user(credentials=None, session=None)
        except UnauthorizedException as exc:
            assert exc.message == "not authenticated"
            return

        raise AssertionError("Expected missing credentials to raise UnauthorizedException")

    asyncio.run(run())


def test_auth_me_returns_current_user_when_authenticated() -> None:
    async def run() -> None:
        response = await get_current_user_endpoint(current_user=FakeCurrentUser())

        assert response.data is not None
        assert response.data.account == "admin"

    asyncio.run(run())


def test_user_and_role_endpoints_return_success_after_authentication(monkeypatch) -> None:
    async def fake_list_users(user_repo, role_repo, params, query):
        from app.modules.user.schemas import UserListData

        return UserListData(
            page_no=1,
            page_size=20,
            items=[{"id": 1, "name": "Admin", "account": "admin", "roles": []}],
            total=1,
            pages=1,
        )

    async def fake_list_roles(role_repo, params, query):
        from app.modules.role.schemas import RoleListData

        return RoleListData(
            page_no=1,
            page_size=20,
            items=[],
            total=0,
            pages=1,
        )

    monkeypatch.setattr("app.modules.user.router.list_users", fake_list_users)
    monkeypatch.setattr("app.modules.role.router.list_roles", fake_list_roles)

    async def run() -> None:
        user_response = await list_users_endpoint(
            params=PaginationParams(page=1, page_size=20),
            query=user_list_query_dependency(),
            session=object(),
        )
        role_response = await list_roles_endpoint(
            params=PaginationParams(page=1, page_size=20),
            query=type("RoleQuery", (), {"name": None, "code": None, "sort": "-created_at"})(),
            session=object(),
        )

        assert user_response.data.items[0]["account"] == "admin"
        assert role_response.data.total == 0

    asyncio.run(run())
