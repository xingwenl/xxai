"""为本地 SDK Demo 配置宿主工具策略和三重白名单。"""

import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.embed.models import PlatformEmbedClient
from app.modules.host_tool.models import (
    AgentHostTool,
    EmbedClientHostTool,
    HostToolPolicy,
)
from app.modules.host_tool.services import canonical_fingerprint


DEMO_TOOLS = (
    {
        "name": "get_weather",
        "description": "查询演示城市天气",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "calculate_total",
        "description": "计算两个数字之和",
        "input_schema": {
            "type": "object",
            "properties": {
                "left": {"type": "number"},
                "right": {"type": "number"},
            },
            "required": ["left", "right"],
        },
    },
    {
        "name": "get_order_status",
        "description": "查询演示订单状态",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
    },
)


async def seed() -> None:
    settings = get_settings()
    if not settings.embed_client_id or settings.embed_agent_id < 1:
        raise RuntimeError("请先配置 EMBED_CLIENT_ID 和 EMBED_AGENT_ID")

    async with get_session_factory()() as session:
        client = await session.scalar(
            select(PlatformEmbedClient).where(
                PlatformEmbedClient.client_id == settings.embed_client_id
            )
        )
        if client is None:
            raise RuntimeError("configured embed client not found")

        for definition in DEMO_TOOLS:
            policy = await session.scalar(
                select(HostToolPolicy).where(
                    HostToolPolicy.platform_id == client.platform_id,
                    HostToolPolicy.name == definition["name"],
                )
            )
            if policy is None:
                policy = HostToolPolicy(
                    platform_id=client.platform_id,
                    side_effect="none",
                    confirmation_policy="auto",
                    is_enabled=True,
                    **definition,
                    schema_fingerprint=canonical_fingerprint(
                        definition["input_schema"]
                    ),
                )
                session.add(policy)
                await session.flush()
            else:
                policy.description = definition["description"]
                policy.input_schema = definition["input_schema"]
                policy.schema_fingerprint = canonical_fingerprint(
                    definition["input_schema"]
                )
                policy.side_effect = "none"
                policy.confirmation_policy = "auto"
                policy.is_enabled = True

            agent_binding = await session.scalar(
                select(AgentHostTool).where(
                    AgentHostTool.agent_id == settings.embed_agent_id,
                    AgentHostTool.tool_id == policy.id,
                )
            )
            if agent_binding is None:
                session.add(
                    AgentHostTool(
                        agent_id=settings.embed_agent_id,
                        tool_id=policy.id,
                        is_enabled=True,
                    )
                )
            else:
                agent_binding.is_enabled = True

            client_binding = await session.scalar(
                select(EmbedClientHostTool).where(
                    EmbedClientHostTool.client_id == client.id,
                    EmbedClientHostTool.tool_id == policy.id,
                )
            )
            if client_binding is None:
                session.add(
                    EmbedClientHostTool(
                        client_id=client.id,
                        tool_id=policy.id,
                    )
                )

        await session.commit()
        print("已配置 Demo 宿主工具:", ", ".join(item["name"] for item in DEMO_TOOLS))


if __name__ == "__main__":
    asyncio.run(seed())
