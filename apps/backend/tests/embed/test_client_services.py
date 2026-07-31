import asyncio
from dataclasses import dataclass

import pytest

from app.modules.embed.schemas import EmbedTokenRequest, PlatformEmbedClientCreate
from app.modules.embed.services import create_embed_client, issue_embed_token
from app.modules.embed.security import decode_embed_token
from app.shared.exceptions import UnauthorizedException
from app.shared.exceptions import TooManyRequestsException


@dataclass
class FakeClient:
    id: int = 1
    platform_id: int = 7
    client_id: str = "client_acme"
    name: str = "Acme Web"
    secret_hash: str = ""
    allowed_origins: list[str] | None = None
    token_ttl_seconds: int = 600
    is_active: bool = True
    max_tokens_per_minute: int | None = None
    max_connections: int | None = None
    allow_temporary_tools: bool = False


@dataclass
class FakeAgent:
    id: int = 11
    platform_id: int = 7


class FakeEmbedRepository:
    def __init__(self, client: FakeClient | None = None) -> None:
        self.client = client
        self.created_end_users: list[dict] = []

    async def create_client(self, **values):
        self.client = FakeClient(**values)
        return self.client

    async def get_client(self, platform_id: int, client_id: str):
        if (
            self.client
            and self.client.platform_id == platform_id
            and self.client.client_id == client_id
        ):
            return self.client
        return None

    async def get_end_user(self, platform_id: int, external_user_id: str):
        return next(
            (
                item
                for item in self.created_end_users
                if item["platform_id"] == platform_id
                and item["external_user_id"] == external_user_id
            ),
            None,
        )

    async def is_agent_allowed(self, client_id: int, agent_id: int):
        return agent_id == 11

    async def list_client_tool_names(self, client_id: int):
        return {"get_weather", "calculate_total"}

    async def create_end_user(
        self, platform_id: int, external_user_id: str, display_name: str | None
    ):
        item = {
            "id": 22,
            "platform_id": platform_id,
            "external_user_id": external_user_id,
            "display_name": display_name,
        }
        self.created_end_users.append(item)
        return type("EndUser", (), item)()


class FakeAgentRepository:
    async def get_agent(self, agent_id: int, platform_id: int):
        return (
            FakeAgent(id=agent_id, platform_id=platform_id) if agent_id == 11 else None
        )


class FakeTokenQuota:
    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.calls = []

    async def check(self, resource, dimensions):
        self.calls.append((resource, dimensions))
        return type(
            "Decision",
            (),
            {
                "allowed": self.allowed,
                "code": "allowed" if self.allowed else "quota_exceeded",
                "retryable": True,
                "retry_after_seconds": 60,
            },
        )()


def test_create_client_returns_secret_once_and_stores_only_hash():
    async def run() -> None:
        repo = FakeEmbedRepository()
        result = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )

        assert result.client_secret
        assert repo.client.secret_hash != result.client_secret
        assert repo.client.secret_hash.startswith("scrypt$")

    asyncio.run(run())


def test_token_exchange_rejects_wrong_secret_and_unbound_agent():
    async def run() -> None:
        repo = FakeEmbedRepository()
        created = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )
        request = EmbedTokenRequest(
            client_id=created.client.client_id,
            client_secret="wrong",
            agent_id=11,
            external_user_id="user_1",
            origin="https://app.acme.test",
        )

        with pytest.raises(UnauthorizedException):
            await issue_embed_token(repo, FakeAgentRepository(), request, platform_id=7)

    asyncio.run(run())


def test_token_exchange_contains_scoped_claims_and_creates_external_user():
    async def run() -> None:
        repo = FakeEmbedRepository()
        created = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )
        token = await issue_embed_token(
            repo,
            FakeAgentRepository(),
            EmbedTokenRequest(
                client_id=created.client.client_id,
                client_secret=created.client_secret,
                agent_id=11,
                external_user_id="user_1",
                display_name="Alice",
                origin="https://app.acme.test",
                host_tool_names=["get_weather", "calculate_total"],
            ),
            platform_id=7,
        )

        assert token.access_token
        assert token.expires_in == 600
        assert repo.created_end_users[0]["external_user_id"] == "user_1"
        claims = decode_embed_token(token.access_token)
        assert claims["host_tools"] == ["calculate_total", "get_weather"]

    asyncio.run(run())


def test_token_exchange_includes_client_temporary_tool_capability():
    async def run() -> None:
        repo = FakeEmbedRepository()
        created = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )
        repo.client.allow_temporary_tools = True
        token = await issue_embed_token(
            repo,
            FakeAgentRepository(),
            EmbedTokenRequest(
                client_id=created.client.client_id,
                client_secret=created.client_secret,
                agent_id=11,
                external_user_id="user_1",
                origin="https://app.acme.test",
            ),
            platform_id=7,
        )

        assert decode_embed_token(token.access_token)["temporary_tools"] is True

    asyncio.run(run())


def test_token_exchange_rejects_before_creating_end_user_when_quota_exceeded():
    async def run() -> None:
        repo = FakeEmbedRepository()
        created = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )
        quota = FakeTokenQuota(allowed=False)

        with pytest.raises(TooManyRequestsException, match="quota_exceeded"):
            await issue_embed_token(
                repo,
                FakeAgentRepository(),
                EmbedTokenRequest(
                    client_id=created.client.client_id,
                    client_secret=created.client_secret,
                    agent_id=11,
                    external_user_id="blocked-user",
                    origin="https://app.acme.test",
                ),
                platform_id=7,
                quota_service=quota,
            )

        assert repo.created_end_users == []
        assert quota.calls[0][0] == "token_issue"

    asyncio.run(run())
