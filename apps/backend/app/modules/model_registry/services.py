from __future__ import annotations

from typing import Any

from app.modules.agent.services import encrypt_secret
from app.modules.model_registry.models import AgentModelBinding, PlatformModel
from app.modules.model_registry.schemas import (
    AgentModelBindingsUpdate,
    PlatformModelCreate,
    PlatformModelUpdate,
)
from app.shared.exceptions import BadRequestException, ConflictException


async def create_platform_model(
    repo, payload: PlatformModelCreate, *, platform_id: int
) -> PlatformModel:
    values = payload.model_dump(exclude={"api_key"}, mode="json")
    api_key = payload.api_key
    if api_key:
        values["api_key_encrypted"] = encrypt_secret(api_key)
    existing = await repo.get_by_type_and_name(
        platform_id, values["model_type"], values["model_name"]
    )
    if existing is not None:
        raise ConflictException("model already exists")
    return await repo.create(platform_id=platform_id, **values)


async def update_platform_model(
    repo, model: PlatformModel, payload: PlatformModelUpdate
) -> PlatformModel:
    values = payload.model_dump(exclude_unset=True, exclude={"api_key"}, mode="json")
    if payload.api_key:
        values["api_key_encrypted"] = encrypt_secret(payload.api_key)
    if "model_type" in values or "model_name" in values:
        new_type = values.get("model_type", model.model_type)
        new_name = values.get("model_name", model.model_name)
        existing = await repo.get_by_type_and_name(
            model.platform_id, new_type, new_name
        )
        if existing is not None and existing.id != model.id:
            raise ConflictException("model already exists")
    return await repo.update(model, **values)


async def delete_platform_model(repo, model: PlatformModel) -> None:
    if await repo.count_bindings(model.id) > 0:
        raise ConflictException("model_in_use")
    await repo.delete(model)


async def replace_agent_bindings(
    binding_repo,
    model_repo,
    *,
    agent_id: int,
    platform_id: int,
    payload: AgentModelBindingsUpdate,
) -> list[AgentModelBinding]:
    """整体替换 Agent 的模型绑定，事务内完成避免半更新状态。"""
    validated: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for item in payload.bindings:
        role = item.role.value
        if role in seen_roles:
            raise BadRequestException("duplicate binding role")
        seen_roles.add(role)
        model = await model_repo.get_for_platform(item.model_id, platform_id)
        if model is None:
            raise BadRequestException("model not found")
        if not model.is_active:
            raise BadRequestException("model_not_active")
        if model.model_type != role:
            raise BadRequestException("model_type_mismatch")
        validated.append({"agent_id": agent_id, "model_id": model.id, "role": role})

    await binding_repo.delete_for_agent(agent_id)
    bindings = [AgentModelBinding(**values) for values in validated]
    for binding in bindings:
        binding_repo.session.add(binding)
    await binding_repo.session.commit()
    for binding in bindings:
        await binding_repo.session.refresh(binding)
    return await binding_repo.list_for_agent(agent_id)


async def unbind_agent_role(binding_repo, *, agent_id: int, role: str) -> bool:
    binding = await binding_repo.get_for_agent_role(agent_id, role)
    if binding is None:
        return False
    await binding_repo.session.delete(binding)
    await binding_repo.session.commit()
    return True
