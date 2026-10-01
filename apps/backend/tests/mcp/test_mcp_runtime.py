import asyncio
import ipaddress
import json
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import app.modules.mcp.runtime as mcp_runtime
from app.core.config import get_settings
from app.modules.agent.services import encrypt_secret
from app.modules.mcp.runtime import (
    StreamableHttpMcpClient,
    is_forbidden_address,
    validate_mcp_target,
    validate_mcp_url,
)
from app.shared.exceptions import BadRequestException


def _set_private_switch(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        mcp_runtime,
        "get_settings",
        lambda: SimpleNamespace(mcp_allow_private_endpoints=enabled),
    )


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
    _set_private_switch(monkeypatch, enabled=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", 0))
        ],
    )

    with pytest.raises(BadRequestException, match="not public"):
        asyncio.run(validate_mcp_target("https://internal.example.test/mcp"))


def test_validate_mcp_url_rejects_loopback_when_switch_disabled(monkeypatch) -> None:
    _set_private_switch(monkeypatch, enabled=False)

    with pytest.raises(BadRequestException, match="not public"):
        validate_mcp_url("http://127.0.0.1:4545/mcp")


def test_validate_mcp_url_allows_loopback_when_switch_enabled(monkeypatch) -> None:
    _set_private_switch(monkeypatch, enabled=True)

    assert validate_mcp_url("http://127.0.0.1:4545/mcp") == "http://127.0.0.1:4545/mcp"


def test_switch_enabled_still_rejects_link_local_and_metadata(monkeypatch) -> None:
    _set_private_switch(monkeypatch, enabled=True)

    with pytest.raises(BadRequestException, match="not public"):
        validate_mcp_url("http://169.254.169.254/latest/meta-data")
    assert is_forbidden_address(ipaddress.ip_address("169.254.169.254")) is True
    assert is_forbidden_address(ipaddress.ip_address("fe80::1")) is True


def test_switch_enabled_allows_hostname_resolving_to_private_ip(monkeypatch) -> None:
    _set_private_switch(monkeypatch, enabled=True)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0))
        ],
    )

    assert (
        asyncio.run(validate_mcp_target("http://mcp.internal.test/mcp"))
        == "http://mcp.internal.test/mcp"
    )


def test_switch_disabled_keeps_rejecting_private_and_loopback(monkeypatch) -> None:
    _set_private_switch(monkeypatch, enabled=False)

    assert is_forbidden_address(ipaddress.ip_address("10.0.0.9")) is True
    assert is_forbidden_address(ipaddress.ip_address("127.0.0.1")) is True
    assert is_forbidden_address(ipaddress.ip_address("::1")) is True
    assert is_forbidden_address(ipaddress.ip_address("8.8.8.8")) is False


def test_settings_reads_private_endpoint_switch(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ALLOW_PRIVATE_ENDPOINTS", "true")
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_allow_private_endpoints is True
    finally:
        get_settings.cache_clear()

    monkeypatch.setenv("MCP_ALLOW_PRIVATE_ENDPOINTS", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_allow_private_endpoints is False
    finally:
        get_settings.cache_clear()


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
