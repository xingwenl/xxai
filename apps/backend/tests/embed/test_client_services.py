import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import jwt
import pytest

from app.core.config import get_settings
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
    allow_agent_switching: bool = False


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
        matched = next(
            (
                item
                for item in self.created_end_users
                if item["platform_id"] == platform_id
                and item["external_user_id"] == external_user_id
            ),
            None,
        )
        # 仓储替身内部按 dict 记账便于断言，但返回给服务的必须是对象。
        return SimpleNamespace(**matched) if matched is not None else None

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


def test_create_client_persists_agent_switching_toggle():
    """智能体切换开关是平台策略：创建时必须落库，缺省值为关闭。"""

    async def run() -> None:
        repo = FakeEmbedRepository()
        default_client = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web", allowed_origins=["https://app.acme.test"]
            ),
        )
        assert default_client.client.allow_agent_switching is False

        enabled_client = await create_embed_client(
            repo,
            platform_id=7,
            payload=PlatformEmbedClientCreate(
                name="Acme Web",
                allowed_origins=["https://app.acme.test"],
                allow_agent_switching=True,
            ),
        )
        assert enabled_client.client.allow_agent_switching is True

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


def test_trusted_entry_token_carries_backend_user_claim():
    """受信任入口签发的 token 带 user_id；公开兑换入口不带。"""

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
            client_secret=created.client_secret,
            agent_id=11,
            external_user_id="admin-1",
            origin="https://app.acme.test",
        )

        public = await issue_embed_token(
            repo, FakeAgentRepository(), request, platform_id=7
        )
        assert "user_id" not in decode_embed_token(public.access_token)

        trusted = await issue_embed_token(
            repo, FakeAgentRepository(), request, platform_id=7, user_id=1
        )
        assert decode_embed_token(trusted.access_token)["user_id"] == 1

    asyncio.run(run())


def test_decode_rejects_malformed_user_claim():
    """user_id 只接受正整数：字符串、布尔值、0 都必须当作坏 token 拒绝。"""

    async def run() -> None:
        settings = get_settings()
        for bad in ("1", True, 0, -3):
            now = datetime.now(UTC)
            token = jwt.encode(
                {
                    "iss": settings.embed_token_issuer,
                    "aud": settings.embed_token_audience,
                    "sub": "65",
                    "platform_id": 1,
                    "agent_id": 11,
                    "client_id": "client-x",
                    "origin": "https://app.acme.test",
                    "host_tools": [],
                    "temporary_tools": False,
                    "protocol_version": 1,
                    "jti": "jti-x",
                    "iat": now,
                    "nbf": now,
                    "exp": now.timestamp() + 60,
                    "user_id": bad,
                },
                settings.embed_jwt_secret_key,
                algorithm=settings.embed_jwt_algorithm,
            )
            with pytest.raises(UnauthorizedException):
                decode_embed_token(token)

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
