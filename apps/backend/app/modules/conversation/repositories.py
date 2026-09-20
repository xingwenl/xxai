from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)

# 会话软删除状态。删除只改这一个字段，消息、附件与用量记录全部保留，
# 因此不存在级联销毁账单数据的路径，也不需要数据迁移。
CONVERSATION_STATUS_ACTIVE = "active"
CONVERSATION_STATUS_DELETED = "deleted"


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
            # 软删除会话不可再被解析：否则用户删掉会话后继续发消息会让它
            # 从列表之外“复活”，删除语义失效。
            Conversation.status != CONVERSATION_STATUS_DELETED,
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

    def _principal_filters(
        self,
        platform_id: int,
        agent_id: int,
        *,
        end_user_id: int,
    ) -> list:
        """构造会话列表的隔离条件。

        平台、Agent 与最终用户三者缺一不可，任何一项缺失都会横向泄露
        其他主体的会话，因此集中在这里供列表与计数复用。
        """
        return [
            Conversation.platform_id == platform_id,
            Conversation.agent_id == agent_id,
            Conversation.platform_end_user_id == end_user_id,
            Conversation.status != CONVERSATION_STATUS_DELETED,
        ]

    async def list_for_principal(
        self,
        platform_id: int,
        agent_id: int,
        *,
        end_user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> list[tuple[Conversation, int, str | None]]:
        """按主体列出会话，按创建时间倒序分页。

        返回 (会话, 消息数, 末条消息摘要) 三元组；摘要与计数用一次带
        关联子查询的查询取回，避免逐会话再查一次造成 N+1。
        """
        last_message_id = (
            select(func.max(ConversationMessage.id))
            .where(ConversationMessage.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        statement = (
            select(
                Conversation,
                select(func.count(ConversationMessage.id))
                .where(ConversationMessage.conversation_id == Conversation.id)
                .correlate(Conversation)
                .scalar_subquery()
                .label("message_count"),
                select(ConversationMessage.content)
                .where(ConversationMessage.id == last_message_id)
                .scalar_subquery()
                .label("last_message_preview"),
            )
            .where(*self._principal_filters(platform_id, agent_id, end_user_id=end_user_id))
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(statement)
        return [
            (conversation, int(message_count or 0), last_message_preview)
            for conversation, message_count, last_message_preview in result.all()
        ]

    async def count_for_principal(
        self,
        platform_id: int,
        agent_id: int,
        *,
        end_user_id: int,
    ) -> int:
        """统计主体下的可用会话总数，供分页元信息使用。"""
        total = await self.session.scalar(
            select(func.count(Conversation.id)).where(
                *self._principal_filters(platform_id, agent_id, end_user_id=end_user_id)
            )
        )
        return int(total or 0)

    async def soft_delete_for_principal(
        self,
        conversation_id: int,
        platform_id: int,
        *,
        end_user_id: int,
    ) -> bool:
        """把本主体的会话标记为已删除，返回是否命中。

        只改状态字段：消息、Loop、附件与 model_usage_records 一律保留，
        因此不存在级联删除账单数据的路径；重复删除幂等返回 False。
        """
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.platform_id == platform_id,
                Conversation.platform_end_user_id == end_user_id,
                Conversation.status != CONVERSATION_STATUS_DELETED,
            )
        )
        if conversation is None:
            return False
        conversation.status = CONVERSATION_STATUS_DELETED
        await self.session.commit()
        return True

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
