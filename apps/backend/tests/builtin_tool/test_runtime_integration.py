import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.modules.builtin_tool.schemas import BuiltinToolOutcome
from app.modules.conversation.runtime import run_graph


class BuiltinCallingModel:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools):
        assert tools[0]["function"]["name"] == "http_get"
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "http_get",
                        "args": {"url": "https://example.com/data"},
                        "id": "builtin-call-1",
                    }
                ],
            )
        assert '"kind": "json"' in messages[-1].content
        return AIMessage(content="读取完成")


def test_builtin_tool_uses_local_invoker_and_records_builtin_step_type() -> None:
    tool = SimpleNamespace(
        name="http_get",
        description="读取公开 URL",
        input_schema={"type": "object"},
        kind="builtin",
    )
    invocations = []

    async def invoke_tool_fn(**kwargs):
        invocations.append(kwargs)
        return BuiltinToolOutcome(
            status="completed", result={"kind": "json", "content": {"ok": True}}
        )

    result = asyncio.run(
        run_graph(
            BuiltinCallingModel(),
            system_prompt="回答问题",
            user_message="读取数据",
            tools=[tool],
            invoke_tool_fn=invoke_tool_fn,
        )
    )

    assert result.content == "读取完成"
    assert invocations[0]["tool"] is tool
    assert invocations[0]["call"]["id"] == "builtin-call-1"
    assert result.tool_events[0]["tool_type"] == "builtin_tool"
