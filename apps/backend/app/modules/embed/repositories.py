from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embed.models import (
    PlatformEmbedClient,
    PlatformEmbedClientAgent,
    PlatformEndUser,
)
from app.modules.host_tool.models import EmbedClientHostTool, HostToolPolicy


class EmbedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_client(self, platform_id: int, client_id: str):
        return await self.session.scalar(
            select(PlatformEmbedClient).where(
                PlatformEmbedClient.platform_id == platform_id,
                PlatformEmbedClient.client_id == client_id,
            )
        )

    async def get_client_by_id(self, client_id: str):
        return await self.session.scalar(
            select(PlatformEmbedClient).where(
                PlatformEmbedClient.client_id == client_id
            )
        )

    async def list_clients(self, platform_id: int):
        result = await self.session.execute(
            select(PlatformEmbedClient)
            .where(PlatformEmbedClient.platform_id == platform_id)
            .order_by(PlatformEmbedClient.id)
        )
        return list(result.scalars().all())

    async def update_client(self, client, values: dict):
        for key, value in values.items():
            setattr(client, key, value)
        await self.session.commit()
        await self.session.refresh(client)
        return client

    async def rotate_secret(self, client, secret_hash: str):
        client.secret_hash = secret_hash
        await self.session.commit()
        await self.session.refresh(client)
        return client

    async def bind_agent(self, client_id: int, agent_id: int):
        binding = PlatformEmbedClientAgent(client_id=client_id, agent_id=agent_id)
        self.session.add(binding)
        await self.session.commit()
        return binding

    async def unbind_agent(self, client_id: int, agent_id: int):
        binding = await self.session.scalar(
            select(PlatformEmbedClientAgent).where(
                PlatformEmbedClientAgent.client_id == client_id,
                PlatformEmbedClientAgent.agent_id == agent_id,
            )
        )
        if binding is not None:
            await self.session.delete(binding)
            await self.session.commit()

    async def get_end_user(self, platform_id: int, external_user_id: str):
        return await self.session.scalar(
            select(PlatformEndUser).where(
                PlatformEndUser.platform_id == platform_id,
                PlatformEndUser.external_user_id == external_user_id,
            )
        )

    async def is_agent_allowed(self, client_id: int, agent_id: int) -> bool:
        return (
            await self.session.scalar(
                select(PlatformEmbedClientAgent.id).where(
                    PlatformEmbedClientAgent.client_id == client_id,
                    PlatformEmbedClientAgent.agent_id == agent_id,
                )
            )
            is not None
        )

    async def list_client_tool_names(self, client_id: int) -> set[str]:
        result = await self.session.execute(
            select(HostToolPolicy.name)
            .join(
                EmbedClientHostTool,
                EmbedClientHostTool.tool_id == HostToolPolicy.id,
            )
            .where(EmbedClientHostTool.client_id == client_id)
        )
        return set(result.scalars().all())

    async def create_client(self, **values):
        client = PlatformEmbedClient(**values)
        self.session.add(client)
        await self.session.flush()
        return client

    async def create_end_user(
        self, platform_id: int, external_user_id: str, display_name: str | None
    ):
        end_user = PlatformEndUser(
            platform_id=platform_id,
            external_user_id=external_user_id,
            display_name=display_name,
        )
        self.session.add(end_user)
        await self.session.flush()
        return end_user
