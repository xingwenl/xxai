"""shop-agent 会话接口「项目固定 Embed Client」优先级的单测。

接口层只负责取值与优先级：请求携带的凭证 > 项目常量 > 环境配置；
凭证、Agent、来源必须成套给出，否则会在签发阶段报出难以定位的错误。
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.shop_agent import router as shop_agent_router
from app.modules.shop_agent.schemas import ShopAgentSessionRequest
from app.shared.exceptions import BadRequestException


class FakeSession:
    async def commit(self):
        return None


@pytest.fixture(autouse=True)
def _reset_project_constants(monkeypatch):
    """默认清空项目常量，保证用例之间互不影响。"""
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_ID", "")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_SECRET", "")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_AGENT_ID", 0)
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_ORIGIN", "")


@pytest.fixture
def captured(monkeypatch):
    """替换店铺校验与签发服务，只观察接口层传出的参数。"""
    recorded: dict = {}

    async def fake_verify_shop_token(base_url, shop_token, shop_user_id):
        recorded["verify"] = (base_url, shop_token, shop_user_id)
        return "昵称"

    async def fake_issue(session, **kwargs):
        recorded["issue"] = kwargs
        return SimpleNamespace(access_token="embed-token", expires_in=600, jti="jti")

    def fake_decode(token):
        return {"sub": "42"}

    async def fake_store(end_user_id, shop_token, shop_user_id):
        recorded["store"] = (end_user_id, shop_token, shop_user_id)

    monkeypatch.setattr(shop_agent_router, "verify_shop_token", fake_verify_shop_token)
    monkeypatch.setattr(shop_agent_router, "issue_configured_agent_token", fake_issue)
    monkeypatch.setattr(shop_agent_router, "decode_embed_token", fake_decode)
    monkeypatch.setattr(shop_agent_router, "store_shop_context", fake_store)
    return recorded


def _payload(**overrides):
    data = {"shopToken": "shop-token", "shopUserId": "1001"}
    data.update(overrides)
    return ShopAgentSessionRequest.model_validate(data)


def _call(payload, origin):
    return asyncio.run(
        shop_agent_router.create_shop_agent_session(
            payload=payload, origin=origin, session=FakeSession()
        )
    )


def test_router_falls_back_to_env_configuration(captured):
    """常量留空且请求未带凭证时，沿用服务端环境配置（行为与变更前一致）。"""
    _call(_payload(), "https://shop.example.com")

    issue = captured["issue"]
    assert issue["client_id"] is None
    assert issue["client_secret"] is None
    assert issue["agent_id"] is None
    assert issue["origin"] == "https://shop.example.com"


def test_router_uses_project_constants(monkeypatch, captured):
    """项目常量配齐时直接使用固定 Client、Agent 与来源，客户端无需携带任何凭证。"""
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_ID", "client_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_SECRET", "secret_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_AGENT_ID", 12)

    _call(_payload(), "http://127.0.0.1:5390")

    issue = captured["issue"]
    assert issue["client_id"] == "client_project"
    assert issue["client_secret"] == "secret_project"
    assert issue["agent_id"] == 12


def test_router_uses_project_origin_when_caller_omits_it(monkeypatch, captured):
    """请求未带来源时用项目固定来源补齐，避免退回到服务端默认来源。"""
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_ID", "client_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_SECRET", "secret_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_AGENT_ID", 12)
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_ORIGIN", "http://127.0.0.1:5390")

    _call(_payload(), None)

    assert captured["issue"]["origin"] == "http://127.0.0.1:5390"


def test_router_rejects_project_client_without_agent(monkeypatch, captured):
    """固定了 Client 却没有配 Agent 时直接拒绝，而不是倒退到默认 Agent。"""
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_ID", "client_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_SECRET", "secret_project")

    with pytest.raises(BadRequestException):
        _call(_payload(), "http://127.0.0.1:5390")


def test_router_prefers_request_credentials_over_constants(monkeypatch, captured):
    """请求携带的凭证优先级高于项目常量，便于同一部署临时接入其他 Client。"""
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_ID", "client_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_CLIENT_SECRET", "secret_project")
    monkeypatch.setattr(shop_agent_router, "PROJECT_EMBED_AGENT_ID", 12)

    _call(
        _payload(agentId=99, clientId="client_request", clientSecret="secret_request"),
        "http://127.0.0.1:5390",
    )

    issue = captured["issue"]
    assert issue["client_id"] == "client_request"
    assert issue["client_secret"] == "secret_request"
    assert issue["agent_id"] == 99
