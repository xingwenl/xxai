from datetime import datetime
from typing import NamedTuple

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)
from app.modules.embed.models import PlatformEndUser
from app.modules.user.models import User

# 会话软删除状态。删除只改这一个字段，消息、附件与用量记录全部保留，
# 因此不存在级联销毁账单数据的路径，也不需要数据迁移。
CONVERSATION_STATUS_ACTIVE = "active"
CONVERSATION_STATUS_DELETED = "deleted"

# 会话主体的两种类型，与 CheckConstraint
# `ck_conversations_exactly_one_principal` 的两个分支一一对应。
PRINCIPAL_TYPE_USER = "user"
PRINCIPAL_TYPE_END_USER = "end_user"


class ConsoleConversationRow(NamedTuple):
    """后台会话列表/详情的一行：会话实体 + 显示名与统计。"""

    conversation: Conversation
    message_count: int
    last_message_preview: str | None
    last_message_at: datetime | None
    agent_name: str | None
    principal_type: str
    principal_id: int
    principal_name: str | None


class ConversationPrincipalRow(NamedTuple):
    """会话主体聚合项：某主体在本平台的会话数与最近活跃时间。"""

    principal_type: str
    principal_id: int
    display_name: str | None
    conversation_count: int
    last_conversation_at: datetime | None


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

    # ------------------------------------------------------------------
    # 后台会话记录（平台级只读视图）
    #
    # 与上面按主体隔离的方法不同：这里的强隔离条件只有平台一项，其余维度都是
    # 管理员主动下钻的筛选项。所有查询都必须带上 platform_id，调用方无法通过
    # 参数拼出跨平台的读取路径。
    # ------------------------------------------------------------------

    def _console_status_filters(self, *, status: str | None, include_deleted: bool) -> list:
        """决定会话状态过滤：默认排除软删除，显式指定状态时按值过滤。"""
        if include_deleted:
            return []
        if status is None:
            return [Conversation.status != CONVERSATION_STATUS_DELETED]
        return [Conversation.status == status]

    def _platform_filters(
        self,
        platform_id: int,
        *,
        agent_id: int | None = None,
        principal_type: str | None = None,
        principal_id: int | None = None,
        status: str | None = None,
        include_deleted: bool = False,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        keyword: str | None = None,
        last_message_content=None,
    ) -> list:
        """构造后台会话查询的过滤条件。

        平台是唯一的强隔离条件；Agent、主体、状态、时间与关键字都是可选下钻。
        关键字同时匹配会话标题与末条消息摘要（后者以相关子查询的形式由调用方
        传入，见 `_console_conversation_statement`），不做正文全文检索。
        """
        filters = [Conversation.platform_id == platform_id]
        filters.extend(
            self._console_status_filters(status=status, include_deleted=include_deleted)
        )
        if agent_id is not None:
            filters.append(Conversation.agent_id == agent_id)
        if principal_type == PRINCIPAL_TYPE_USER and principal_id is not None:
            filters.append(Conversation.user_id == principal_id)
        elif principal_type == PRINCIPAL_TYPE_END_USER and principal_id is not None:
            filters.append(Conversation.platform_end_user_id == principal_id)
        if start_at is not None:
            filters.append(Conversation.created_at >= start_at)
        if end_at is not None:
            filters.append(Conversation.created_at < end_at)
        pattern = f"%{(keyword or '').strip()}%"
        if pattern != "%%":
            conditions = [Conversation.title.ilike(pattern)]
            if last_message_content is not None:
                conditions.append(last_message_content.ilike(pattern))
            filters.append(or_(*conditions))
        return filters

    def _console_conversation_statement(self, platform_id: int, **filters):
        """后台会话列表与详情共用的查询：会话 + 统计 + 主体/Agent 显示名。

        消息条数、末条消息摘要与最后活跃时间都用相关子查询一次取回，避免逐会话
        再查（N+1）；主体显示名按「后台用户 → 终端用户显示名 → 终端用户外部 ID」
        回退，与 embed 侧的展示口径一致。
        """
        last_message_id = (
            select(func.max(ConversationMessage.id))
            .where(ConversationMessage.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        last_message_content = (
            select(ConversationMessage.content)
            .where(ConversationMessage.id == last_message_id)
            .scalar_subquery()
        )
        last_message_at = (
            select(func.max(ConversationMessage.created_at))
            .where(ConversationMessage.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        return (
            select(
                Conversation,
                select(func.count(ConversationMessage.id))
                .where(ConversationMessage.conversation_id == Conversation.id)
                .correlate(Conversation)
                .scalar_subquery()
                .label("message_count"),
                last_message_content.label("last_message_preview"),
                last_message_at.label("last_message_at"),
                Agent.name.label("agent_name"),
                case(
                    (Conversation.user_id.is_not(None), literal_column("'user'")),
                    else_=literal_column("'end_user'"),
                ).label("principal_type"),
                func.coalesce(
                    Conversation.user_id, Conversation.platform_end_user_id
                ).label("principal_id"),
                func.coalesce(
                    User.name,
                    PlatformEndUser.display_name,
                    PlatformEndUser.external_user_id,
                ).label("principal_name"),
            )
            .outerjoin(Agent, Agent.id == Conversation.agent_id)
            .outerjoin(User, User.id == Conversation.user_id)
            .outerjoin(
                PlatformEndUser, PlatformEndUser.id == Conversation.platform_end_user_id
            )
            .where(
                *self._platform_filters(
                    platform_id, last_message_content=last_message_content, **filters
                )
            )
        )

    @staticmethod
    def _console_row(row) -> ConsoleConversationRow:
        """把一行查询结果还原成带显示名与统计的会话行。"""
        return ConsoleConversationRow(
            conversation=row[0],
            message_count=int(row[1] or 0),
            last_message_preview=row[2],
            last_message_at=row[3],
            agent_name=row[4],
            principal_type=row[5],
            principal_id=int(row[6]),
            principal_name=row[7],
        )

    async def list_for_platform(
        self, platform_id: int, *, page: int = 1, page_size: int = 20, **filters
    ) -> list[ConsoleConversationRow]:
        """分页取平台下的会话，最近创建的在前。"""
        result = await self.session.execute(
            self._console_conversation_statement(platform_id, **filters)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
        return [self._console_row(row) for row in result.all()]

    async def count_for_platform(self, platform_id: int, **filters) -> int:
        """平台下满足同一组筛选条件的会话总数（供分页信封使用）。"""
        statement = self._console_conversation_statement(platform_id, **filters)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return int(total or 0)

    async def get_for_platform(
        self, conversation_id: int, platform_id: int, **filters
    ) -> ConsoleConversationRow | None:
        """取单个会话；不属于该平台时返回 None，由服务层转成 404。"""
        result = await self.session.execute(
            self._console_conversation_statement(platform_id, **filters).where(
                Conversation.id == conversation_id
            )
        )
        row = result.first()
        return None if row is None else self._console_row(row)

    async def usage_for_conversation(
        self, conversation_id: int
    ) -> tuple[int, int, int, int]:
        """会话级用量汇总，取自 model_usage_records（计费事实来源）。

        返回 (prompt_tokens, completion_tokens, total_tokens, record_count)。
        """
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(ModelUsageRecord.prompt_tokens), 0),
                    func.coalesce(func.sum(ModelUsageRecord.completion_tokens), 0),
                    func.coalesce(func.sum(ModelUsageRecord.total_tokens), 0),
                    func.count(ModelUsageRecord.id),
                ).where(ModelUsageRecord.conversation_id == conversation_id)
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)

    async def soft_delete_for_platform(self, conversation_id: int, platform_id: int) -> bool:
        """后台软删除会话：只改状态，消息与用量记录一律保留。

        非本平台或已删除返回 False，由服务层统一转成 404——与 embed 侧
        「不泄露他平台会话是否存在」的语义保持一致。
        """
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.platform_id == platform_id,
                Conversation.status != CONVERSATION_STATUS_DELETED,
            )
        )
        if conversation is None:
            return False
        conversation.status = CONVERSATION_STATUS_DELETED
        await self.session.commit()
        return True

    def _principal_aggregate(
        self,
        platform_id: int,
        *,
        status: str | None = None,
        include_deleted: bool = False,
    ):
        """把两个主体分支 UNION ALL 成一张按主体聚合的派生表。

        后台用户与终端用户存在 `conversations` 的两个不同列里，用 UNION ALL +
        GROUP BY 让数据库完成聚合与分页；若分别取回再在 Python 里合并，分页就
        必须先全量加载。再叠加同一个会话上的 `principal_type`/`principal_id`
        筛选时，聚合后的视图是逐会话过滤，不会改变计数口径。
        """
        base_filters = self._platform_filters(
            platform_id, status=status, include_deleted=include_deleted
        )
        user_branch = (
            select(
                literal_column("'user'").label("principal_type"),
                Conversation.user_id.label("principal_id"),
                func.count(Conversation.id).label("conversation_count"),
                func.max(Conversation.created_at).label("last_conversation_at"),
            )
            .where(*base_filters, Conversation.user_id.is_not(None))
            .group_by(Conversation.user_id)
        )
        end_user_branch = (
            select(
                literal_column("'end_user'").label("principal_type"),
                Conversation.platform_end_user_id.label("principal_id"),
                func.count(Conversation.id).label("conversation_count"),
                func.max(Conversation.created_at).label("last_conversation_at"),
            )
            .where(*base_filters, Conversation.platform_end_user_id.is_not(None))
            .group_by(Conversation.platform_end_user_id)
        )
        return user_branch.union_all(end_user_branch).subquery(
            "conversation_principal_aggregate"
        )

    def _principals_statement(
        self,
        platform_id: int,
        *,
        principal_type: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
    ):
        """会话主体列表查询：聚合结果外连主体表补显示名，并应用筛选。"""
        aggregate = self._principal_aggregate(
            platform_id, status=status, include_deleted=include_deleted
        )
        display_name = func.coalesce(
            User.name, PlatformEndUser.display_name, PlatformEndUser.external_user_id
        )
        statement = (
            select(
                aggregate.c.principal_type,
                aggregate.c.principal_id,
                display_name.label("display_name"),
                aggregate.c.conversation_count,
                aggregate.c.last_conversation_at,
            )
            .select_from(aggregate)
            .outerjoin(
                User,
                and_(
                    aggregate.c.principal_type == PRINCIPAL_TYPE_USER,
                    User.id == aggregate.c.principal_id,
                ),
            )
            .outerjoin(
                PlatformEndUser,
                and_(
                    aggregate.c.principal_type == PRINCIPAL_TYPE_END_USER,
                    PlatformEndUser.id == aggregate.c.principal_id,
                ),
            )
        )
        if principal_type in (PRINCIPAL_TYPE_USER, PRINCIPAL_TYPE_END_USER):
            statement = statement.where(aggregate.c.principal_type == principal_type)
        pattern = f"%{(keyword or '').strip()}%"
        if pattern != "%%":
            statement = statement.where(display_name.ilike(pattern))
        return statement, aggregate

    async def list_principals_for_platform(
        self,
        platform_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        principal_type: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
    ) -> list[ConversationPrincipalRow]:
        """分页取平台下「有会话」的主体，最近产生会话的在前。"""
        statement, aggregate = self._principals_statement(
            platform_id,
            principal_type=principal_type,
            keyword=keyword,
            status=status,
            include_deleted=include_deleted,
        )
        result = await self.session.execute(
            statement.order_by(
                aggregate.c.last_conversation_at.desc(), aggregate.c.principal_id.desc()
            )
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
        return [
            ConversationPrincipalRow(
                principal_type=row[0],
                principal_id=int(row[1]),
                display_name=row[2],
                conversation_count=int(row[3] or 0),
                last_conversation_at=row[4],
            )
            for row in result.all()
        ]

    async def count_principals_for_platform(
        self,
        platform_id: int,
        *,
        principal_type: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
    ) -> int:
        """平台下满足同一组筛选条件的主体总数。"""
        statement, _aggregate = self._principals_statement(
            platform_id,
            principal_type=principal_type,
            keyword=keyword,
            status=status,
            include_deleted=include_deleted,
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return int(total or 0)
