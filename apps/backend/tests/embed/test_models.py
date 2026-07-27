import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.agent.models import Agent
from app.modules.embed.models import (
    PlatformEmbedClient,
    PlatformEmbedClientAgent,
    PlatformEndUser,
)
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    BaseModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        BaseModel.metadata.drop_all(engine)


def test_embed_client_and_agent_binding_are_unique(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        session.add(platform)
        session.flush()
        agent = Agent(platform_id=platform.id, name="Support", slug="support")
        client = PlatformEmbedClient(
            platform=platform,
            client_id="client_acme",
            name="Acme Web",
            secret_hash="hash",
            allowed_origins=["https://app.acme.test"],
        )
        session.add_all([agent, client])
        session.commit()

        session.add(PlatformEmbedClientAgent(client=client, agent_id=agent.id))
        session.commit()
        session.add(PlatformEmbedClientAgent(client=client, agent_id=agent.id))

        with pytest.raises(IntegrityError):
            session.commit()


def test_platform_end_user_external_id_is_unique_per_platform(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        session.add(platform)
        session.commit()

        session.add_all(
            [
                PlatformEndUser(
                    platform=platform,
                    external_user_id="user_1",
                    display_name="Alice",
                ),
                PlatformEndUser(
                    platform=platform,
                    external_user_id="user_1",
                    display_name="Duplicate",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_client_secret_hash_is_persisted_without_plaintext_secret(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        client = PlatformEmbedClient(
            platform=platform,
            client_id="client_acme",
            name="Acme Web",
            secret_hash="argon2$hash",
            allowed_origins=["https://app.acme.test"],
        )
        session.add_all([platform, client])
        session.commit()

        stored = session.get(PlatformEmbedClient, client.id)
        assert stored.secret_hash == "argon2$hash"
        assert not hasattr(stored, "secret")
