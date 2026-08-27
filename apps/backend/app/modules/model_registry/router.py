from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.model_registry.repositories import (
    AgentModelBindingRepository,
    ModelRegistryRepository,
)
from app.modules.model_registry.schemas import (
    AgentModelBindingItem,
    AgentModelBindingsRead,
    AgentModelBindingsUpdate,
    BindingRole,
    PlatformModelCreate,
    PlatformModelListData,
    PlatformModelRead,
    PlatformModelUpdate,
)
from app.modules.model_registry.services import (
    create_platform_model,
    delete_platform_model,
    replace_agent_bindings,
    unbind_agent_role,
    update_platform_model,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

model_router = APIRouter(
    prefix="/platforms/{platform_id}/models", tags=["model-registry"]
)
binding_router = APIRouter(
    prefix="/platforms/{platform_id}/agents/{agent_id}/models",
    tags=["agent-model-bindings"],
)


async def _require_platform_admin(
    platform_id: int, user_id: int, session: AsyncSession
) -> None:
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, user_id
    )
    if platform is None:
        raise NotFoundException("platform not found")


async def _require_platform_agent(
    agent_id: int, platform_id: int, session: AsyncSession
) -> None:
    agent = await AgentRepository(session).get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")


def _model_read(model) -> PlatformModelRead:
    return PlatformModelRead.model_validate(
        {**model.__dict__, "has_api_key": bool(model.api_key_encrypted)}
    )


@model_router.get("", response_model=ApiResponse[PlatformModelListData])
async def list_models_endpoint(
    platform_id: int,
    model_type: str | None = None,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformModelListData]:
    await _require_platform_admin(platform_id, current_user.id, session)
    page = await ModelRegistryRepository(session).list_models(
        platform_id, params, model_type
    )
    page.items = [_model_read(item) for item in page.items]
    return success_response(
        data=PlatformModelListData.model_validate(page.model_dump()),
        message="models listed",
    )


@model_router.post(
    "",
    response_model=ApiResponse[PlatformModelRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_model_endpoint(
    platform_id: int,
    payload: PlatformModelCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformModelRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    model = await create_platform_model(
        ModelRegistryRepository(session), payload, platform_id=platform_id
    )
    return success_response(data=_model_read(model), message="model created")


@model_router.patch("/{model_id}", response_model=ApiResponse[PlatformModelRead])
async def update_model_endpoint(
    platform_id: int,
    model_id: int,
    payload: PlatformModelUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[PlatformModelRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = ModelRegistryRepository(session)
    model = await repo.get_for_platform(model_id, platform_id)
    if model is None:
        raise NotFoundException("model not found")
    updated = await update_platform_model(repo, model, payload)
    return success_response(data=_model_read(updated), message="model updated")


@model_router.delete("/{model_id}", response_model=ApiResponse)
async def delete_model_endpoint(
    platform_id: int,
    model_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = ModelRegistryRepository(session)
    model = await repo.get_for_platform(model_id, platform_id)
    if model is None:
        raise NotFoundException("model not found")
    await delete_platform_model(repo, model)
    return success_response(message="model deleted")


@binding_router.get("", response_model=ApiResponse[AgentModelBindingsRead])
async def list_agent_bindings_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentModelBindingsRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    await _require_platform_agent(agent_id, platform_id, session)
    bindings = await AgentModelBindingRepository(session).list_for_agent(agent_id)
    items = [
        AgentModelBindingItem(
            role=binding.role,
            model_id=binding.model.id,
            model_name=binding.model.model_name,
            model_type=binding.model.model_type,
            is_active=binding.model.is_active,
        )
        for binding in bindings
        if binding.model is not None
    ]
    return success_response(
        data=AgentModelBindingsRead(items=items), message="bindings listed"
    )


@binding_router.put("", response_model=ApiResponse[AgentModelBindingsRead])
async def replace_agent_bindings_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentModelBindingsUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentModelBindingsRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    await _require_platform_agent(agent_id, platform_id, session)
    bindings = await replace_agent_bindings(
        AgentModelBindingRepository(session),
        ModelRegistryRepository(session),
        agent_id=agent_id,
        platform_id=platform_id,
        payload=payload,
    )
    items = [
        AgentModelBindingItem(
            role=binding.role,
            model_id=binding.model.id,
            model_name=binding.model.model_name,
            model_type=binding.model.model_type,
            is_active=binding.model.is_active,
        )
        for binding in bindings
        if binding.model is not None
    ]
    return success_response(
        data=AgentModelBindingsRead(items=items), message="bindings replaced"
    )


@binding_router.delete("/{role}", response_model=ApiResponse)
async def unbind_agent_role_endpoint(
    platform_id: int,
    agent_id: int,
    role: BindingRole,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    await _require_platform_admin(platform_id, current_user.id, session)
    await _require_platform_agent(agent_id, platform_id, session)
    removed = await unbind_agent_role(
        AgentModelBindingRepository(session), agent_id=agent_id, role=role.value
    )
    if not removed:
        raise NotFoundException("binding not found")
    return success_response(message="binding removed")
