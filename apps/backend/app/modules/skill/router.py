from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import (
    AgentSkillBind,
    AgentSkillRead,
    SkillCreate,
    SkillListData,
    SkillRead,
    SkillUpdate,
)
from app.modules.skill.services import (
    bind_skill,
    create_skill,
    delete_skill,
    unbind_skill,
    update_skill,
)
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}", tags=["skills"])


async def _require_admin(platform_id: int, user_id: int, session: AsyncSession):
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


@router.post(
    "/skills",
    response_model=ApiResponse[SkillRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_endpoint(
    platform_id: int,
    payload: SkillCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    skill = await create_skill(SkillRepository(session), platform_id, payload)
    return success_response(
        data=SkillRead.model_validate(skill), message="skill created"
    )


@router.get("/skills", response_model=ApiResponse[SkillListData])
async def list_skills_endpoint(
    platform_id: int,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    page = await SkillRepository(session).list_skills(platform_id, params)
    return success_response(
        data=SkillListData.model_validate(page.model_dump()), message="skills listed"
    )


@router.patch("/skills/{skill_id}", response_model=ApiResponse[SkillRead])
async def update_skill_endpoint(
    platform_id: int,
    skill_id: int,
    payload: SkillUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    skill = await update_skill(SkillRepository(session), platform_id, skill_id, payload)
    return success_response(data=SkillRead.model_validate(skill), message="skill updated")


@router.delete("/skills/{skill_id}", response_model=ApiResponse[None])
async def delete_skill_endpoint(
    platform_id: int,
    skill_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    await delete_skill(SkillRepository(session), platform_id, skill_id)
    return success_response(message="skill deleted")


@router.get(
    "/agents/{agent_id}/skills", response_model=ApiResponse[list[AgentSkillRead]]
)
async def list_agent_skills_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    bindings = await SkillRepository(session).list_bindings(platform_id, agent_id)
    return success_response(
        data=[AgentSkillRead.model_validate(item) for item in bindings],
        message="agent skills listed",
    )


@router.put("/agents/{agent_id}/skills", response_model=ApiResponse[dict])
async def bind_skill_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentSkillBind,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    binding = await bind_skill(SkillRepository(session), platform_id, agent_id, payload)
    return success_response(
        data={"agent_id": binding.agent_id, "skill_id": binding.skill_id},
        message="skill bound",
    )


@router.delete(
    "/agents/{agent_id}/skills/{skill_id}", response_model=ApiResponse[None]
)
async def unbind_skill_endpoint(
    platform_id: int,
    agent_id: int,
    skill_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    await unbind_skill(SkillRepository(session), platform_id, agent_id, skill_id)
    return success_response(message="skill unbound")
