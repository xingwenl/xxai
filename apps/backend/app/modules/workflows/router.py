"""工作流接口路由。

全部挂在平台作用域前缀下（与 tasks / wechat_bots 等模块一致）：

    /api/v1/platforms/{platform_id}/workflows

可见性规则与任务一致：平台管理员看到该平台全部工作流，普通用户只看到自己
名下的；越权一律按「不存在」回答（404），不区分「无权」与「没有」。

需要注意（与任务模块同源）：``_require_platform_member`` 查的是
``platform_admins`` 成员表，能在表里查到就算该平台的管理员，因此经 HTTP 进来的
调用者目前恒为管理员，``assert_can_manage`` 的 owner 分支暂时只有服务层的直接
调用覆盖到。真正在生效的隔离是平台作用域：跨平台 id 一律 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.workflows import services
from app.modules.workflows.schemas import (
    WorkflowCreate,
    WorkflowListData,
    WorkflowRead,
    WorkflowRunAccepted,
    WorkflowRunDetail,
    WorkflowRunListData,
    WorkflowRunRead,
    WorkflowUpdate,
)
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}/workflows", tags=["workflows"])


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


def _to_read(workflow) -> WorkflowRead:
    return WorkflowRead.model_validate(workflow)


def _run_to_read(run) -> WorkflowRunRead:
    return WorkflowRunRead.model_validate(run)


@router.get("", response_model=ApiResponse[WorkflowListData])
async def list_workflows_endpoint(
    platform_id: int,
    status: str | None = Query(default=None, description="按状态筛选：active / paused"),
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowListData]:
    """工作流列表：管理员看全平台，普通用户只看自己名下的。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    page = await services.list_workflows(
        session,
        platform_id=platform_id,
        params=params,
        # 非管理员强制按本人过滤；管理员传 None 表示不过滤归属。
        owner_user_id=None if is_admin else current_user.id,
        status=status,
    )
    data = WorkflowListData(
        page_no=page.page_no,
        page_size=page.page_size,
        items=[_to_read(item) for item in page.items],
        total=page.total,
        pages=page.pages,
    )
    return success_response(data=data, message="workflows listed")


@router.post("", response_model=ApiResponse[WorkflowRead], status_code=201)
async def create_workflow_endpoint(
    platform_id: int,
    payload: WorkflowCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRead]:
    """创建工作流；定义在保存时完成静态校验并编译成 nodes/edges。"""

    await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.create_workflow(
        session,
        platform_id=platform_id,
        payload=payload,
        owner_user_id=current_user.id,
        created_by_type="user",
        created_by_user_id=current_user.id,
    )
    return success_response(data=_to_read(workflow), message="workflow created")


@router.get("/{workflow_id}", response_model=ApiResponse[WorkflowRead])
async def get_workflow_endpoint(
    platform_id: int,
    workflow_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRead]:
    """工作流详情。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    return success_response(data=_to_read(workflow), message="workflow detail")


@router.patch("/{workflow_id}", response_model=ApiResponse[WorkflowRead])
async def update_workflow_endpoint(
    platform_id: int,
    workflow_id: int,
    payload: WorkflowUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRead]:
    """更新工作流（含暂停 status=paused / 恢复 status=active）。

    传入 steps 即视为保存新一版定义，服务层会把 version 加一并重新编译。
    """

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    updated = await services.update_workflow(session, workflow=workflow, payload=payload)
    return success_response(data=_to_read(updated), message="workflow updated")


@router.delete("/{workflow_id}", response_model=ApiResponse[dict])
async def delete_workflow_endpoint(
    platform_id: int,
    workflow_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[dict]:
    """删除工作流；历史运行记录随定义级联处理。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    await services.delete_workflow(session, workflow=workflow)
    return success_response(data={"deleted": workflow_id}, message="workflow deleted")


@router.post("/{workflow_id}/run", response_model=ApiResponse[WorkflowRunAccepted])
async def run_workflow_endpoint(
    platform_id: int,
    workflow_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRunAccepted]:
    """立即运行一次。

    接口只负责「排队」：写入运行记录后由调度器在下一个 tick 领取执行，
    不阻塞等待整条流程跑完。
    """

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    run, started = await services.enqueue_manual_run(
        session, workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    message = "已开始执行" if started else "该工作流正在运行，本次已跳过"
    return success_response(
        data=WorkflowRunAccepted(run=_run_to_read(run), message=message),
        message=message,
    )


@router.get("/{workflow_id}/runs", response_model=ApiResponse[WorkflowRunListData])
async def list_workflow_runs_endpoint(
    platform_id: int,
    workflow_id: int,
    status: str | None = Query(default=None, description="按运行状态筛选"),
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRunListData]:
    """运行记录列表。"""

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    page = await services.list_workflow_runs(
        session, workflow_id=workflow.id, params=params, status=status
    )
    data = WorkflowRunListData(
        page_no=page.page_no,
        page_size=page.page_size,
        items=[_run_to_read(item) for item in page.items],
        total=page.total,
        pages=page.pages,
    )
    return success_response(data=data, message="workflow runs listed")


@router.get("/{workflow_id}/runs/{run_id}", response_model=ApiResponse[WorkflowRunDetail])
async def get_workflow_run_detail_endpoint(
    platform_id: int,
    workflow_id: int,
    run_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WorkflowRunDetail]:
    """单次运行的明细：运行信息 + 当时的定义快照 + 各步骤记录。

    快照让历史运行可解释：定义后来被改过，也仍能看到这条运行照哪一版执行的。
    """

    is_admin = await _require_platform_member(platform_id, current_user.id, session)
    workflow = await services.get_workflow_or_404(
        session, workflow_id=workflow_id, platform_id=platform_id
    )
    services.assert_can_manage(
        workflow, user_id=current_user.id, is_platform_admin=is_admin
    )
    detail = await services.get_run_detail(session, workflow=workflow, run_id=run_id)
    return success_response(data=detail, message="workflow run detail")
