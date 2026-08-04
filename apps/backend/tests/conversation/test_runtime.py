import asyncio
import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from app.modules.mcp.schemas import ToolInvocationOutcome

from app.modules.conversation.runtime import (
    extract_token_usage,
    format_sse_event,
    build_system_prompt,
    load_runtime_context,
    run_graph,
    stream_graph,
)


class FakeAgentRepository:
    async def get_published_agent(self, agent_id, platform_id):
        return SimpleNamespace(
            id=agent_id,
            platform_id=platform_id,
            default_version_id=7,
            default_version=SimpleNamespace(
                id=7, system_prompt="base prompt", published_at=True
            ),
        )


class FakeKnowledgeRepository:
    async def list_enabled_for_agent(self, agent_id, platform_id):
        return [SimpleNamespace(id=3, active_index_version=1)]


class FakeSkillRepository:
    async def list_enabled_for_agent(self, agent_id, platform_id):
        return [
            SimpleNamespace(
                sort_order=2,
                skill=SimpleNamespace(instruction_template="second"),
            ),
            SimpleNamespace(
                sort_order=1,
                skill=SimpleNamespace(instruction_template="first"),
            ),
        ]


class FakeMcpRepository:
    async def list_enabled_tools_for_agent(self, agent_id, platform_id):
        return [SimpleNamespace(server_id=9, name="lookup", side_effect="none")]


def test_system_prompt_explains_available_host_tools():
    prompt = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        host_tools=[
            SimpleNamespace(
                name="navigate_to_page",
                description="打开后台已有页面",
                input_schema={"type": "object"},
            )
        ],
    )

    assert "navigate_to_page" in prompt
    assert "打开后台已有页面" in prompt
    assert "用户询问可用工具时" in prompt


def test_runtime_context_only_loads_published_bound_capabilities():
    context = asyncio.run(
        load_runtime_context(
            FakeAgentRepository(),
            FakeKnowledgeRepository(),
            FakeSkillRepository(),
            FakeMcpRepository(),
            agent_id=11,
            platform_id=2,
        )
    )

    assert context.agent.id == 11
    assert [item.id for item in context.knowledge_bases] == [3]
    assert context.skill_instructions == ["first", "second"]
    assert context.mcp_tools[0].name == "lookup"


def test_runtime_context_logs_loaded_knowledge_and_tool_counts(caplog):
    caplog.set_level(logging.INFO)

    asyncio.run(
        load_runtime_context(
            FakeAgentRepository(),
            FakeKnowledgeRepository(),
            FakeSkillRepository(),
            FakeMcpRepository(),
            agent_id=11,
            platform_id=2,
        )
    )

    assert "Loaded runtime context" in caplog.text
    assert "knowledge_bases=[3]" in caplog.text
    assert "skill_count=2" in caplog.text
    assert "mcp_tool_count=1" in caplog.text


def test_runtime_context_rejects_agent_without_published_version():
    class UnpublishedAgentRepository(FakeAgentRepository):
        async def get_published_agent(self, agent_id, platform_id):
            return None

    with pytest.raises(LookupError, match="published agent"):
        asyncio.run(
            load_runtime_context(
                UnpublishedAgentRepository(),
                FakeKnowledgeRepository(),
                FakeSkillRepository(),
                FakeMcpRepository(),
                agent_id=11,
                platform_id=2,
            )
        )


class FakeChatModel:
    async def ainvoke(self, messages):
        assert "退款规则" in messages[-1].content
        return AIMessage(content="退款规则是 30 天内申请。")


def test_graph_returns_answer_with_structured_citations():
    result = asyncio.run(
        run_graph(
            FakeChatModel(),
            system_prompt="回答问题",
            user_message="退款规则是什么？",
            citations=[
                {
                    "title": "退款政策",
                    "source_url": "https://example.test/refund",
                    "text": "30 天内可申请退款。",
                }
            ],
        )
    )

    assert result.content == "退款规则是 30 天内申请。"
    assert result.citations[0]["title"] == "退款政策"
    assert result.knowledge_grounded is True


