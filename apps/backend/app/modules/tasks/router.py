"""任务接口路由。

全部挂在平台作用域前缀下（与 wechat_bots / agents 等模块一致）：

    /api/v1/platforms/{platform_id}/tasks

可见性规则：平台管理员看到该平台全部任务，普通用户只看到自己名下的任务；
平台级任务（``owner_user_id`` 为空）只有管理员能管理。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.tasks import services
from app.modules.tasks.schemas import (
    TaskCreate,
    TaskListData,
    TaskRead,
    TaskRunAccepted,
    TaskRunDetail,
    TaskRunListData,
    TaskRunRead,
    TaskUpdate,
)
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}/tasks", tags=["tasks"])


async def _require_platform_member(
    platform_id: int, user_id: int, session: AsyncSession
) -> bool:
    """确认当前用户属于该平台，并返回其是否为平台管理员。

    本仓库没有独立的「平台角色」概念：只要能在 ``platform_admins`` 里
    查到这条归属，就是该平台的管理员，否则直接 404。
    """

    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, user_id
    )
    if platform is None:
        raise NotFoundException("platform not found")
    return True


def _to_read(task) -> TaskRead:
    return TaskRead.model_validate(task)


def _run_to_read(run) -> TaskRunRead:
    return TaskRunRead.model_validate(run)


@router.get("", response_model=ApiResponse[TaskListData])
async def list_tasks_endpoint(
    platform_id: int,
    status: str | None = Query(default=None, description="按状态筛选：active / paused"),
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskListData]:
    """任务列表：管理员看全平台，普通用户只看自己名下的。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    page = await services.list_tasks(
        session,
        platform_id=platform_id,
        params=params,
        # 非管理员强制按本人过滤；管理员传 None 表示不过滤归属。
        owner_user_id=None if is_admin else current_user.id,
        status=status,
    )
    data = TaskListData(
        page_no=page.page_no,
        page_size=page.page_size,
        items=[_to_read(item) for item in page.items],
        total=page.total,
        pages=page.pages,
    )
    return success_response(data=data, message="tasks listed")


@router.post("", response_model=ApiResponse[TaskRead], status_code=201)
async def create_task_endpoint(
    platform_id: int,
    payload: TaskCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRead]:
    """创建任务；归属为当前用户，执行身份与归属一致。"""

    await _require_platform_member(platform_id, current_user.id, session)
    task = await services.create_task(
        session,
        platform_id=platform_id,
        payload=payload,
        owner_user_id=current_user.id,
        created_by_type="user",
        created_by_user_id=current_user.id,
        run_as_user_id=current_user.id,
    )
    return success_response(data=_to_read(task), message="task created")


@router.get("/{task_id}", response_model=ApiResponse[TaskRead])
async def get_task_endpoint(
    platform_id: int,
    task_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRead]:
    """任务详情。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    return success_response(data=_to_read(task), message="task detail")


@router.patch("/{task_id}", response_model=ApiResponse[TaskRead])
async def update_task_endpoint(
    platform_id: int,
    task_id: int,
    payload: TaskUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRead]:
    """更新任务（含暂停 status=paused / 恢复 status=active）。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    updated = await services.update_task(session, task, payload)
    return success_response(data=_to_read(updated), message="task updated")


@router.delete("/{task_id}", response_model=ApiResponse[dict])
async def delete_task_endpoint(
    platform_id: int,
    task_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[dict]:
    """删除任务；执行记录级联删除，任务创建过的会话默认保留。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    await services.delete_task(session, task)
    return success_response(data={"deleted": task_id}, message="task deleted")


@router.post("/{task_id}/run", response_model=ApiResponse[TaskRunAccepted])
async def run_task_endpoint(
    platform_id: int,
    task_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRunAccepted]:
    """立即运行一次；不受最小间隔限制，但仍受「同一任务串行」约束。

    写入执行记录后由调度进程在下一个 tick 领取执行，因此接口只负责
    「排队」，不阻塞等待模型跑完。
    """

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    run, started = await services.enqueue_manual_run(session, task)
    message = "已开始执行" if started else "该任务正在运行，本次已跳过"
    return success_response(
        data=TaskRunAccepted(run=_run_to_read(run), message=message),
        message=message,
    )


@router.get("/{task_id}/runs/{run_id}/detail", response_model=ApiResponse[TaskRunDetail])
async def get_task_run_detail_endpoint(
    platform_id: int,
    task_id: int,
    run_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRunDetail]:
    """单次运行的执行过程：每步的思考、工具调用、结果与错误。

    过程数据来自 ``agent_loop_steps``，通过 ``agent_loop_run_id`` 关联。
    有了它，任务侧不必跳去会话页就能看清一轮运行做了什么、卡在哪一步。
    """

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    detail = await services.get_run_detail(session, task=task, run_id=run_id)
    return success_response(data=detail, message="task run detail")


@router.get("/{task_id}/runs", response_model=ApiResponse[TaskRunListData])
async def list_task_runs_endpoint(
    platform_id: int,
    task_id: int,
    status: str | None = Query(default=None, description="按执行状态筛选"),
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TaskRunListData]:
    """执行记录列表。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    task = await services.get_task_or_404(
        session, task_id=task_id, platform_id=platform_id
    )
    services.assert_can_manage(
        task, user_id=current_user.id, is_platform_admin=is_admin
    )
    page = await services.list_task_runs(
        session, task_id=task_id, params=params, status=status
    )
    data = TaskRunListData(
        page_no=page.page_no,
        page_size=page.page_size,
        items=[_run_to_read(item) for item in page.items],
        total=page.total,
        pages=page.pages,
    )
    return success_response(data=data, message="task runs listed")
