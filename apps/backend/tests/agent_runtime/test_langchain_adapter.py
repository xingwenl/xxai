import asyncio

from langchain_core.messages import AIMessage, AIMessageChunk

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome
from app.modules.agent_runtime.langchain_adapter import (
    LangChainModelInvoker,
    messages_for_model,
    model_turn_from_message,
    tool_message_from_outcome,
)


def test_model_turn_adapter_normalizes_tool_calls():
    turn = model_turn_from_message(
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "search", "args": {"q": "x"}}],
        )
    )

    assert turn.tool_calls == [ToolCall("c1", "search", {"q": "x"})]


def test_model_turn_adapter_carries_tool_type_from_registry():
    search = type(
        "Tool",
        (),
        {"name": "search", "kind": "builtin", "description": "", "input_schema": {}},
    )()
    mcp = type(
        "McpTool",
        (),
        {
            "name": "lookup",
            "server_id": 4,
            "description": "",
            "input_schema": {},
        },
    )()

    turn = model_turn_from_message(
        AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "search", "args": {}},
                {"id": "c2", "name": "lookup", "args": {}},
                {"id": "c3", "name": "missing", "args": {}},
            ],
        ),
        tools=[search, mcp],
    )

    assert [call.tool_type for call in turn.tool_calls] == [
        "builtin_tool",
        "mcp_tool",
        None,
    ]


def test_tool_outcome_adapter_preserves_error_for_model():
    message = tool_message_from_outcome(
        ToolCall("c1", "search"),
        ToolOutcome(status="failed", error={"code": "timeout"}),
    )

    assert message.tool_call_id == "c1"
    assert '"timeout"' in message.content


def test_messages_for_model_keeps_tool_call_association():
    messages = messages_for_model(
        [ToolOutcome(status="completed", call_id="c1", result={"ok": True})]
    )

    assert messages[0].tool_call_id == "c1"


def test_langchain_invoker_binds_tools_and_returns_model_turn():
    class Model:
        def __init__(self):
            self.bound = None

        def bind_tools(self, tools):
            self.bound = tools
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "search", "args": {"q": "x"}}],
            )

    tool = type(
        "Tool",
        (),
        {"name": "search", "description": "search", "input_schema": {"type": "object"}},
    )()
    model = Model()
    turn = asyncio.run(
        LangChainModelInvoker(model, [tool])([], emit=lambda _event: None)
    )

    assert model.bound[0]["function"]["name"] == "search"
    assert turn.tool_calls[0].name == "search"


def test_langchain_invoker_streams_thinking_and_text_separately():
    class ThinkingStreamingModel:
        async def astream(self, _messages):
            yield AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": "先分析问题"},
            )
            yield AIMessageChunk(content="正文回答")
            yield AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": "再补充校验"},
            )

    events = []

    async def emit(event):
        events.append(event)

    turn = asyncio.run(
        LangChainModelInvoker(
            ThinkingStreamingModel(), streaming=True
        )(
            [],
            emit=emit,
        )
    )

    assert [event.payload["content"] for event in events] == [
        "先分析问题",
        "正文回答",
        "再补充校验",
    ]
    assert [str(event.type) for event in events] == [
        "thinking_delta",
        "message_delta",
        "thinking_delta",
    ]
    assert turn.content == "正文回答"
    assert turn.metadata["thinking_text"] == "先分析问题再补充校验"


def test_langchain_invoker_non_streaming_carries_thinking_text():
    class ThinkingModel:
        async def ainvoke(self, _messages):
            return AIMessage(
                content="最终回答",
                additional_kwargs={"reasoning_content": "先思考再作答"},
            )

    turn = asyncio.run(
        LangChainModelInvoker(ThinkingModel())(
            [],
            emit=lambda _event: None,
        )
    )

    assert turn.content == "最终回答"
    assert turn.metadata["thinking_text"] == "先思考再作答"


def test_model_turn_adapter_normalizes_response_metadata_usage_fallback():
    turn = model_turn_from_message(
        AIMessage(
            content="答案",
            response_metadata={
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 4,
                    "total_tokens": 16,
                }
            },
        )
    )

    assert turn.metadata["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_model_turn_adapter_does_not_promote_invalid_tool_calls():
    turn = model_turn_from_message(
        AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "id": "partial-1",
                    "name": "write",
                    "args": "not-json",
                    "error": "invalid args",
                }
            ],
        )
    )

    assert turn.tool_calls == []


def test_model_turn_adapter_preserves_empty_content_turn():
    turn = model_turn_from_message(AIMessage(content=""))

    assert turn.content == ""
    assert turn.tool_calls == []
