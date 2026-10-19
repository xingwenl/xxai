"""模型注册表仓储、服务与解析器测试。"""

import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.agent.services import decrypt_secret
from app.modules.model_registry.repositories import (
    AgentModelBindingRepository,
    ModelRegistryRepository,
)
from app.modules.model_registry.resolver import resolve_agent_model, resolve_chat_model
from app.modules.model_registry.schemas import (
    AgentModelBindingsUpdate,
    AgentModelBindingUpdateItem,
    BindingRole,
    PlatformModelCreate,
)
from app.modules.model_registry.services import (
    create_platform_model,
    delete_platform_model,
    replace_agent_bindings,
)
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel
from app.shared.exceptions import BadRequestException, ConflictException


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session, *, platform_code="acme", agent_slug="support"):
    platform = Platform(name="Acme", code=platform_code)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="客服", slug=agent_slug)
    session.add(agent)
    await session.commit()
    await session.refresh(platform)
    await session.refresh(agent)
    return platform.id, agent.id


def test_create_model_encrypts_api_key_and_resolver_decrypts():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            repo = ModelRegistryRepository(session)
            model = await create_platform_model(
                repo,
                PlatformModelCreate(
                    name="生图模型",
                    model_type="image_generate",
                    model_name="gpt-image-1",
                    api_key="secret-key",
                    capabilities={"output": "image"},
                ),
                platform_id=platform_id,
            )
            assert model.api_key_encrypted is not None
            assert decrypt_secret(model.api_key_encrypted) == "secret-key"
            assert model.api_key_encrypted != "secret-key"

            resolved = await resolve_agent_model(
                session,
                platform_id=platform_id,
                agent_id=agent_id,
                role="image_generate",
            )
            assert resolved is None  # 未绑定前解析不到
        await engine.dispose()

    asyncio.run(run())


def test_duplicate_model_type_and_name_conflict():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, _ = await _seed(session)
            repo = ModelRegistryRepository(session)
            payload = PlatformModelCreate(
                name="读图模型",
                model_type="image_read",
                model_name="gpt-4o",
            )
            await create_platform_model(repo, payload, platform_id=platform_id)
            try:
                await create_platform_model(repo, payload, platform_id=platform_id)
            except ConflictException:
                return
            raise AssertionError("expected ConflictException")
        await engine.dispose()

    asyncio.run(run())


def test_replace_bindings_validates_role_and_model_type():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            model = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="聊天模型",
                    model_type="chat",
                    model_name="gpt-4o-mini",
                ),
                platform_id=platform_id,
            )
            payload = AgentModelBindingsUpdate(
                bindings=[
                    AgentModelBindingUpdateItem(
                        role=BindingRole.EMBEDDING, model_id=model.id
                    )
                ]
            )
            try:
                await replace_agent_bindings(
                    binding_repo,
                    model_repo,
                    agent_id=agent_id,
                    platform_id=platform_id,
                    payload=payload,
                )
            except BadRequestException:
                return
            raise AssertionError("expected BadRequestException")
        await engine.dispose()

    asyncio.run(run())


def test_replace_bindings_rejects_duplicate_role():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            first = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="嵌入一",
                    model_type="embedding",
                    model_name="text-embedding-3-small",
                ),
                platform_id=platform_id,
            )
            second = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="嵌入二",
                    model_type="embedding",
                    model_name="text-embedding-3-large",
                ),
                platform_id=platform_id,
            )
            payload = AgentModelBindingsUpdate(
                bindings=[
                    AgentModelBindingUpdateItem(
                        role=BindingRole.EMBEDDING, model_id=first.id
                    ),
                    AgentModelBindingUpdateItem(
                        role=BindingRole.EMBEDDING, model_id=second.id
                    ),
                ]
            )
            try:
                await replace_agent_bindings(
                    binding_repo,
                    model_repo,
                    agent_id=agent_id,
                    platform_id=platform_id,
                    payload=payload,
                )
            except BadRequestException:
                return
            raise AssertionError("expected BadRequestException")
        await engine.dispose()

    asyncio.run(run())


