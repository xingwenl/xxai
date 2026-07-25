import asyncio
from dataclasses import dataclass

from app.modules.agent.services import decrypt_secret
from app.modules.mcp.schemas import McpServerCreate
from app.modules.mcp.services import (
    create_mcp_server,
    policy_after_schema_sync,
    sync_mcp_tools,
)
from app.modules.mcp.schemas import DiscoveredMcpTool


@dataclass
class FakeServer:
    id: int
    platform_id: int
    name: str
    slug: str
    endpoint_url: str
    auth_headers_encrypted: str | None


class FakeRepository:
    def __init__(self) -> None:
        self.server = None
        self.tools = {}

    async def get_server_by_slug(self, platform_id, slug):
        return self.server if self.server and self.server.slug == slug else None

    async def create_server(self, platform_id, payload):
        self.server = FakeServer(
            1,
            platform_id,
            payload.name,
            payload.slug,
            payload.endpoint_url,
            payload.auth_headers,
        )
        return self.server

    async def sync_tools(self, server_id, tools):
        for tool in tools:
            current = self.tools.get(tool.name)
            if current is None:
                self.tools[tool.name] = {
                    "name": tool.name,
                    "is_allowed": False,
                    "side_effect": "external",
                }
        return list(self.tools.values())


class FakeClient:
    async def list_tools(self, server):
        return [
            DiscoveredMcpTool(
                name="cancel_order",
                description="取消订单",
                input_schema={"type": "object"},
            )
        ]


def test_create_server_encrypts_auth_headers() -> None:
    async def run() -> None:
        server = await create_mcp_server(
            FakeRepository(),
            1,
            McpServerCreate(
                name="订单 MCP",
                slug="orders",
                endpoint_url="https://mcp.example.test/mcp",
                auth_headers={"Authorization": "Bearer secret"},
            ),
        )

        assert "secret" not in server.auth_headers_encrypted
        assert "Bearer secret" in decrypt_secret(server.auth_headers_encrypted)

    asyncio.run(run())


def test_newly_discovered_tool_defaults_to_denied_high_risk() -> None:
    async def run() -> None:
        repo = FakeRepository()
        server = FakeServer(
            1, 1, "订单 MCP", "orders", "https://example.test/mcp", None
        )

        tools = await sync_mcp_tools(repo, FakeClient(), server)

        assert tools[0]["is_allowed"] is False
        assert tools[0]["side_effect"] == "external"

    asyncio.run(run())


def test_tool_sync_preserves_existing_policy() -> None:
    async def run() -> None:
        repo = FakeRepository()
        repo.tools["cancel_order"] = {
            "name": "cancel_order",
            "is_allowed": True,
            "side_effect": "write",
        }
        server = FakeServer(
            1, 1, "订单 MCP", "orders", "https://example.test/mcp", None
        )

        tools = await sync_mcp_tools(repo, FakeClient(), server)

        assert tools[0]["is_allowed"] is True
        assert tools[0]["side_effect"] == "write"

    asyncio.run(run())


def test_changed_tool_schema_resets_existing_allow_policy() -> None:
    allowed, side_effect = policy_after_schema_sync(
        previous_schema={"type": "object", "required": ["id"]},
        discovered_schema={"type": "object", "required": ["id", "reason"]},
        is_allowed=True,
        side_effect="write",
    )

    assert allowed is False
    assert side_effect == "external"
