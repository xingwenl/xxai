from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.skill.importers import MAX_ZIP_BYTES
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import (
    AgentSkillBind,
    AgentSkillRead,
    SkillCreate,
    SkillListData,
    SkillPackageDetail,
    SkillPackageImportResult,
    SkillPackageListData,
    SkillPackageRead,
    SkillPackageUpdate,
    SkillScriptExecutionListData,
    SkillRead,
    SkillUpdate,
)
from app.modules.skill.services import (
    bind_skill,
    create_skill,
    delete_skill,
    import_skill_package,
    unbind_skill,
    update_skill_package,
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


@router.post(
    "/skills/import",
    response_model=ApiResponse[SkillPackageImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def import_skill_package_endpoint(
    platform_id: int,
    file: UploadFile = File(...),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    content = await file.read(MAX_ZIP_BYTES + 1)
    package = await import_skill_package(
        SkillRepository(session),
        platform_id,
        filename=file.filename or "skill-package.zip",
        content=content,
    )
    detail = SkillPackageDetail.model_validate(package)
    return success_response(
        data=SkillPackageImportResult(package=detail, warnings=package.warnings),
        message="skill package imported",
    )


@router.get("/skill-packages", response_model=ApiResponse[SkillPackageListData])
async def list_skill_packages_endpoint(
    platform_id: int,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    page = await SkillRepository(session).list_packages(platform_id, params)
    return success_response(
        data=SkillPackageListData.model_validate(page.model_dump()),
        message="skill packages listed",
    )


@router.get(
    "/skill-packages/{package_id}", response_model=ApiResponse[SkillPackageDetail]
)
async def get_skill_package_endpoint(
    platform_id: int,
    package_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    package = await SkillRepository(session).get_package(package_id, platform_id)
    if package is None:
        raise NotFoundException("skill package not found")
    return success_response(
        data=SkillPackageDetail.model_validate(package),
        message="skill package loaded",
    )


@router.patch(
    "/skill-packages/{package_id}", response_model=ApiResponse[SkillPackageRead]
)
async def update_skill_package_endpoint(
    platform_id: int,
    package_id: int,
    payload: SkillPackageUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    package = await update_skill_package(
        SkillRepository(session), platform_id, package_id, payload
    )
    return success_response(
        data=SkillPackageRead.model_validate(package),
        message="skill package updated",
    )


@router.get(
    "/skill-script-executions",
    response_model=ApiResponse[SkillScriptExecutionListData],
)
async def list_skill_script_executions_endpoint(
    platform_id: int,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    page = await SkillRepository(session).list_script_executions(platform_id, params)
    return success_response(
        data=SkillScriptExecutionListData.model_validate(page.model_dump()),
        message="skill script executions listed",
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
