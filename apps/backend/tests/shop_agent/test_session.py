"""shop_agent 会话接口契约与店铺 token 校验/存储单测。"""

import asyncio

import pytest

from app.modules.shop_agent.router import router
from app.modules.shop_agent.services import store_shop_context, verify_shop_token
from app.shared.exceptions import UnauthorizedException


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return self.response

    async def post(self, *args, **kwargs):
        return self.response


def test_session_route_is_registered_under_api_v1():
    paths = {route.path for route in router.routes}
    assert "/shop-agent/session" in paths


def test_verify_shop_token_success(monkeypatch):
    body = {
        "code": 200,
        "msg": "操作成功",
        "user": {"userId": 1, "userName": "admin", "nickName": "管理员"},
    }

    def fake_client(*args, **kwargs):
        return FakeClient(FakeResponse(200, body))

    monkeypatch.setattr("app.modules.shop_agent.services.httpx.AsyncClient", fake_client)
    result = asyncio.run(verify_shop_token("http://hua8.test", "token-1", "1"))
    assert result == "管理员"


def test_verify_shop_token_user_mismatch(monkeypatch):
    body = {"code": 200, "msg": "ok", "user": {"userId": 99, "nickName": "x"}}

    def fake_client(*args, **kwargs):
        return FakeClient(FakeResponse(200, body))

    monkeypatch.setattr("app.modules.shop_agent.services.httpx.AsyncClient", fake_client)
    with pytest.raises(UnauthorizedException):
        asyncio.run(verify_shop_token("http://hua8.test", "token-1", "1"))


def test_verify_shop_token_invalid(monkeypatch):
    def fake_client(*args, **kwargs):
        return FakeClient(FakeResponse(401, {"code": 401, "msg": "认证失败"}))

    monkeypatch.setattr("app.modules.shop_agent.services.httpx.AsyncClient", fake_client)
    with pytest.raises(UnauthorizedException):
        asyncio.run(verify_shop_token("http://hua8.test", "token-bad", "1"))


def test_verify_shop_token_unreachable(monkeypatch):
    import httpx

    def fake_client(*args, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr("app.modules.shop_agent.services.httpx.AsyncClient", fake_client)
    with pytest.raises(UnauthorizedException):
        asyncio.run(verify_shop_token("http://hua8.test", "token-1", "1"))


def test_store_shop_context_writes_redis(monkeypatch):
    stored = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            stored[key] = (value, ex)
            return True

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "app.modules.shop_agent.services.Redis.from_url", lambda _url: FakeRedis()
    )
    asyncio.run(store_shop_context(42, "shop-token", "7"))
    assert "shop-agent:end-user:42" in stored
    value, ttl = stored["shop-agent:end-user:42"]
    assert "shop-token" in value
    assert ttl == 43200
