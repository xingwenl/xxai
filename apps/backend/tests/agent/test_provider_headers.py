"""OpenCode 兼容请求头测试。

分两层：工具函数层锁定判定与合并语义；模型层用 httpx.MockTransport 抓真实
HTTP 请求头，断言上游实际收到什么，而不是只看对象内部字段。
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.modules.agent.provider_headers import (
    is_opencode_endpoint,
    merge_default_headers,
    resolve_session_id,
    session_headers,
)
from app.modules.agent.services import build_chat_model, encrypt_secret

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
OTHER_BASE_URL = "https://api.deepseek.com/v1"


@dataclass
class FakeVersion:
    id: int = 1
    agent_id: int = 1
    version: int = 1
    system_prompt: str = "help"
    model_name: str = "glm-5.2"
    api_key_encrypted: str | None = field(
        default_factory=lambda: encrypt_secret("sk-test")
    )
    published_at: datetime | None = None
    model_base_url: str | None = None
    temperature: float = 0.2
    model_options: dict[str, Any] = field(default_factory=dict)


def _completion_body() -> dict[str, Any]:
    return {
        "id": "1",
        "object": "chat.completion",
        "created": 0,
        "model": "glm-5.2",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _stream_body() -> bytes:
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "o"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "k"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    payloads = [
        "data: "
        + json.dumps(
            {
                "id": "1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "glm-5.2",
                **chunk,
            }
        )
        + "\n\n"
        for chunk in chunks
    ]
    payloads.append("data: [DONE]\n\n")
    return "".join(payloads).encode("utf-8")


class Recorder:
    """记录每次请求的请求头，并按请求体里的 stream 标记返回对应响应。"""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.headers.append({k.lower(): v for k, v in request.headers.items()})
        payload = json.loads(request.content or b"{}")
        if payload.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_stream_body(),
            )
        return httpx.Response(200, json=_completion_body())

    def model(self, *, base_url: str, session_id_provider=None, **option_overrides):
        recorder = self

        def handler(request: httpx.Request) -> httpx.Response:
            return recorder._handle(request)

        transport = httpx.MockTransport(handler)
        version = FakeVersion(
            model_base_url=base_url,
            model_options={
                "http_client": httpx.Client(transport=transport),
                "http_async_client": httpx.AsyncClient(transport=transport),
                **option_overrides,
            },
        )
        return build_chat_model(version, session_id_provider=session_id_provider)


# --- 工具函数层 ---------------------------------------------------------


def test_is_opencode_endpoint_matches_exact_host_only() -> None:
    assert is_opencode_endpoint("https://opencode.ai/zen/go/v1") is True
    assert is_opencode_endpoint("https://opencode.ai") is True
    # 子串匹配会把伪造域名当成 OpenCode，必须只认精确主机名。
    assert is_opencode_endpoint("https://notopencode.ai/v1") is False
    assert is_opencode_endpoint("https://opencode.ai.evil.test/v1") is False
    assert is_opencode_endpoint("https://api.deepseek.com/v1") is False
    assert is_opencode_endpoint(None) is False
    assert is_opencode_endpoint("") is False


def test_merge_default_headers_adds_client_identity_only_for_opencode() -> None:
    headers = merge_default_headers(OPENCODE_BASE_URL, None)
    assert headers == {"User-Agent": "ai-base/1.0", "x-opencode-client": "ai-base"}

    # 非 OpenCode 端点不注入任何东西，保证既有供应商请求头不变。
    assert merge_default_headers(OTHER_BASE_URL, None) is None
    assert merge_default_headers(OTHER_BASE_URL, {"X-Trace": "1"}) == {"X-Trace": "1"}


def test_merge_default_headers_lets_configured_values_win() -> None:
    headers = merge_default_headers(OPENCODE_BASE_URL, {"User-Agent": "my-agent/2.0"})
    assert headers == {
        "User-Agent": "my-agent/2.0",
        "x-opencode-client": "ai-base",
    }


def test_resolve_session_id_handles_missing_and_broken_providers() -> None:
    assert resolve_session_id(None) is None
    assert resolve_session_id(lambda: None) is None
    assert resolve_session_id(lambda: "   ") is None
    assert resolve_session_id(lambda: 42) == "42"

    def boom():
        raise RuntimeError("db down")

    # provider 异常不应中断对话，退化为不发送会话头。
    assert resolve_session_id(boom) is None


def test_session_headers_skip_non_opencode_or_configured_values() -> None:
    assert session_headers(OPENCODE_BASE_URL, "7") == {"x-opencode-session": "7"}
    assert session_headers(OPENCODE_BASE_URL, None) == {}
    assert session_headers(OTHER_BASE_URL, "7") == {}
    # 配置里显式固定了会话头时不再覆盖。
    assert (
        session_headers(OPENCODE_BASE_URL, "7", configured={"x-opencode-session": "x"})
        == {}
    )


# --- 模型层：抓真实请求头 -----------------------------------------------


def test_opencode_request_carries_session_and_client_headers() -> None:
    recorder = Recorder()
    model = recorder.model(base_url=OPENCODE_BASE_URL, session_id_provider=lambda: 42)

    asyncio.run(model.ainvoke("hi"))

    headers = recorder.headers[-1]
    assert headers["user-agent"] == "ai-base/1.0"
    assert headers["x-opencode-client"] == "ai-base"
    assert headers["x-opencode-session"] == "42"
    # 用户代理必须是自有名称，而不是通用 SDK 名（小写 user-agent 会退化成合并值）。
    assert "OpenAI/Python" not in headers["user-agent"]


def test_session_id_is_evaluated_per_call() -> None:
    recorder = Recorder()
    state = {"conversation_id": None}
    model = recorder.model(
        base_url=OPENCODE_BASE_URL,
        session_id_provider=lambda: state["conversation_id"],
    )

    # 首轮：会话尚未解析，只发送客户端标识，不发送会话头。
    asyncio.run(model.ainvoke("hi"))
    assert "x-opencode-session" not in recorder.headers[-1]

    # 会话解析后，同一客户端实例的下一次调用立刻带上真实会话 id。
    state["conversation_id"] = 7
    asyncio.run(model.ainvoke("hi again"))
    assert recorder.headers[-1]["x-opencode-session"] == "7"


def test_non_opencode_endpoint_gains_no_new_headers() -> None:
    recorder = Recorder()
    model = recorder.model(base_url=OTHER_BASE_URL, session_id_provider=lambda: 42)

    asyncio.run(model.ainvoke("hi"))

    headers = recorder.headers[-1]
    assert "x-opencode-session" not in headers
    assert "x-opencode-client" not in headers
    # 非 OpenCode 端点保留 SDK 默认 UA，说明我们完全没有改动它的请求头。
    assert "OpenAI/Python" in headers["user-agent"]


def test_configured_session_header_is_not_overridden() -> None:
    recorder = Recorder()
    model = recorder.model(
        base_url=OPENCODE_BASE_URL,
        session_id_provider=lambda: 42,
        default_headers={"x-opencode-session": "pinned"},
    )

    asyncio.run(model.ainvoke("hi"))

    headers = recorder.headers[-1]
    assert headers["x-opencode-session"] == "pinned"
    assert headers["user-agent"] == "ai-base/1.0"


def test_headers_survive_bind_tools_and_streaming() -> None:
    recorder = Recorder()
    model = recorder.model(base_url=OPENCODE_BASE_URL, session_id_provider=lambda: 42)

    async def run():
        bound = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        await bound.ainvoke("hi")
        chunks = [chunk async for chunk in model.astream("hi")]
        return chunks

    chunks = asyncio.run(run())

    assert "".join(chunk.content for chunk in chunks) == "ok"
    for headers in recorder.headers:
        assert headers["x-opencode-client"] == "ai-base"
        assert headers["x-opencode-session"] == "42"
        assert headers["user-agent"] == "ai-base/1.0"
