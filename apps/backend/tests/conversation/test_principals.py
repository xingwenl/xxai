import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.agent.models import Agent
from app.modules.conversation.models import Conversation
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.modules.user.models import User
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


def test_conversation_requires_exactly_one_principal(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        session.add(platform)
        session.flush()
        agent = Agent(platform_id=platform.id, name="Support", slug="support")
        user = User(
            name="Admin",
            email="admin@acme.test",
            account="admin",
            password="password",
        )
        end_user = PlatformEndUser(
            platform=platform,
            external_user_id="external_1",
        )
        session.add_all([agent, user, end_user])
        session.commit()

        session.add(
            Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=user.id,
                platform_end_user_id=end_user.id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_internal_conversation_still_accepts_internal_user(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        session.add(platform)
        session.flush()
        agent = Agent(platform_id=platform.id, name="Support", slug="support")
        user = User(
            name="Admin",
            email="admin@acme.test",
            account="admin",
            password="password",
        )
        session.add_all([agent, user])
        session.commit()

        conversation = Conversation(
            platform_id=platform.id,
            agent_id=agent.id,
            user_id=user.id,
        )
        session.add(conversation)
        session.commit()

        assert conversation.platform_end_user_id is None


def test_external_conversation_accepts_platform_end_user(database):
    with Session(database) as session:
        platform = Platform(name="Acme", code="acme")
        session.add(platform)
        session.flush()
        agent = Agent(platform_id=platform.id, name="Support", slug="support")
        end_user = PlatformEndUser(
            platform=platform,
            external_user_id="external_1",
        )
        session.add_all([agent, end_user])
        session.commit()

        conversation = Conversation(
            platform_id=platform.id,
            agent_id=agent.id,
            platform_end_user_id=end_user.id,
        )
        session.add(conversation)
        session.commit()

        assert conversation.user_id is None
