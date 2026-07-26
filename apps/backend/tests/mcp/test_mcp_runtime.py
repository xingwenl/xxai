import asyncio
import json
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.modules.agent.services import encrypt_secret
from app.modules.mcp.runtime import (
    StreamableHttpMcpClient,
    validate_mcp_target,
    validate_mcp_url,
)
from app.shared.exceptions import BadRequestException


@dataclass
class FakeServer:
    endpoint_url: str = "https://mcp.example.test/mcp"
    auth_headers_encrypted: str | None = None


class FakeSession:
    def __init__(self) -> None:
        self.initialized = False
        self.calls = []

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        tool = SimpleNamespace(
            name="get_order",
            description="查询订单",
            inputSchema={"type": "object", "properties": {"id": {"type": "string"}}},
        )
        return SimpleNamespace(tools=[tool])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            model_dump=lambda mode: {"content": [{"type": "text", "text": "ok"}]}
        )


def test_validate_mcp_url_rejects_credentials_and_non_http() -> None:
    with pytest.raises(BadRequestException):
        validate_mcp_url("stdio:///tmp/server.py")
    with pytest.raises(BadRequestException):
        validate_mcp_url("https://user:pass@example.test/mcp")
    with pytest.raises(BadRequestException):
        validate_mcp_url("http://169.254.169.254/latest/meta-data")


def test_mcp_target_rejects_hostname_resolving_to_private_ip(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", 0))
        ],
    )

    with pytest.raises(BadRequestException, match="not public"):
        asyncio.run(validate_mcp_target("https://internal.example.test/mcp"))


def test_streamable_client_discovers_tools_and_decrypts_headers() -> None:
    async def run() -> None:
        session = FakeSession()
        observed_headers = {}

        @asynccontextmanager
        async def session_factory(server, headers):
            observed_headers.update(headers)
            yield session

        server = FakeServer(
            auth_headers_encrypted=encrypt_secret(
                json.dumps({"Authorization": "Bearer secret"})
            )
        )
        client = StreamableHttpMcpClient(session_factory=session_factory)

        tools = await client.list_tools(server)

        assert session.initialized is True
        assert observed_headers == {"Authorization": "Bearer secret"}
        assert tools[0].name == "get_order"
        assert tools[0].input_schema["type"] == "object"

    asyncio.run(run())


def test_streamable_client_calls_tool_and_returns_json_result() -> None:
    async def run() -> None:
        session = FakeSession()

        @asynccontextmanager
        async def session_factory(server, headers):
            yield session

        result = await StreamableHttpMcpClient(
            session_factory=session_factory
        ).call_tool(FakeServer(), "get_order", {"id": "A-1"})

        assert result["content"][0]["text"] == "ok"
        assert session.calls == [("get_order", {"id": "A-1"})]

    asyncio.run(run())
