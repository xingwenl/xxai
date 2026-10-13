"""工作流数据访问层。

集中承载三类容易写散的查询，与 ``app/modules/tasks/repositories.py`` 同构：

1. 可见性过滤（平台 + 归属人）；
2. 调度抢占与串行判定（``FOR UPDATE SKIP LOCKED`` 保证多副本安全）；
3. 看门狗所需的「按状态 + 时间」扫描。

注意 ``BaseRepository.create/update/delete`` 自带 commit，而调度链路上的写入
必须由调用方控制事务边界（抢占与推进要在同一事务里提交），因此这里的方法
一律只 ``flush``，由调用方 commit。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PageData, PaginationParams, build_page_data


class WorkflowRepository(BaseRepository[Workflow]):
    """工作流定义的查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Workflow)

    async def get_scoped(self, workflow_id: int, platform_id: int) -> Workflow | None:
        """按「工作流 + 平台」取，避免跨平台越权读取。"""

        stmt = select(Workflow).where(
            Workflow.id == workflow_id, Workflow.platform_id == platform_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_workflows(
        self,
        platform_id: int,
        params: PaginationParams,
        *,
        owner_user_id: int | None = None,
        status: str | None = None,
    ) -> PageData[Workflow]:
        """可见性规则只在这里实现：``owner_user_id=None`` 表示管理员视角。"""

        conditions = [Workflow.platform_id == platform_id]
        if owner_user_id is not None:
            conditions.append(Workflow.owner_user_id == owner_user_id)
        if status is not None:
            conditions.append(Workflow.status == status)

        rows = await self.list(
            offset=params.offset,
            limit=params.limit,
            order_by=Workflow.id.desc(),
            filters=conditions,
        )
        total = await self.count_by_filters(conditions)
        return build_page_data(list(rows), params, int(total or 0))

    async def count_for_platform(self, platform_id: int) -> int:
        """单平台工作流数量，用于创建工作流前的上限校验。"""

        return await self.count_by_filters([Workflow.platform_id == platform_id])


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    """工作流运行的写入与调度扫描。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowRun)

    async def get_running(self, workflow_id: int) -> WorkflowRun | None:
        """取该工作流当前的 running 记录；有值即「上一次还没结束」。"""

        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status == "running",
            )
            .order_by(WorkflowRun.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_run(
        self,
        *,
        workflow_id: int,
        status: str,
        trigger_kind: str,
        definition_version_id: int,
        definition_snapshot: dict,
        total_steps: int = 0,
        run_as_type: str = "user",
        run_as_user_id: int | None = None,
        run_as_end_user_id: int | None = None,
        planned_at: datetime | None = None,
        started_at: datetime | None = None,
        skip_reason: str | None = None,
    ) -> WorkflowRun:
        """写入一条运行记录（只 flush，调用方负责 commit）。

        注意这里**不写 started_at** 用于「已排队」语义：``status='running'``
        且 ``started_at IS NULL`` 表示等待执行，由调度器认领时才补 ``started_at``。
        沿用任务模块的状态口径，不新增状态值。
        """

        run = WorkflowRun(
            workflow_id=workflow_id,
            status=status,
            trigger_kind=trigger_kind,
            definition_version_id=definition_version_id,
            definition_snapshot=definition_snapshot,
            total_steps=total_steps,
            run_as_type=run_as_type,
            run_as_user_id=run_as_user_id,
            run_as_end_user_id=run_as_end_user_id,
            planned_at=planned_at,
            started_at=started_at,
            skip_reason=skip_reason,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def claim_queued_runs(self, *, limit: int = 50) -> list[int]:
        """认领「已排队待执行」的运行记录，返回 id 列表。

        认领条件是 ``status='running'`` 且 ``started_at IS NULL``。调度器不能只
        执行自己在本 tick 里创建的记录：手动运行接口写入的记录、以及进程重启后
        遗留的排队记录，都必须能在这里被认领，否则永远无人执行、只会被看门狗判成
        超时失败。
        """

        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.status == "running",
                WorkflowRun.started_at.is_(None),
            )
            .order_by(WorkflowRun.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        runs = list(result.scalars().all())

        now = datetime.now(UTC)
        claimed: list[int] = []
        for run in runs:
            # 认领即写 started_at：看门狗按 started_at 计算超时，排队中的记录
            # 不该被算进执行时长。
            run.started_at = now
            claimed.append(run.id)
        if claimed:
            await self.session.flush()
        return claimed

    async def mark_started(self, run_id: int) -> WorkflowRun | None:
        """给 running 记录补写 started_at（幂等，已有值则不覆盖）。"""

        run = await self.session.get(WorkflowRun, run_id)
        if run is None:
            return None
        if run.started_at is None:
            run.started_at = datetime.now(UTC)
            await self.session.flush()
        return run

    async def finish_run(
        self,
        run: WorkflowRun,
        *,
        status: str,
        error_message: str | None = None,
        completed_steps: int | None = None,
        auto_approved_count: int | None = None,
        skip_reason: str | None = None,
    ) -> WorkflowRun:
        """收尾一次运行：写状态、结束时间与统计值。"""

        run.status = status
        run.finished_at = datetime.now(UTC)
        if error_message is not None:
            run.error_message = error_message
        if completed_steps is not None:
            run.completed_steps = completed_steps
        if auto_approved_count is not None:
            run.auto_approved_count = auto_approved_count
        if skip_reason is not None:
            run.skip_reason = skip_reason
        await self.session.flush()
        return run

    async def list_runs(
        self,
        workflow_id: int,
        params: PaginationParams,
        *,
        status: str | None = None,
    ) -> PageData[WorkflowRun]:
        """工作流运行列表，倒序。"""

        conditions = [WorkflowRun.workflow_id == workflow_id]
        if status is not None:
            conditions.append(WorkflowRun.status == status)

        rows = await self.list(
            offset=params.offset,
            limit=params.limit,
            order_by=WorkflowRun.id.desc(),
            filters=conditions,
        )
        total = await self.count_by_filters(conditions)
        return build_page_data(list(rows), params, int(total or 0))

    async def expire_stale_running(self, *, default_timeout_seconds: int) -> int:
        """看门狗：把超时仍在 running 的运行标记为失败，返回处理条数。

        判定基准用 ``started_at``（为空回落到 ``created_at``），按**每个工作流
        自己的** ``timeout_seconds`` 计算，避免统一超时误杀长流程。进程被杀会留下
        永久 running，这里是唯一的兜底清理入口。
        """

        now = datetime.now(UTC)
        expired = 0
        for run, workflow in await self._list_running_locked():
            run.watchdog_checked_at = now
            anchor = self._timeout_anchor(run)
            if anchor is None:
                continue
            timeout = int(workflow.timeout_seconds or default_timeout_seconds)
            if (now - anchor).total_seconds() <= timeout:
                continue
            run.status = "failed"
            run.finished_at = now
            run.error_message = (
                f"执行超时：超过 {timeout} 秒仍未结束，由看门狗标记失败"
            )
            expired += 1
        if expired:
            await self.session.flush()
        return expired

    async def _list_running_locked(self) -> list[tuple[WorkflowRun, Workflow]]:
        """取出所有 running 运行并加行锁；join 定义表以取各自超时。"""

        stmt = (
            select(WorkflowRun, Workflow)
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
            .where(WorkflowRun.status == "running")
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return [(run, workflow) for run, workflow in result.all()]

    @staticmethod
    def _timeout_anchor(run: WorkflowRun) -> datetime | None:
        """超时计算的起点：优先 started_at，未认领时回落到 created_at。"""

        anchor = run.started_at or run.created_at
        if anchor is None:
            return None
        if anchor.tzinfo is None:
            # sqlite 不保留时区信息，读出来是 naive，按 UTC 解释。
            return anchor.replace(tzinfo=UTC)
        return anchor


class WorkflowStepRunRepository(BaseRepository[WorkflowStepRun]):
    """步骤运行记录的写入与读取。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowStepRun)

    async def create_step_run(
        self,
        *,
        run_id: int,
        step_id: str,
        seq: int,
        node_type: str,
        status: str = "running",
        started_at: datetime | None = None,
    ) -> WorkflowStepRun:
        """开始一步：写入 running 记录（只 flush）。"""

        step_run = WorkflowStepRun(
            run_id=run_id,
            step_id=step_id,
            seq=seq,
            node_type=node_type,
            status=status,
            started_at=started_at or datetime.now(UTC),
        )
        self.session.add(step_run)
        await self.session.flush()
        return step_run

    async def finish_step_run(
        self,
        step_run: WorkflowStepRun,
        *,
        status: str,
        model_visible_output: str | None = None,
        raw_output: str | None = None,
        error_message: str | None = None,
        on_error_applied: bool = False,
        retry_count: int | None = None,
        conversation_id: int | None = None,
        agent_loop_run_id: int | None = None,
    ) -> WorkflowStepRun:
        """收尾一步：写状态、双通道输出与关联记录。"""

        step_run.status = status
        step_run.finished_at = datetime.now(UTC)
        step_run.on_error_applied = on_error_applied
        if model_visible_output is not None:
            step_run.model_visible_output = model_visible_output
        if raw_output is not None:
            step_run.raw_output = raw_output
        if error_message is not None:
            step_run.error_message = error_message
        if retry_count is not None:
            step_run.retry_count = retry_count
        if conversation_id is not None:
            step_run.conversation_id = conversation_id
        if agent_loop_run_id is not None:
            step_run.agent_loop_run_id = agent_loop_run_id
        await self.session.flush()
        return step_run

    async def list_for_run(self, run_id: int) -> list[WorkflowStepRun]:
        """按执行顺序取一次运行的全部步骤记录。"""

        stmt = (
            select(WorkflowStepRun)
            .where(WorkflowStepRun.run_id == run_id)
            .order_by(WorkflowStepRun.seq.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def fail_running_steps(self, run_id: int, *, error_message: str) -> int:
        """把一次运行里仍是 running 的步骤标记为失败，返回处理条数。

        进程被杀、整条超时、或还没走到收尾就抛异常时，步骤记录会停在
        ``running``；不在同一处收敛掉，界面就会永远显示「这一步还在跑」。
        """

        stmt = select(WorkflowStepRun).where(
            WorkflowStepRun.run_id == run_id,
            WorkflowStepRun.status == "running",
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        now = datetime.now(UTC)
        for step_run in rows:
            step_run.status = "failed"
            step_run.finished_at = now
            step_run.error_message = error_message
        if rows:
            await self.session.flush()
        return len(rows)
