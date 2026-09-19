"""shop_agent 会话接口可选参数（agentId / hostToolNames / clientId / clientSecret）的契约与透传单测。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.embed import services as embed_services
from app.modules.shop_agent.schemas import ShopAgentSessionRequest
from app.shared.exceptions import BadRequestException


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def configured_embed_env(monkeypatch):
    """为签发放行所需的 Embed 服务端配置。"""
    monkeypatch.setenv("EMBED_CLIENT_ID", "client_test")
    monkeypatch.setenv("EMBED_CLIENT_SECRET", "secret_test")
    monkeypatch.setenv("EMBED_AGENT_ID", "9")
    monkeypatch.setenv("EMBED_ORIGIN", "https://shop.example.com")
    get_settings.cache_clear()


def test_session_request_defaults_keep_existing_behaviour():
    """不传新参数时行为与变更前一致：沿用默认 Agent，且不带任何宿主工具。"""
    payload = ShopAgentSessionRequest.model_validate(
        {"shopToken": "token-1", "shopUserId": "1"}
    )

    assert payload.agent_id is None
    assert payload.host_tool_names == []


def test_session_request_accepts_camel_case_options():
    payload = ShopAgentSessionRequest.model_validate(
        {
            "shopToken": "token-1",
            "shopUserId": "1",
            "agentId": 12,
            "hostToolNames": ["get_current_shop", "list_shops"],
        }
    )

    assert payload.agent_id == 12
    assert payload.host_tool_names == ["get_current_shop", "list_shops"]


def test_session_request_accepts_client_credentials():
    """调用方可以携带自己的 Embed Client 凭证，用于一个部署接入多个 Client。"""
    payload = ShopAgentSessionRequest.model_validate(
        {
            "shopToken": "token-1",
            "shopUserId": "1",
            "agentId": 12,
            "origin": "https://desktop.example.com",
            "clientId": "client_other",
            "clientSecret": "secret_other",
        }
    )

    assert payload.client_id == "client_other"
    assert payload.client_secret == "secret_other"


def test_session_request_client_credentials_are_optional():
    payload = ShopAgentSessionRequest.model_validate(
        {"shopToken": "token-1", "shopUserId": "1"}
    )

    assert payload.client_id is None
    assert payload.client_secret is None


def _install_fakes(monkeypatch, captured):
    class FakeEmbedRepo:
        def __init__(self, session):
            self.session = session

        async def get_client_by_id(self, client_id):
            captured["client_lookup"] = client_id
            # 额度服务会读取 Client 上的限流字段，这里给出与管理端一致的默认值。
            return SimpleNamespace(
                id=1,
                platform_id=7,
                max_tokens_per_minute=None,
                max_connections=None,
            )

    async def fake_issue_embed_token(embed_repo, agent_repo, request, **kwargs):
        captured["request"] = request
        return SimpleNamespace(access_token="embed-token", expires_in=600, jti="jti")

    monkeypatch.setattr(embed_services, "EmbedRepository", FakeEmbedRepo)
    monkeypatch.setattr(embed_services, "issue_embed_token", fake_issue_embed_token)


def test_issue_configured_agent_token_defaults_to_server_agent(
    monkeypatch, configured_embed_env
):
    """缺省 agent_id 时沿用服务端默认 Agent，保持既有调用方行为。"""
    captured = {}
    _install_fakes(monkeypatch, captured)

    asyncio.run(
        embed_services.issue_configured_agent_token(
            object(), external_user_id="1", host_tool_names=None
        )
    )

    request = captured["request"]
    assert request.agent_id == 9
    assert request.host_tool_names == []


def test_issue_configured_agent_token_forwards_agent_and_host_tools(
    monkeypatch, configured_embed_env
):
    """显式传入的 Agent 与宿主工具候选名必须原样进入签发请求。"""
    captured = {}
    _install_fakes(monkeypatch, captured)

    asyncio.run(
        embed_services.issue_configured_agent_token(
            object(),
            external_user_id="1",
            agent_id=12,
            host_tool_names=["get_current_shop"],
        )
    )

    request = captured["request"]
    assert request.agent_id == 12
    assert request.host_tool_names == ["get_current_shop"]


def test_issue_configured_agent_token_rejects_missing_agent(
    monkeypatch, configured_embed_env
):
    """没有可用默认 Agent 且调用方未指定时，必须拒绝而不是签发无效 token。"""
    monkeypatch.setenv("EMBED_AGENT_ID", "0")
    get_settings.cache_clear()

    with pytest.raises(BadRequestException):
        asyncio.run(
            embed_services.issue_configured_agent_token(object(), external_user_id="1")
        )


def test_issue_configured_agent_token_forwards_client_credentials(
    monkeypatch, configured_embed_env
):
    """携带的 Client 凭证必须原样进入签发请求，且按传入的 client_id 查找 Client。"""
    captured = {}
    _install_fakes(monkeypatch, captured)

    asyncio.run(
        embed_services.issue_configured_agent_token(
            object(),
            external_user_id="1",
            origin="https://desktop.example.com",
            agent_id=12,
            client_id="client_other",
            client_secret="secret_other",
        )
    )

    request = captured["request"]
    assert captured["client_lookup"] == "client_other"
    assert request.client_id == "client_other"
    assert request.client_secret == "secret_other"
    assert request.agent_id == 12
    assert request.origin == "https://desktop.example.com"


def test_issue_configured_agent_token_defaults_to_env_client(
    monkeypatch, configured_embed_env
):
    """不携带凭证时仍按服务端配置的 Client 签发，保持既有调用方行为。"""
    captured = {}
    _install_fakes(monkeypatch, captured)

    asyncio.run(
        embed_services.issue_configured_agent_token(object(), external_user_id="1")
    )

    request = captured["request"]
    assert captured["client_lookup"] == "client_test"
    assert request.client_id == "client_test"
    assert request.client_secret == "secret_test"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"client_id": "client_other"},
        {"client_secret": "secret_other"},
    ],
)
def test_issue_configured_agent_token_rejects_partial_credentials(
    monkeypatch, configured_embed_env, kwargs
):
    """Client ID 与密钥必须成对提供，避免出现来源不明的组合。"""
    _install_fakes(monkeypatch, {})

    with pytest.raises(BadRequestException):
        asyncio.run(
            embed_services.issue_configured_agent_token(
                object(), external_user_id="1", **kwargs
            )
        )


def test_issue_configured_agent_token_requires_agent_with_client(
    monkeypatch, configured_embed_env
):
    """携带凭证时不允许回退到服务端默认 Agent，否则容易把 Agent 配错。"""
    _install_fakes(monkeypatch, {})

    with pytest.raises(BadRequestException):
        asyncio.run(
            embed_services.issue_configured_agent_token(
                object(),
                external_user_id="1",
                client_id="client_other",
                client_secret="secret_other",
                origin="https://desktop.example.com",
            )
        )


def test_issue_configured_agent_token_requires_origin_with_client(
    monkeypatch, configured_embed_env
):
    """携带凭证时必须显式给出 origin，避免误用服务端默认来源。"""
    _install_fakes(monkeypatch, {})

    with pytest.raises(BadRequestException):
        asyncio.run(
            embed_services.issue_configured_agent_token(
                object(),
                external_user_id="1",
                client_id="client_other",
                client_secret="secret_other",
                agent_id=12,
            )
        )
