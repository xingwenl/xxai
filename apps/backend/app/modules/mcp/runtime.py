import json
import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.modules.agent.services import decrypt_secret
from app.modules.mcp.schemas import DiscoveredMcpTool
from app.shared.exceptions import BadRequestException, NotFoundException


def validate_mcp_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BadRequestException("MCP endpoint must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise BadRequestException("MCP endpoint must not contain credentials")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise BadRequestException("MCP endpoint is not public")
    return url


async def validate_mcp_target(url: str) -> str:
    validate_mcp_url(url)
    host = urlsplit(url).hostname
    addresses = await asyncio.get_running_loop().run_in_executor(
        None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    )
    if not addresses:
        raise BadRequestException("MCP endpoint cannot be resolved")
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except ValueError as exc:
            raise BadRequestException("MCP endpoint cannot be resolved") from exc
        if not address.is_global:
            raise BadRequestException("MCP endpoint is not public")
    return url


def _decode_headers(encrypted: str | None) -> dict[str, str]:
    if not encrypted:
        return {}
    try:
        values = json.loads(decrypt_secret(encrypted))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadRequestException("MCP authentication headers are invalid") from exc
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in values.items()
    ):
        raise BadRequestException("MCP authentication headers are invalid")
    return values


@asynccontextmanager
async def _official_session_factory(server, headers):
    await validate_mcp_target(server.endpoint_url)
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(
            server.endpoint_url, http_client=http_client
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                yield session


class StreamableHttpMcpClient:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or _official_session_factory

    async def list_tools(self, server) -> list[DiscoveredMcpTool]:
        headers = _decode_headers(server.auth_headers_encrypted)
        async with self.session_factory(server, headers) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                DiscoveredMcpTool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.inputSchema,
                )
                for tool in result.tools
            ]

    async def call_tool(self, server, name: str, arguments: dict):
        headers = _decode_headers(server.auth_headers_encrypted)
        async with self.session_factory(server, headers) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return result.model_dump(mode="json")


class RepositoryMcpExecutor:
    def __init__(self, repo, client: StreamableHttpMcpClient | None = None) -> None:
        self.repo = repo
        self.client = client or StreamableHttpMcpClient()

    async def __call__(self, server_id: int, tool_name: str, arguments: dict):
        server = await self.repo.get_server(server_id)
        if server is None or not server.is_active:
            raise NotFoundException("MCP server not found")
        return await self.client.call_tool(server, tool_name, arguments)