class ToolCallingModel:
    def __init__(self, second_response, tool_name="lookup"):
        self.calls = 0
        self.second_response = second_response
        self.tool_name = tool_name

    def bind_tools(self, tools):
        assert tools[0]["function"]["name"] in {"lookup", "refund"}
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": self.tool_name,
                        "args": {"query": "退款"},
                        "id": "call-1",
                    }
                ],
            )
        return AIMessage(content=self.second_response)


def test_read_only_tool_result_is_returned_to_model():
    tool = SimpleNamespace(
        name="lookup",
        description="查询",
        input_schema={"type": "object"},
        server_id=9,
    )
    invocations = []

    async def invoke_tool_fn(**kwargs):
        invocations.append(kwargs)
        return ToolInvocationOutcome(status="completed", audit_id=1, result="结果")

    result = asyncio.run(
        run_graph(
            ToolCallingModel("最终答案"),
            system_prompt="回答问题",
            user_message="退款规则是什么？",
            tools=[tool],
            invoke_tool_fn=invoke_tool_fn,
        )
    )

    assert result.content == "最终答案"
    assert invocations == [
        {"server_id": 9, "tool_name": "lookup", "arguments": {"query": "退款"}}
    ]


def test_side_effect_tool_stops_with_confirmation():
    tool = SimpleNamespace(
        name="refund",
        description="退款",
        input_schema={"type": "object"},
        server_id=9,
    )
    executed = []

    async def invoke_tool_fn(**kwargs):
        executed.append(kwargs)
        return ToolInvocationOutcome(
            status="confirmation_required", audit_id=2, confirmation_id=8
        )

    result = asyncio.run(
        run_graph(
            ToolCallingModel("不会被调用", tool_name="refund"),
            system_prompt="回答问题",
            user_message="帮我退款",
            tools=[tool],
            invoke_tool_fn=invoke_tool_fn,
        )
    )

    assert result.pending_confirmation_id == 8
    assert result.content == ""
    assert len(executed) == 1


def test_sse_event_has_stable_envelope_and_event_name():
    event = format_sse_event(
        {
            "type": "message_completed",
            "conversation_id": 3,
            "message_id": 4,
            "sequence": 2,
            "payload": {"content": "完成"},
        }
    )

    assert event.startswith("event: message_completed\n")
    assert '"sequence":2' in event
    assert event.endswith("\n\n")


class StreamingChatModel:
    async def astream(self, messages):
        for content in ("退款", "规则是 30 天。"):
            yield AIMessage(content=content)


class UsageStreamingChatModel:
    async def astream(self, messages):
        yield AIMessage(content="答案", usage_metadata={
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
        })


def test_extract_token_usage_normalizes_langchain_usage_metadata():
    message = AIMessage(
        content="答案",
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
        },
    )

    assert extract_token_usage(message) == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_graph_stream_includes_usage_on_completed_result():
    async def collect():
        async for item in stream_graph(
            UsageStreamingChatModel(),
            system_prompt="回答问题",
            user_message="测试",
        ):
            if item["type"] == "completed":
                return item["result"]
        raise AssertionError("completed event not emitted")

    result = asyncio.run(collect())

    assert result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_graph_streams_model_deltas_and_returns_final_result():
    async def collect():
        deltas = []
        final = None
        async for item in stream_graph(
            StreamingChatModel(),
            system_prompt="回答问题",
            user_message="退款规则是什么？",
        ):
            if item["type"] == "message_delta":
                deltas.append(item["content"])
            else:
                final = item
        return deltas, final

    deltas, final = asyncio.run(collect())

    assert deltas == ["退款", "规则是 30 天。"]
    assert final["result"].content == "退款规则是 30 天。"
