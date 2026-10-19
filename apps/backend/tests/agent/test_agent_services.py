import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import get_settings
from app.modules.agent.schemas import AgentCreate, AgentVersionCreate
from app.modules.agent.services import (
    build_chat_model,
    create_agent,
    create_agent_version,
    decrypt_secret,
    encrypt_secret,
    publish_agent_version,
    rollback_agent,
)
from app.modules.model_registry.resolver import ResolvedModel


@dataclass
class FakeAgent:
    id: int
    platform_id: int
    name: str
    slug: str
    default_version_id: int | None = None


@dataclass
class FakeVersion:
    id: int
    agent_id: int
    version: int
    system_prompt: str
    temperature: float = 0.2
    model_options: dict | None = None
    published_at: datetime | None = None


class FakeAgentRepository:
    def __init__(self) -> None:
        self.agents: list[FakeAgent] = []
        self.versions: list[FakeVersion] = []

    async def get_by_slug(self, platform_id: int, slug: str):
        return next(
            (a for a in self.agents if a.platform_id == platform_id and a.slug == slug),
            None,
        )

    async def create_agent(self, payload, platform_id: int):
        agent = FakeAgent(len(self.agents) + 1, platform_id, payload.name, payload.slug)
        self.agents.append(agent)
        return agent

    async def get_agent(self, agent_id: int, platform_id: int):
        return next(
            (
                a
                for a in self.agents
                if a.id == agent_id and a.platform_id == platform_id
            ),
            None,
        )

    async def create_version(self, agent_id: int, payload):
        version = FakeVersion(
            len(self.versions) + 1,
            agent_id,
            len([v for v in self.versions if v.agent_id == agent_id]) + 1,
            payload.system_prompt,
            payload.temperature,
            payload.model_options,
        )
        self.versions.append(version)
        return version

    async def publish_version(self, agent, version_id: int):
        version = next(v for v in self.versions if v.id == version_id)
        version.published_at = datetime.now(UTC)
        agent.default_version_id = version.id
        return version

    async def rollback(self, agent, version_id: int):
        return await self.publish_version(agent, version_id)


def test_encrypt_secret_can_round_trip_without_exposing_plaintext() -> None:
    encrypted = encrypt_secret("sk-test", master_key="test-master")

    assert encrypted != "sk-test"
    assert decrypt_secret(encrypted, master_key="test-master") == "sk-test"


def test_publish_and_rollback_select_agent_version() -> None:
    async def run() -> None:
        repo = FakeAgentRepository()
        agent = await create_agent(
            repo, AgentCreate(name="客服", slug="support"), platform_id=1
        )
        first = await agent_version(repo, agent.id, "first")
        second = await agent_version(repo, agent.id, "second")

        await publish_agent_version(repo, agent.id, first.id, platform_id=1)
        assert agent.default_version_id == first.id
        await rollback_agent(repo, agent.id, second.id, platform_id=1)
        assert agent.default_version_id == second.id

    asyncio.run(run())


def test_create_version_keeps_model_credentials_out_of_version() -> None:
    """模型三要素归平台模型注册表；版本只保存提示词与采样参数。"""
    fields = AgentVersionCreate.model_fields
    assert "model_name" not in fields
    assert "model_base_url" not in fields
    assert "api_key" not in fields

    async def run() -> None:
        repo = FakeAgentRepository()
        agent = await create_agent(
            repo, AgentCreate(name="客服", slug="support"), platform_id=1
        )

        version = await create_agent_version(
            repo,
            agent.id,
            AgentVersionCreate(system_prompt="help", temperature=0.3),
            platform_id=1,
        )

        assert version.system_prompt == "help"
        assert version.temperature == 0.3

    asyncio.run(run())


def test_build_chat_model_uses_resolved_credentials() -> None:
    """模型名/地址/密钥取自解析结果；版本行只贡献温度与模型参数。"""
    version = FakeVersion(
        id=1,
        agent_id=1,
        version=1,
        system_prompt="help",
        temperature=0.1,
    )

    model = build_chat_model(
        version,
        resolved=ResolvedModel(
            model_name="gpt-4o-mini",
            base_url="https://example.test/v1",
            api_key="sk-runtime",
            capabilities=None,
            options={},
        ),
    )

    assert model.model_name == "gpt-4o-mini"
    assert model.openai_api_key.get_secret_value() == "sk-runtime"
    assert str(model.openai_api_base) == "https://example.test/v1"
    assert model.request_timeout == 60
    assert model.stream_chunk_timeout == 60
    assert model.max_retries == 0


def test_build_chat_model_falls_back_to_env_defaults_when_unbound() -> None:
    """未绑定对话模型时回落到环境变量默认三要素，保住零配置可用。"""
    version = FakeVersion(
        id=1, agent_id=1, version=1, system_prompt="help", temperature=0.2
    )

    model = build_chat_model(version, resolved=None)

    settings = get_settings()
    assert model.model_name == settings.model_default_name
    assert model.openai_api_key.get_secret_value() == settings.openai_api_key


async def agent_version(repo, agent_id: int, prompt: str):
    return await repo.create_version(
        agent_id,
        AgentVersionCreate(system_prompt=prompt),
    )
