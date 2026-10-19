"""按 Agent 绑定解析模型：辅助角色供工具与 embedding 运行时使用，chat 供对话主链路使用。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.services import decrypt_secret
from app.modules.model_registry.models import AgentModelBinding, PlatformModel
from app.shared.exceptions import AppException, BadRequestException

logger = logging.getLogger(__name__)

# 对话主模型的角色名，与 ModelType.CHAT / BindingRole.CHAT 保持同一字面量。
CHAT_ROLE = "chat"


class ChatModelUnavailable(AppException):
    """对话模型不可用：绑定存在但被停用、类型不符或密钥不可解。

    与辅助角色不同，这种情况**不**回落到 `.env` 默认值：`is_active` 的注释语义是
    「停用后不再参与能力路由」，静默回落会让管理员以为停用生效了，实际却仍在用
    一个他以为已经关掉的模型。`error_code` 是暴露给客户端的稳定错误码。
    """

    error_code = "chat_model_unavailable"

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=status.HTTP_409_CONFLICT)


@dataclass(frozen=True)
class ResolvedModel:
    """解析得到的可调用模型配置，字段语义与注册表条目一致。"""

    model_name: str
    base_url: str | None
    api_key: str | None
    capabilities: dict[str, Any] | None
    options: dict[str, Any]


def _resolved_from(model: PlatformModel, *, api_key: str | None) -> ResolvedModel:
    return ResolvedModel(
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=api_key,
        capabilities=model.capabilities,
        options=model.options or {},
    )


def _decrypt_model_key(model: PlatformModel, *, role: str, agent_id: int) -> str | None:
    """解密注册表条目的密钥；解密失败时按角色决定是回退还是明确失败。"""

    if not model.api_key_encrypted:
        return None
    try:
        return decrypt_secret(model.api_key_encrypted)
    except BadRequestException:
        logger.exception(
            "模型密钥解密失败 role=%s agent_id=%s model_id=%s",
            role,
            agent_id,
            model.id,
        )
        if role == CHAT_ROLE:
            raise ChatModelUnavailable(
                "该 Agent 绑定的对话模型密钥无法解密，请管理员在模型管理中重新填写 API Key"
            ) from None
        return None


async def resolve_agent_model(
    session: AsyncSession | None,
    *,
    platform_id: int,
    agent_id: int,
    role: str,
) -> ResolvedModel | None:
    """按能力角色解析 Agent 绑定的启用模型；未绑定或配置异常返回 None。

    返回 None 时调用方回退全局 `.env` 配置，保证未绑定 Agent 行为与既有实现一致。
    """
    if session is None:
        return None
    result = await session.execute(
        select(AgentModelBinding)
        .join(PlatformModel, PlatformModel.id == AgentModelBinding.model_id)
        .where(
            AgentModelBinding.agent_id == agent_id,
            AgentModelBinding.role == role,
            PlatformModel.platform_id == platform_id,
            PlatformModel.is_active.is_(True),
            PlatformModel.model_type == role,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None or binding.model is None:
        return None
    api_key = _decrypt_model_key(binding.model, role=role, agent_id=agent_id)
    return _resolved_from(binding.model, api_key=api_key)


async def resolve_chat_model(
    session: AsyncSession | None,
    *,
    platform_id: int,
    agent_id: int,
    model_id: int | None = None,
) -> ResolvedModel | None:
    """解析 Agent 的对话主模型；未绑定任何 chat 模型时返回 None。

    ``None`` 表示「该 Agent 没有绑定对话模型」，调用方据此回落到 `.env` 默认值；
    但**已绑定**的条目一旦不可用（停用、类型不符、密钥不可解、任务覆盖指向的条目
    不属于该平台）就抛 :class:`ChatModelUnavailable`，而不是静默换一个模型。

    ``model_id`` 是任务级覆盖（`tasks.model_id`），给出时以它为准。
    """
    if session is None:
        return None

    if model_id is not None:
        model = await _get_platform_model(session, model_id=model_id, platform_id=platform_id)
        if model is None:
            raise ChatModelUnavailable(
                "任务指定的对话模型不存在或不属于当前平台，请重新指定模型"
            )
        if model.model_type != CHAT_ROLE:
            raise ChatModelUnavailable("任务指定的模型不是对话模型，请改绑 chat 类型的模型")
        if not model.is_active:
            raise ChatModelUnavailable("任务指定的对话模型已被停用，请联系管理员")
        return _resolved_from(
            model,
            api_key=_decrypt_model_key(model, role=CHAT_ROLE, agent_id=agent_id),
        )

    result = await session.execute(
        select(AgentModelBinding)
        .join(PlatformModel, PlatformModel.id == AgentModelBinding.model_id)
        .where(
            AgentModelBinding.agent_id == agent_id,
            AgentModelBinding.role == CHAT_ROLE,
            PlatformModel.platform_id == platform_id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        # 没有绑定：回落 .env，这是开发环境可用的前提。
        return None
    model = binding.model
    if model is None or model.model_type != CHAT_ROLE:
        raise ChatModelUnavailable(
            "该 Agent 绑定的对话模型配置异常（条目缺失或类型不是 chat），请重新绑定模型"
        )
    if not model.is_active:
        raise ChatModelUnavailable(
            "该 Agent 绑定的对话模型已被停用，请联系管理员启用或重新绑定模型"
        )
    return _resolved_from(
        model,
        api_key=_decrypt_model_key(model, role=CHAT_ROLE, agent_id=agent_id),
    )


async def _get_platform_model(
    session: AsyncSession, *, model_id: int, platform_id: int
) -> PlatformModel | None:
    result = await session.execute(
        select(PlatformModel).where(
            PlatformModel.id == model_id,
            PlatformModel.platform_id == platform_id,
        )
    )
    return result.scalar_one_or_none()
