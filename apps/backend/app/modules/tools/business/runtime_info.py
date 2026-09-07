"""runtime_info 业务工具：返回当前 Agent 运行时信息（模型、配置、用量、版本）。

只读查询，输出字段走白名单：不含 api_key、base_url 等敏感配置。
用量来自 model_usage_records（当前会话 / 今日 / 累计 token）；身份来自 Agent 及其默认版本、
最近用量记录反查的 embed client。任何查询失败降级为对应字段 null，不向模型抛错。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.agent.models import Agent, AgentVersion
from app.modules.conversation.models import ModelUsageRecord
from app.modules.embed.models import PlatformEmbedClient
from app.modules.model_usage.repositories import ModelUsageRepository
from app.modules.model_usage.schemas import TokenUsageSummary
from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)

logger = get_logger(__name__)

# 累计用量查询的起始日期（远早于任何真实数据）
_TOTAL_USAGE_START_DATE = date(1970, 1, 1)
# 能力摘要白名单：只披露这三项布尔能力
_CAPABILITY_KEYS = ("image", "native_file", "text_retrieval")


def _usage_payload(summary: TokenUsageSummary | None) -> dict | None:
    if summary is None:
        return None
    return {
        "promptTokens": summary.prompt_tokens,
        "completionTokens": summary.completion_tokens,
        "totalTokens": summary.total_tokens,
        "messageCount": summary.record_count,
    }


async def _load_agent_with_version(session, *, platform_id: int, agent_id: int):
    """一次查询返回 Agent 与其默认版本，避免 async 懒加载。"""
    result = await session.execute(
        select(Agent, AgentVersion)
        .outerjoin(AgentVersion, AgentVersion.id == Agent.default_version_id)
        .where(Agent.id == agent_id, Agent.platform_id == platform_id)
    )
    return result.one_or_none()


async def _load_client_from_latest_usage(
    session, *, platform_id: int, agent_id: int, conversation_id: int
):
    """从当前会话最近一条用量记录反查 embed client（后台会话无 client_id 时返回 None）。"""
    client_id = await session.scalar(
        select(ModelUsageRecord.client_id)
        .where(
            ModelUsageRecord.platform_id == platform_id,
            ModelUsageRecord.agent_id == agent_id,
            ModelUsageRecord.conversation_id == conversation_id,
            ModelUsageRecord.client_id.isnot(None),
        )
        .order_by(ModelUsageRecord.created_at.desc(), ModelUsageRecord.id.desc())
        .limit(1)
    )
    if client_id is None:
        return None
    client = await session.scalar(
        select(PlatformEmbedClient).where(
            PlatformEmbedClient.platform_id == platform_id,
            PlatformEmbedClient.client_id == client_id,
        )
    )
    if client is None:
        return None
    return {"clientId": client.client_id, "name": client.name}


@business_tool(
    name="get_runtime_info",
    description=(
        "返回当前 Agent 的运行时信息：当前使用的模型名称、Agent 版本、服务版本、"
        "温度与能力配置，以及当前会话、今日与累计的 token 用量和连接身份。"
        "当用户询问你当前使用什么模型、配置如何、版本号、已消耗多少 token 或额度时调用；"
        "无输入参数，直接返回结果；结果中缺失或查询失败的字段为 null，不代表未发生用量。"
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)
async def get_runtime_info_business(args: dict, ctx: BusinessToolContext) -> dict:
    session = ctx.session
    settings = get_settings()
    repo = ModelUsageRepository(session)
    today = date.today()

    agent = None
    version = None
    try:
        row = await _load_agent_with_version(
            session, platform_id=ctx.platform_id, agent_id=ctx.agent_id
        )
        if row is not None:
            agent, version = row
    except Exception:
        agent, version = None, None

    conversation_summary = await _safe_call(
        repo.session_summary,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        conversation_id=ctx.conversation_id,
    )
    today_summary = await _safe_call(
        repo.summary,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        client_id=None,
        start_date=today,
        end_date=today,
    )
    total_summary = await _safe_call(
        repo.summary,
        platform_id=ctx.platform_id,
        agent_id=ctx.agent_id,
        client_id=None,
        start_date=_TOTAL_USAGE_START_DATE,
        end_date=today,
    )

    client = None
    try:
        client = await _load_client_from_latest_usage(
            session,
            platform_id=ctx.platform_id,
            agent_id=ctx.agent_id,
            conversation_id=ctx.conversation_id,
        )
    except Exception:
        client = None

    model = None
    if version is not None:
        capabilities = {
            key: True
            for key in _CAPABILITY_KEYS
            if (version.capabilities or {}).get(key)
        }
        model = {
            "name": version.model_name,
            "temperature": version.temperature,
            "capabilities": capabilities,
        }

    return {
        "model": model,
        "agent": (
            {"agentId": agent.id, "name": agent.name, "slug": agent.slug}
            if agent is not None
            else None
        ),
        "version": (
            {
                "agentVersion": version.version,
                "serviceVersion": settings.app_version,
                "sdkMinimumVersion": settings.sdk_minimum_version,
            }
            if version is not None
            else None
        ),
        "usage": {
            "conversation": _usage_payload(conversation_summary),
            "today": _usage_payload(today_summary.totals if today_summary else None),
            "total": _usage_payload(total_summary.totals if total_summary else None),
        },
        "client": client,
    }


async def _safe_call(method, **kwargs):
    """查询降级：失败返回 None，不向模型抛错。"""
    try:
        return await method(**kwargs)
    except Exception as exc:
        # 运行时信息是诊断工具，查询失败时仍需返回稳定结构；但不能完全
        # 吞掉异常，否则 WS/REST 两条工具链出现差异时无法定位上下文问题。
        logger.warning(
            "runtime info query failed method=%s conversation_id=%s agent_id=%s: %s",
            getattr(method, "__name__", type(method).__name__),
            kwargs.get("conversation_id"),
            kwargs.get("agent_id"),
            exc,
        )
        return None
