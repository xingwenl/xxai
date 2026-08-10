from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)


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

    async def list_recent_context_messages(
        self, conversation_id: int, *, since: datetime
    ):
        """读取可安全回填模型上下文的近期已完成消息。"""
        result = await self.session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.created_at >= since,
                ConversationMessage.status == "completed",
                ConversationMessage.role.in_(("user", "assistant", "tool")),
            )
            .order_by(ConversationMessage.created_at, ConversationMessage.id)
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

    async def create_loop(self, conversation_id: int, **values):
        loop = AgentLoopRun(conversation_id=conversation_id, **values)
        self.session.add(loop)
        await self.session.flush()
        return loop

    async def create_loop_step(self, loop_run_id: int, **values):
        step = AgentLoopStep(loop_run_id=loop_run_id, **values)
        self.session.add(step)
        await self.session.flush()
        return step

    async def save_loop(self, loop: AgentLoopRun):
        await self.session.commit()
        await self.session.refresh(loop)
        return loop

    async def list_loop_steps(self, loop_run_id: int):
        result = await self.session.execute(
            select(AgentLoopStep)
            .where(AgentLoopStep.loop_run_id == loop_run_id)
            .order_by(AgentLoopStep.sequence, AgentLoopStep.id)
        )
        return list(result.scalars().all())

    async def list_loops(self, conversation_id: int):
        result = await self.session.execute(
            select(AgentLoopRun)
            .where(AgentLoopRun.conversation_id == conversation_id)
            .order_by(AgentLoopRun.id)
        )
        return list(result.scalars().all())

    async def get_loop(self, loop_id: int, conversation_id: int):
        return await self.session.scalar(
            select(AgentLoopRun).where(
                AgentLoopRun.id == loop_id,
                AgentLoopRun.conversation_id == conversation_id,
            )
        )

    async def record_model_usage(self, **values):
        record = ModelUsageRecord(**values)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record
