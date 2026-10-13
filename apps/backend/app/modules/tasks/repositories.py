"""任务与任务运行的数据库访问层。

这里集中承载三类容易被写散的查询：
1. 可见性过滤（平台管理员看全平台，普通用户只看自己名下的任务）；
2. 调度抢占（``FOR UPDATE SKIP LOCKED``，保证多副本安全）；
3. 串行判定与看门狗所需的「按状态 + 时间」扫描。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import Task, TaskRun
from app.shared.base_repository import BaseRepository
from app.shared.pagination import PaginationParams, build_page_data


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Task)

    async def get_scoped(self, task_id: int, platform_id: int) -> Task | None:
        """按「任务 + 平台」取任务，避免跨平台越权读取。"""

        result = await self.session.execute(
            select(Task).where(Task.id == task_id, Task.platform_id == platform_id)
        )
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        platform_id: int,
        params: PaginationParams,
        *,
        owner_user_id: int | None = None,
        status: str | None = None,
    ):
        """任务列表。

        ``owner_user_id=None`` 表示平台管理员视角：返回该平台全部任务
        （含平台级任务与所有用户的个人任务）；传入用户 ID 时只返回
        该用户自己名下的任务。可见性规则只有这一处实现。
        """

        conditions = [Task.platform_id == platform_id]
        if owner_user_id is not None:
            conditions.append(Task.owner_user_id == owner_user_id)
        if status is not None:
            conditions.append(Task.status == status)

        statement = (
            select(Task)
            .where(*conditions)
            .order_by(Task.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(statement)
        items = list(result.scalars().all())
        total = await self.session.scalar(
            select(func.count()).select_from(Task).where(*conditions)
        )
        return build_page_data(items, params, int(total or 0))

    async def count_for_platform(self, platform_id: int) -> int:
        """平台内的任务总数，用于「单平台任务数上限」校验。"""

        total = await self.session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.platform_id == platform_id)
        )
        return int(total or 0)

    async def claim_due_tasks(
        self, *, limit: int = 50, workflow_linked: bool | None = None
    ) -> list[Task]:
        """抢占一批到期任务。

        用 ``FOR UPDATE SKIP LOCKED`` 跳过已被其他副本锁住的行，这样
        多副本同时 tick 时同一个触发点只会被一个副本拿到，拿不到锁的
        副本直接跳过而不阻塞等待。

        ``workflow_linked`` 是给调度器用的：它把「普通任务」与「由工作流触发
        的任务」两条触发路径切成互不相交的集合，避免同一批到期任务被普通任务
        tick 与工作流 tick 同时处理：

        - ``None`` 表示不加条件（保持本方法原有的全部行为）；
        - ``False`` 只看普通任务（``workflow_id IS NULL``）；
        - ``True`` 只看由工作流触发的任务（``workflow_id IS NOT NULL``）。

        调用方负责在**同一个事务**内提交（含推进 ``next_run_at``），
        本方法只 flush 不 commit。
        """

        now = datetime.now(UTC)
        conditions = [
            Task.status == "active",
            Task.next_run_at.is_not(None),
            Task.next_run_at <= now,
        ]
        if workflow_linked is False:
            conditions.append(Task.workflow_id.is_(None))
        elif workflow_linked is True:
            conditions.append(Task.workflow_id.is_not(None))

        statement = (
            select(Task)
            .where(*conditions)
            .order_by(Task.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        claimed = list(result.scalars().all())
        for task in claimed:
            # 记下这次实际触发的时刻；next_run_at 由服务层按「错过不补跑」推进。
            task.last_run_at = now
        if claimed:
            await self.session.flush()
        return claimed

    async def list_runs(
        self,
        task_id: int,
        params: PaginationParams,
        *,
        status: str | None = None,
    ):
        """某个任务的执行记录列表（倒序）。"""

        conditions = [TaskRun.task_id == task_id]
        if status is not None:
            conditions.append(TaskRun.status == status)
        statement = (
            select(TaskRun)
            .where(*conditions)
            .order_by(TaskRun.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(statement)
        items = list(result.scalars().all())
        total = await self.session.scalar(
            select(func.count()).select_from(TaskRun).where(*conditions)
        )
        return build_page_data(items, params, int(total or 0))


class TaskRunRepository(BaseRepository[TaskRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TaskRun)

    async def get_running(self, task_id: int) -> TaskRun | None:
        """取该任务当前正在执行（含已排队待执行）的记录。

        有值即表示「上一次还没结束」，用于「同一任务串行」判定。
        """

        result = await self.session.execute(
            select(TaskRun)
            .where(TaskRun.task_id == task_id, TaskRun.status == "running")
            .order_by(TaskRun.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_queued_runs(self, *, limit: int = 50) -> list[int]:
        """认领所有「已排队但尚未开始」的执行记录，返回 run id 列表。

        状态口径：``status='running'`` 且 ``started_at IS NULL`` 表示已排队、
        等待执行；``started_at`` 有值才代表真正在执行。用这个区分而不是新增
        状态值，是因为执行记录的状态语义要保持稳定。

        这一步是「立即运行一次」与「进程重启后遗留 run」能被执行的保证：
        调度器不能只执行自己在本 tick 里创建的记录，否则由接口写入的
        run 永远无人认领，只会被看门狗判为超时失败。

        用 ``FOR UPDATE SKIP LOCKED`` 抢占，多副本下同一条只会被认领一次。
        调用方负责提交事务。
        """

        statement = (
            select(TaskRun)
            .where(TaskRun.status == "running", TaskRun.started_at.is_(None))
            .order_by(TaskRun.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        claimed = list(result.scalars().all())
        now = datetime.now(UTC)
        for run in claimed:
            run.started_at = now
        if claimed:
            await self.session.flush()
        return [run.id for run in claimed]

    async def create_run(
        self,
        *,
        task_id: int,
        status: str,
        trigger_kind: str,
        planned_at: datetime | None = None,
        started_at: datetime | None = None,
        skip_reason: str | None = None,
    ) -> TaskRun:
        """写入一条执行记录；调用方负责提交事务。"""

        run = TaskRun(
            task_id=task_id,
            status=status,
            trigger_kind=trigger_kind,
            planned_at=planned_at,
            started_at=started_at,
            skip_reason=skip_reason,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def mark_started(self, run_id: int) -> TaskRun | None:
        """给一条 running 记录补写 ``started_at``（空写一次，幂等）。"""

        run = await self.session.get(TaskRun, run_id)
        if run is None:
            return None
        if run.status == "running" and run.started_at is None:
            run.started_at = datetime.now(UTC)
            await self.session.flush()
        return run

    async def finish_run(
        self,
        run: TaskRun,
        *,
        status: str,
        error_message: str | None = None,
        conversation_id: int | None = None,
        agent_loop_run_id: int | None = None,
        auto_approved_count: int | None = None,
    ) -> TaskRun:
        """回写执行结果；调用方负责提交事务。"""

        run.status = status
        run.finished_at = datetime.now(UTC)
        if error_message is not None:
            run.error_message = error_message
        if conversation_id is not None:
            run.conversation_id = conversation_id
        if agent_loop_run_id is not None:
            run.agent_loop_run_id = agent_loop_run_id
        if auto_approved_count is not None:
            run.auto_approved_count = auto_approved_count
        await self.session.flush()
        return run

    async def expire_stale_running(self, *, default_timeout_seconds: int) -> int:
        """看门狗：把已超时仍处于 running 的记录标记为失败，返回处理条数。

        判定基准用 ``started_at``（为空时回落到 ``created_at``），并按每个
        任务自己的 ``timeout_seconds`` 计算，避免统一超时误杀长任务。
        进程被杀会留下永久 running，这里是唯一的兜底清理入口。
        """

        now = datetime.now(UTC)
        expired = 0
        for run, task in await self._list_running_locked():
            timeout = task.timeout_seconds or default_timeout_seconds
            anchor = self._timeout_anchor(run)
            # 无论是否超时都刷新 checked_at，便于排障时看出看门狗确实跑过。
            run.watchdog_checked_at = now
            if anchor is None:
                continue
            if now - anchor > timedelta(seconds=timeout):
                run.status = "failed"
                run.finished_at = now
                run.error_message = (
                    f"执行超时：超过 {timeout} 秒仍未结束，由看门狗标记失败"
                )
                expired += 1
        await self.session.flush()
        return expired

    async def _list_running_locked(self) -> list[tuple[TaskRun, Task]]:
        """取出当前所有 running 记录及其任务，并锁住这些行。"""

        statement = (
            select(TaskRun, Task)
            .join(Task, Task.id == TaskRun.task_id)
            .where(TaskRun.status == "running")
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        return [(run, task) for run, task in result.all()]

    @staticmethod
    def _timeout_anchor(run: TaskRun) -> datetime | None:
        """超时判定的时间基准：优先 started_at，回落到 created_at。"""

        anchor = run.started_at or run.created_at
        if anchor is not None and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        return anchor
