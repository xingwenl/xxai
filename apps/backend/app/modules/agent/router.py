from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.schemas import (
    AgentCreate,
    AgentDetailRead,
    AgentListData,
    AgentRead,
    AgentSubagentListData,
    AgentSubagentReplace,
    AgentUpdate,
    AgentVersionCreate,
    AgentVersionRead,
)
from app.modules.agent.services import (
    create_agent,
    create_agent_version,
    list_subagent_bindings,
    publish_agent_version,
    replace_subagent_bindings,
    rollback_agent,
    update_agent,
    delete_agent,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}/agents", tags=["agents"])


async def _require_platform_admin(
    platform_id: int, user_id: int, session: AsyncSession
) -> None:
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, user_id
    )
    if platform is None:
        raise NotFoundException("platform not found")


def _version_read(version) -> AgentVersionRead:
    return AgentVersionRead.model_validate(version)


@router.get("", response_model=ApiResponse[AgentListData])
async def list_agents_endpoint(
    platform_id: int,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentListData]:
    await _require_platform_admin(platform_id, current_user.id, session)
    page = await AgentRepository(session).list_agents(platform_id, params)
    return success_response(
        data=AgentListData.model_validate(page.model_dump()), message="agents listed"
    )


@router.post(
    "", response_model=ApiResponse[AgentRead], status_code=status.HTTP_201_CREATED
)
async def create_agent_endpoint(
    platform_id: int,
    payload: AgentCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    agent = await create_agent(
        AgentRepository(session), payload, platform_id=platform_id
    )
    return success_response(
        data=AgentRead.model_validate(agent), message="agent created"
    )


@router.patch("/{agent_id}", response_model=ApiResponse[AgentRead])
async def update_agent_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    agent = await update_agent(
        AgentRepository(session), agent_id, payload, platform_id=platform_id
    )
    return success_response(data=AgentRead.model_validate(agent), message="agent updated")


@router.get("/{agent_id}", response_model=ApiResponse[AgentDetailRead])
async def get_agent_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentDetailRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    agent = await AgentRepository(session).get_agent_detail(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    data = AgentDetailRead.model_validate(
        {
            **agent.__dict__,
            "current_version": (
                _version_read(agent.default_version)
                if agent.default_version is not None
                else None
            ),
        }
    )
    return success_response(data=data, message="agent fetched")


@router.delete("/{agent_id}", response_model=ApiResponse[None])
async def delete_agent_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    await _require_platform_admin(platform_id, current_user.id, session)
    await delete_agent(AgentRepository(session), agent_id, platform_id=platform_id)
    return success_response(message="agent deleted")


@router.get("/{agent_id}/versions", response_model=ApiResponse[list[AgentVersionRead]])
async def list_agent_versions_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[AgentVersionRead]]:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = AgentRepository(session)
    if await repo.get_agent(agent_id, platform_id) is None:
        raise NotFoundException("agent not found")
    return success_response(
        data=[_version_read(item) for item in await repo.list_versions(agent_id)]
    )


@router.post(
    "/{agent_id}/versions",
    response_model=ApiResponse[AgentVersionRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_version_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentVersionCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await create_agent_version(
        AgentRepository(session), agent_id, payload, platform_id=platform_id
    )
    return success_response(
        data=_version_read(version), message="agent version created"
    )


@router.post(
    "/{agent_id}/versions/{version_id}/publish",
    response_model=ApiResponse[AgentVersionRead],
)
async def publish_agent_version_endpoint(
    platform_id: int,
    agent_id: int,
    version_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await publish_agent_version(
        AgentRepository(session), agent_id, version_id, platform_id=platform_id
    )
    return success_response(
        data=_version_read(version), message="agent version published"
    )


@router.post(
    "/{agent_id}/versions/{version_id}/rollback",
    response_model=ApiResponse[AgentVersionRead],
)
async def rollback_agent_endpoint(
    platform_id: int,
    agent_id: int,
    version_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentVersionRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    version = await rollback_agent(
        AgentRepository(session), agent_id, version_id, platform_id=platform_id
    )
    return success_response(data=_version_read(version), message="agent rolled back")


@router.get(
    "/{agent_id}/subagents", response_model=ApiResponse[AgentSubagentListData]
)
async def list_agent_subagents_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentSubagentListData]:
    """读取「该智能体能派给谁」的绑定配置（含可添加候选）。

    配置页据此渲染已绑定列表与下拉候选；运行期候选口径由同一份仓储方法得出，
    两者不一致时问题会落到「配了却派不出去」上，所以读侧复用同一套谓词。
    """
    await _require_platform_admin(platform_id, current_user.id, session)
    data = await list_subagent_bindings(
        AgentRepository(session), agent_id, platform_id=platform_id
    )
    return success_response(
        data=AgentSubagentListData.model_validate(data), message="subagents listed"
    )


@router.put(
    "/{agent_id}/subagents", response_model=ApiResponse[AgentSubagentListData]
)
async def replace_agent_subagents_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentSubagentReplace,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentSubagentListData]:
    """整表替换绑定关系：数组顺序即展示顺序，空数组表示清空（回退兜底口径）。"""
    await _require_platform_admin(platform_id, current_user.id, session)
    data = await replace_subagent_bindings(
        AgentRepository(session),
        agent_id,
        [(item.child_agent_id, item.enabled) for item in payload.items],
        platform_id=platform_id,
    )
    return success_response(
        data=AgentSubagentListData.model_validate(data), message="subagents replaced"
    )
