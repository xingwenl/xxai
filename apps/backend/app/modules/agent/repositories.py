from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent, AgentVersion, SubagentBinding
from app.modules.platform.models import PlatformAdmin
from app.modules.agent.schemas import AgentCreate, AgentUpdate, AgentVersionCreate
from app.modules.workflows.models import Workflow
from app.shared.pagination import PaginationParams, build_page_data
from app.shared.base_repository import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Agent)

    async def get_by_slug(self, platform_id: int, slug: str) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.platform_id == platform_id, Agent.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_orchestration_workflow(
        self, workflow_id: int, platform_id: int
    ) -> Workflow | None:
        """按平台取编排工作流，供绑定校验使用。

        必须限定 ``platform_id``：绑定关系决定「哪些终端用户的每轮消息会被这条
        工作流接管」，跨平台拿到别人的工作流等于把别人的提示词与工具接进自己的
        会话。这里只查纯模型，不引入 workflows 的服务层。
        """

        result = await self.session.execute(
            select(Workflow).where(
                Workflow.id == workflow_id,
                Workflow.platform_id == platform_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_agent(self, agent_id: int, platform_id: int) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        return result.scalar_one_or_none()

    async def get_default_agent(self, platform_id: int) -> Agent | None:
        """获取平台默认智能体（微信绑定未指定 agent_id 时使用）。"""
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.platform_id == platform_id,
                Agent.is_default.is_(True),
                Agent.default_version_id.is_not(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_agent_detail(self, agent_id: int, platform_id: int) -> Agent | None:
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        return result.scalar_one_or_none()

    async def list_agents(self, platform_id: int, params: PaginationParams):
        statement = (
            select(Agent)
            .where(Agent.platform_id == platform_id)
            .order_by(Agent.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(statement)
        items = list(result.scalars().all())
        total = await self.session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

    async def list_versions(self, agent_id: int):
        result = await self.session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version.desc())
        )
        return list(result.scalars().all())

    async def update_agent(self, agent: Agent, payload: AgentUpdate) -> Agent:
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(agent, key, value)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def delete_agent(self, agent: Agent) -> None:
        await self.session.delete(agent)
        await self.session.commit()

    async def get_published_agent(
        self, agent_id: int, platform_id: int
    ) -> Agent | None:
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.id == agent_id,
                Agent.platform_id == platform_id,
                Agent.default_version_id.is_not(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.default_version is None:
            return None
        return agent if agent.default_version.published_at is not None else None

    async def get_published_agent_by_id(self, agent_id: int) -> Agent | None:
        """按 ID 加载已发布智能体（服务端内部使用，不限定平台）。

        微信机器人等内部调用方只持有 agent_id，不归属某个平台用户，
        因此直接按全局唯一主键查询，不附加 platform_id 过滤。
        """
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.id == agent_id,
                Agent.default_version_id.is_not(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.default_version is None:
            return None
        return agent if agent.default_version.published_at is not None else None

    async def get_published_active_agent_by_slug(
        self, platform_id: int, slug: str
    ) -> Agent | None:
        """按 slug 取本平台「已发布且已启用」的智能体。

        「列入可派清单」与「真正被派生子运行」必须用同一个谓词判定，否则
        清单里出现的 Agent 会在执行时被拒（或反过来：清单没列出的却能派），
        所以两个入口都走这一个函数。
        """
        result = await self.session.execute(
            select(Agent)
            .join(AgentVersion, AgentVersion.id == Agent.default_version_id)
            .where(
                Agent.platform_id == platform_id,
                Agent.slug == slug,
                Agent.is_active.is_(True),
                AgentVersion.published_at.is_not(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_published_active_agents(
        self, platform_id: int, *, limit: int = 50
    ) -> list[Agent]:
        """列出本平台「已发布且已启用」的智能体，按 slug 排序。

        调用方是委派工具的描述注入：清单会进模型上下文，因此条数由调用方
        显式限制（``limit`` 在 SQL 层生效，不会先取全量再截断）。
        """
        result = await self.session.execute(
            select(Agent)
            .join(AgentVersion, AgentVersion.id == Agent.default_version_id)
            .where(
                Agent.platform_id == platform_id,
                Agent.is_active.is_(True),
                AgentVersion.published_at.is_not(None),
            )
            .order_by(Agent.slug.asc())
            .limit(max(1, limit))
        )
        return list(result.scalars().all())

    async def get_published_agent_for_user(self, agent_id: int, user_id: int):
        result = await self.session.execute(
            select(Agent)
            .join(PlatformAdmin, PlatformAdmin.platform_id == Agent.platform_id)
            .options(selectinload(Agent.default_version))
            .where(
                Agent.id == agent_id,
                PlatformAdmin.user_id == user_id,
                Agent.default_version_id.is_not(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None or agent.default_version is None:
            return None
        return agent if agent.default_version.published_at is not None else None

    async def create_agent(self, payload: AgentCreate, platform_id: int) -> Agent:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.platform_id == platform_id)
        )
        agent = Agent(
            platform_id=platform_id,
            is_default=(count or 0) == 0,
            **payload.model_dump(),
        )
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def create_version(
        self, agent_id: int, payload: AgentVersionCreate
    ) -> AgentVersion:
        latest = await self.session.scalar(
            select(func.max(AgentVersion.version)).where(
                AgentVersion.agent_id == agent_id
            )
        )
        values = payload.model_dump()
        version = AgentVersion(
            agent_id=agent_id,
            version=(latest or 0) + 1,
            created_at=datetime.now(UTC),
            **values,
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def get_version(self, agent_id: int, version_id: int) -> AgentVersion | None:
        result = await self.session.execute(
            select(AgentVersion).where(
                AgentVersion.id == version_id, AgentVersion.agent_id == agent_id
            )
        )
        return result.scalar_one_or_none()

    async def publish_version(self, agent: Agent, version_id: int) -> AgentVersion:
        version = await self.get_version(agent.id, version_id)
        if version is None:
            raise LookupError("agent version not found")
        version.published_at = datetime.now(UTC)
        agent.default_version_id = version.id
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def rollback(self, agent: Agent, version_id: int) -> AgentVersion:
        return await self.publish_version(agent, version_id)

    # ------------------------------------------------------------------
    # 子智能体绑定：主智能体能派给谁
    #
    # 读侧（配置页）与运行期（清单注入、派发校验）都从这里取数，保证「界面上
    # 看到的候选」与「真正能被派出去的 Agent」是同一个谓词，不会出现配置页有
    # 但模型派不动、或反过来清单外还能派的漂移。
    # ------------------------------------------------------------------

    async def list_subagent_bindings(self, parent_agent_id: int):
        """列出父智能体的全部绑定（含停用/已下线），并带子 Agent 的发布时间。

        返回 ``(绑定行, 子 Agent, published_at)``；``published_at`` 走 outerjoin，
        子 Agent 没有发布版本时它是 None——配置页据此提示「已取消发布」。
        """
        result = await self.session.execute(
            select(SubagentBinding, Agent, AgentVersion.published_at)
            .join(Agent, Agent.id == SubagentBinding.child_agent_id)
            .outerjoin(AgentVersion, AgentVersion.id == Agent.default_version_id)
            .where(SubagentBinding.parent_agent_id == parent_agent_id)
            .order_by(SubagentBinding.sort_order.asc(), SubagentBinding.id.asc())
        )
        return list(result.all())

    async def has_subagent_bindings(self, parent_agent_id: int) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(SubagentBinding)
            .where(SubagentBinding.parent_agent_id == parent_agent_id)
        )
        return bool(count)

    async def list_delegatable_agents(
        self, platform_id: int, parent_agent_id: int, *, limit: int = 50
    ) -> list[Agent]:
        """父智能体运行期可派的子智能体清单（候选口径的唯一实现）。

        有绑定：只取绑定内「开关启用 + 已发布 + 已启用」的子 Agent，按绑定排序；
        没有任何绑定：回退到全平台已发布智能体（排除父自己），即本功能上线前的
        老口径，存量 Agent 行为不变。

        注意判断依据是「有没有绑定行」而不是「绑定内有没有可用行」：一旦配了
        绑定，子 Agent 取消发布或停用就会让候选变空并让派发失败——这是有意的，
        否则配置页显示的约束会静默失效。
        """
        if await self.has_subagent_bindings(parent_agent_id):
            result = await self.session.execute(
                select(Agent)
                .join(SubagentBinding, SubagentBinding.child_agent_id == Agent.id)
                .join(AgentVersion, AgentVersion.id == Agent.default_version_id)
                .where(
                    SubagentBinding.parent_agent_id == parent_agent_id,
                    SubagentBinding.enabled.is_(True),
                    Agent.platform_id == platform_id,
                    Agent.id != parent_agent_id,
                    Agent.is_active.is_(True),
                    AgentVersion.published_at.is_not(None),
                )
                .order_by(SubagentBinding.sort_order.asc(), SubagentBinding.id.asc())
                .limit(max(1, limit))
            )
            return list(result.scalars().all())

        result = await self.session.execute(
            select(Agent)
            .join(AgentVersion, AgentVersion.id == Agent.default_version_id)
            .where(
                Agent.platform_id == platform_id,
                Agent.id != parent_agent_id,
                Agent.is_active.is_(True),
                AgentVersion.published_at.is_not(None),
            )
            .order_by(Agent.slug.asc())
            .limit(max(1, limit))
        )
        return list(result.scalars().all())

    async def list_subagent_available_agents(
        self, platform_id: int, parent_agent_id: int, *, limit: int = 50
    ) -> list[Agent]:
        """配置页「可添加」候选：本平台已发布启用、排除父自己与已绑定项。"""
        bound_ids = select(SubagentBinding.child_agent_id).where(
            SubagentBinding.parent_agent_id == parent_agent_id
        )
        result = await self.session.execute(
            select(Agent)
            .join(AgentVersion, AgentVersion.id == Agent.default_version_id)
            .where(
                Agent.platform_id == platform_id,
                Agent.id != parent_agent_id,
                Agent.is_active.is_(True),
                AgentVersion.published_at.is_not(None),
                Agent.id.not_in(bound_ids),
            )
            .order_by(Agent.slug.asc())
            .limit(max(1, limit))
        )
        return list(result.scalars().all())

    async def replace_subagent_bindings(
        self, parent_agent_id: int, items: list[tuple[int, bool]]
    ) -> None:
        """整表替换绑定；数组顺序即 ``sort_order``。

        调用方负责同平台、禁自指、去重校验（见 agent/services.py）。整表替换的
        语义让前端一次保存就能表达排序与停用，不需要逐条 diff。
        """
        await self.session.execute(
            delete(SubagentBinding).where(
                SubagentBinding.parent_agent_id == parent_agent_id
            )
        )
        for index, (child_agent_id, enabled) in enumerate(items):
            self.session.add(
                SubagentBinding(
                    parent_agent_id=parent_agent_id,
                    child_agent_id=child_agent_id,
                    sort_order=index,
                    enabled=enabled,
                )
            )
        await self.session.commit()
