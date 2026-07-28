from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.models import Conversation, ConversationMessage


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, conversation_id: int, platform_id: int, user_id: int):
        return await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.platform_id == platform_id,
                Conversation.user_id == user_id,
            )
        )

    async def get_for_principal(
        self,
        conversation_id: int,
        platform_id: int,
        *,
        user_id: int | None = None,
        end_user_id: int | None = None,
    ):
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.platform_id == platform_id,
        )
        if user_id is not None:
            statement = statement.where(Conversation.user_id == user_id)
        elif end_user_id is not None:
            statement = statement.where(
                Conversation.platform_end_user_id == end_user_id
            )
        else:
            return None
        return await self.session.scalar(statement)

    async def create(self, platform_id: int, agent_id: int, user_id: int, title: str):
        conversation = Conversation(
            platform_id=platform_id,
            agent_id=agent_id,
            user_id=user_id,
            title=title[:255],
        )
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def create_for_principal(
        self,
        platform_id: int,
        agent_id: int,
        *,
        user_id: int | None = None,
        end_user_id: int | None = None,
        title: str,
    ):
        conversation = Conversation(
            platform_id=platform_id,
            agent_id=agent_id,
            user_id=user_id,
            platform_end_user_id=end_user_id,
            title=title[:255],
        )
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def list_messages(self, conversation_id: int):
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        )
        return list(result.scalars().all())

    async def list_messages_for_principal(
        self, conversation_id: int, platform_id: int, *, end_user_id: int
    ):
        conversation = await self.get_for_principal(
            conversation_id, platform_id, end_user_id=end_user_id
        )
        if conversation is None:
            return None
        return await self.list_messages(conversation.id)

    async def create_message(self, conversation_id: int, **values):
        message = ConversationMessage(conversation_id=conversation_id, **values)
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message