def test_bound_model_is_resolved_and_delete_bound_model_conflicts():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            model = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="嵌入模型",
                    model_type="embedding",
                    model_name="text-embedding-3-small",
                    base_url="https://ollama.local/v1",
                    api_key="embed-key",
                ),
                platform_id=platform_id,
            )
            await replace_agent_bindings(
                binding_repo,
                model_repo,
                agent_id=agent_id,
                platform_id=platform_id,
                payload=AgentModelBindingsUpdate(
                    bindings=[
                        AgentModelBindingUpdateItem(
                            role=BindingRole.EMBEDDING, model_id=model.id
                        )
                    ]
                ),
            )

            resolved = await resolve_agent_model(
                session,
                platform_id=platform_id,
                agent_id=agent_id,
                role="embedding",
            )
            assert resolved is not None
            assert resolved.model_name == "text-embedding-3-small"
            assert resolved.api_key == "embed-key"
            assert resolved.base_url == "https://ollama.local/v1"

            try:
                await delete_platform_model(model_repo, model)
            except ConflictException:
                return
            raise AssertionError("expected ConflictException")
        await engine.dispose()

    asyncio.run(run())


def test_replace_bindings_swaps_existing_role_binding():
    """整体替换必须能换掉已有绑定：(agent_id, role) 上的唯一约束要求先 DELETE 再 INSERT。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            first = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="旧对话模型", model_type="chat", model_name="old-chat-model"
                ),
                platform_id=platform_id,
            )
            second = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="新对话模型", model_type="chat", model_name="new-chat-model"
                ),
                platform_id=platform_id,
            )
            await replace_agent_bindings(
                binding_repo,
                model_repo,
                agent_id=agent_id,
                platform_id=platform_id,
                payload=AgentModelBindingsUpdate(
                    bindings=[
                        AgentModelBindingUpdateItem(
                            role=BindingRole.CHAT, model_id=first.id
                        )
                    ]
                ),
            )
            await replace_agent_bindings(
                binding_repo,
                model_repo,
                agent_id=agent_id,
                platform_id=platform_id,
                payload=AgentModelBindingsUpdate(
                    bindings=[
                        AgentModelBindingUpdateItem(
                            role=BindingRole.CHAT, model_id=second.id
                        )
                    ]
                ),
            )

            bindings = await binding_repo.list_for_agent(agent_id)
            assert [(item.role, item.model_id) for item in bindings] == [
                ("chat", second.id)
            ]
            resolved = await resolve_chat_model(
                session, platform_id=platform_id, agent_id=agent_id
            )
            assert resolved is not None
            assert resolved.model_name == "new-chat-model"
        await engine.dispose()

    asyncio.run(run())


def test_replace_bindings_rejects_inactive_model():
    """停用模型不能被绑定：替换入口直接拒绝，避免先绑再停用之外的后门。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            model = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="停用对话模型",
                    model_type="chat",
                    model_name="inactive-chat-model",
                    is_active=False,
                ),
                platform_id=platform_id,
            )
            try:
                await replace_agent_bindings(
                    binding_repo,
                    model_repo,
                    agent_id=agent_id,
                    platform_id=platform_id,
                    payload=AgentModelBindingsUpdate(
                        bindings=[
                            AgentModelBindingUpdateItem(
                                role=BindingRole.CHAT, model_id=model.id
                            )
                        ]
                    ),
                )
            except BadRequestException as exc:
                assert "model_not_active" in str(exc)
                return
            raise AssertionError("expected BadRequestException")
        await engine.dispose()

    asyncio.run(run())


def test_inactive_model_is_not_resolved():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform_id, agent_id = await _seed(session)
            model_repo = ModelRegistryRepository(session)
            binding_repo = AgentModelBindingRepository(session)
            model = await create_platform_model(
                model_repo,
                PlatformModelCreate(
                    name="读图模型",
                    model_type="image_read",
                    model_name="gpt-4o",
                    api_key="read-key",
                ),
                platform_id=platform_id,
            )
            await replace_agent_bindings(
                binding_repo,
                model_repo,
                agent_id=agent_id,
                platform_id=platform_id,
                payload=AgentModelBindingsUpdate(
                    bindings=[
                        AgentModelBindingUpdateItem(
                            role=BindingRole.IMAGE_READ, model_id=model.id
                        )
                    ]
                ),
            )
            await model_repo.update(model, is_active=False)

            resolved = await resolve_agent_model(
                session,
                platform_id=platform_id,
                agent_id=agent_id,
                role="image_read",
            )
            assert resolved is None
        await engine.dispose()

    asyncio.run(run())
