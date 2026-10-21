import asyncio
from dataclasses import dataclass
from unittest.mock import patch

from app.modules.gateway.router import build_session_info
from app.modules.quota.service import QuotaDimensions, QuotaService


class FakeCounter:
    def __init__(self, values: dict[str, int] | None = None, *, fail: bool = False):
        self.values = values or {}
        self.fail = fail

    async def peek(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.get(key, 0)


class FakeSession:
    """模拟 get_session_factory()() 产生的可复用异步上下文会话。"""

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@dataclass
class FakeClient:
    id: int = 1
    platform_id: int = 7
    client_id: str = "client_acme"
    name: str = "Acme Web"
    token_ttl_seconds: int = 600
    max_tokens_per_minute: int | None = 120
    max_connections: int | None = 50
    allow_agent_switching: bool = True


@dataclass
class FakeAgent:
    id: int = 11
    platform_id: int = 7
    name: str = "客服助手"
    slug: str = "support-bot"
    description: str = "负责售后问题"


class FakeEmbedRepository:
    def __init__(self, client):
        self.client = client

    async def get_client(self, platform_id: int, client_id: str):
        if (
            self.client is not None
            and self.client.platform_id == platform_id
            and self.client.client_id == client_id
        ):
            return self.client
        return None


class FakeAgentRepository:
    def __init__(self, agent):
        self.agent = agent

    async def get_agent(self, agent_id: int, platform_id: int):
        if (
            self.agent is not None
            and self.agent.id == agent_id
            and self.agent.platform_id == platform_id
        ):
            return self.agent
        return None


class Settings:
    quota_window_seconds = 60
    quota_token_issue_limit = 100


def build_quota_service(
    values: dict[str, int] | None = None, *, fail: bool = False
) -> QuotaService:
    return QuotaService(
        FakeCounter(values, fail=fail),
        limits={"connection": 10, "message": 60, "model_tokens": 10000000},
        window_seconds={"connection": 60, "message": 60, "model_tokens": 60},
        clock=lambda: 12345.0,
    )


def run_scenario(
    payload: dict,
    *,
    client=FakeClient(),
    agent=FakeAgent(),
    quota_service=None,
    repo_error=False,
):
    class ExplodingRepo:
        def __init__(self, *args):
            pass

        async def get_client(self, *args):
            raise RuntimeError("db unavailable")

    embed_repo = ExplodingRepo() if repo_error else FakeEmbedRepository(client)
    agent_repo = ExplodingRepo() if repo_error else FakeAgentRepository(agent)
    with (
        patch(
            "app.modules.gateway.router.EmbedRepository", return_value=embed_repo
        ),
        patch(
            "app.modules.gateway.router.AgentRepository", return_value=agent_repo
        ),
    ):
        return asyncio.run(
            build_session_info(
                payload,
                agent_id=agent.id if agent is not None else 11,
                settings=Settings(),
                quota_service=quota_service,
                session_factory=lambda: FakeSession(),
            )
        )


def quota_key(resource: str, *, end_user: str | None = None) -> str:
    dimensions = QuotaDimensions(
        platform_id="7",
        client_id="client_acme",
        agent_id="11",
        end_user_id=end_user,
    )
    return QuotaService.key(resource, dimensions, 205)


def test_session_info_includes_client_agent_and_quota_snapshot():
    values = {
        quota_key("connection", end_user="99"): 2,
        quota_key("message", end_user="99"): 12,
        quota_key("model_tokens", end_user="99"): 123456,
        quota_key("token_issue"): 3,
    }
    info = run_scenario(
        {"platform_id": 7, "client_id": "client_acme", "sub": "99"},
        quota_service=build_quota_service(values),
    )

    assert info["client"] == {
        "clientId": "client_acme",
        "name": "Acme Web",
        "tokenTtlSeconds": 600,
        "maxTokensPerMinute": 120,
        "maxConnections": 50,
        "allowAgentSwitching": True,
    }
    assert info["agent"] == {
        "agentId": 11,
        "name": "客服助手",
        "slug": "support-bot",
        "description": "负责售后问题",
    }
    assert info["quota"]["windowSeconds"] == 60
    assert info["quota"]["resources"] == {
        "connection": {"limit": 10, "current": 2},
        "message": {"limit": 60, "current": 12},
        "model_tokens": {"limit": 10000000, "current": 123456},
        "token_issue": {"limit": 120, "current": 3},
    }


def test_session_info_quota_null_when_quota_disabled():
    info = run_scenario(
        {"platform_id": 7, "client_id": "client_acme", "sub": "99"},
        quota_service=None,
    )

    assert info["quota"] is None
    assert info["client"]["name"] == "Acme Web"
    assert info["agent"]["slug"] == "support-bot"


def test_session_info_quota_null_when_redis_unavailable():
    info = run_scenario(
        {"platform_id": 7, "client_id": "client_acme", "sub": "99"},
        quota_service=build_quota_service(fail=True),
    )

    assert info["quota"] is None
    assert info["client"] is not None
    assert info["agent"] is not None


def test_token_issue_limit_falls_back_to_settings_when_client_unset():
    client = FakeClient(max_tokens_per_minute=None)
    info = run_scenario(
        {"platform_id": 7, "client_id": "client_acme", "sub": "99"},
        client=client,
        quota_service=build_quota_service(),
    )

    assert info["quota"]["resources"]["token_issue"]["limit"] == 100


def test_session_info_returns_null_for_missing_client_and_agent():
    info = run_scenario(
        {"platform_id": 7, "client_id": "unknown", "sub": "99"},
        client=None,
        agent=None,
        quota_service=build_quota_service(),
    )

    assert info == {"client": None, "agent": None, "quota": None}


def test_session_info_does_not_raise_when_db_unavailable():
    info = run_scenario(
        {"platform_id": 7, "client_id": "client_acme", "sub": "99"},
        quota_service=build_quota_service(),
        repo_error=True,
    )

    assert info == {"client": None, "agent": None, "quota": None}
