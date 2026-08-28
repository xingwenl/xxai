import asyncio
from types import SimpleNamespace

from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.tools.business.framework import BusinessToolError


class _EnabledRepo:
    async def is_enabled(self, platform_id, agent_id, tool_name):
        return True


class _DisabledRepo:
    async def is_enabled(self, platform_id, agent_id, tool_name):
        return False


def _fake_definition(handler):
    return SimpleNamespace(
        name="http_get",
        description="读取公开 HTTP/HTTPS URL",
        input_schema={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        executor=handler,
    )


def _run(**kwargs):
    values = dict(
        tool=SimpleNamespace(name="http_get"),
        call={"args": {"url": "https://example.com/data"}},
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=4,
        platform_end_user_id=None,
        session=object(),
    )
    values.update(kwargs)
    return asyncio.run(invoke_builtin_tool(_EnabledRepo(), object(), **values))


def test_invoke_delegates_to_business_handler_with_context(monkeypatch):
    captured = {}

    async def handler(args, ctx):
        captured["args"] = args
        captured["ctx"] = ctx
        return {"ok": True}

    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: _fake_definition(handler),
    )
    outcome = _run()

    assert outcome.status == "completed"
    assert outcome.result == {"ok": True}
    assert captured["args"] == {"url": "https://example.com/data"}
    ctx = captured["ctx"]
    assert ctx.platform_id == 1
    assert ctx.agent_id == 2
    assert ctx.conversation_id == 3
    assert ctx.user_id == 4


def test_invoke_maps_business_tool_error(monkeypatch):
    async def handler(args, ctx):
        raise BusinessToolError("image_required")

    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: _fake_definition(handler),
    )
    outcome = _run()

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "image_required"}}


def test_invoke_passes_through_http_status_code(monkeypatch):
    async def handler(args, ctx):
        raise BusinessToolError("upstream_http_error", status_code=404)

    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: _fake_definition(handler),
    )
    outcome = _run()

    assert outcome.status == "failed"
    assert outcome.result == {
        "error": {"code": "upstream_http_error", "status_code": 404}
    }


def test_invoke_falls_back_for_unexpected_exception(monkeypatch):
    async def handler(args, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: _fake_definition(handler),
    )
    outcome = _run()

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "tool_failed"}}


def test_invoke_rejects_invalid_arguments_without_calling_handler(monkeypatch):
    called = False

    async def handler(args, ctx):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: _fake_definition(handler),
    )
    outcome = _run(call={"args": {"url": 123}})

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "invalid_arguments"}}
    assert called is False


def test_invoke_returns_not_available_when_executor_missing(monkeypatch):
    monkeypatch.setattr(
        "app.modules.builtin_tool.services.get_builtin_tool",
        lambda _name: SimpleNamespace(
            name="ask_user",
            description="",
            input_schema={"type": "object", "properties": {}},
            executor=None,
        ),
    )
    outcome = _run()

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "tool_not_available"}}


def test_invoke_returns_not_available_when_disabled(monkeypatch):
    outcome = asyncio.run(
        invoke_builtin_tool(
            _DisabledRepo(),
            object(),
            tool=SimpleNamespace(name="http_get"),
            call={"args": {"url": "https://example.com/data"}},
            platform_id=1,
            agent_id=2,
            conversation_id=3,
        )
    )

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "tool_not_available"}}


def test_invoke_requires_conversation(monkeypatch):
    outcome = _run(conversation_id=None)

    assert outcome.status == "failed"
    assert outcome.result == {"error": {"code": "conversation_required"}}
