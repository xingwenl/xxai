from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import AgentSkillBind, SkillCreate, SkillRead
from app.modules.skill.services import bind_skill, create_skill
from app.shared.exceptions import NotFoundException
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
