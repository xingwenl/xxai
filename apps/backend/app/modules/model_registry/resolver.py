"""按 Agent 绑定解析辅助模型，供工具与 embedding 运行时使用。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.services import decrypt_secret
from app.modules.model_registry.models import AgentModelBinding, PlatformModel
from app.shared.exceptions import BadRequestException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedModel:
    """解析得到的可调用模型配置，字段语义与注册表条目一致。"""

    model_name: str
    base_url: str | None
    api_key: str | None
    capabilities: dict[str, Any] | None
    options: dict[str, Any]


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
    api_key: str | None = None
    if binding.model.api_key_encrypted:
        try:
            api_key = decrypt_secret(binding.model.api_key_encrypted)
        except BadRequestException:
            logger.exception(
                "模型密钥解密失败，回退全局配置 role=%s agent_id=%s",
                role,
                agent_id,
            )
            return None
    return ResolvedModel(
        model_name=binding.model.model_name,
        base_url=binding.model.base_url,
        api_key=api_key,
        capabilities=binding.model.capabilities,
        options=binding.model.options or {},
    )
