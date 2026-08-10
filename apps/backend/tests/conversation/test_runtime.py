import asyncio
import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from app.modules.mcp.schemas import ToolInvocationOutcome

from app.modules.conversation.runtime import (
    build_agent_error_payload,
    extract_token_usage,
    format_sse_event,
    build_system_prompt,
    load_runtime_context,
    run_graph,
    stream_graph,
)
from app.modules.conversation.schemas import sanitize_content_blocks
from app.modules.conversation.services import build_loop_payload


def test_content_blocks_keep_supported_custom_blocks_and_reject_unsafe_values():
    blocks = sanitize_content_blocks(
        [
            {
                "id": "card",
                "type": "custom",
                "componentName": "OrderCard",
                "props": {"orderId": 3},
                "fallback": "订单详情",
            },
            {"id": "bad", "type": "image", "assetId": "../../secret"},
            {"id": "too-long", "type": "markdown", "text": "x" * 120_001},
        ]
    )
    assert blocks[0]["type"] == "custom"
    assert blocks[0]["component_name"] == "OrderCard"
    assert blocks[1]["type"] == "error"
    assert blocks[2]["type"] == "markdown"
    assert len(blocks[2]["text"]) == 100_000


def test_agent_upstream_502_is_mapped_to_safe_terminal_error():
    error = RuntimeError("HTTP 502 Bad Gateway from model proxy")

    assert build_agent_error_payload(error) == {
        "code": "agent_upstream_unavailable",
        "message": "Agent 连接失败（HTTP 502），本轮对话已结束",
        "retryable": True,
        "details": {
            "statusCode": "502",
            "error": "HTTP 502 Bad Gateway from model proxy",
            "exceptionType": "RuntimeError",
        },
    }

def test_build_loop_payload_includes_persisted_steps():
    class FakeLoopRepository:
        async def get_loop(self, loop_id, conversation_id):
            assert (loop_id, conversation_id) == (7, 11)
            return SimpleNamespace(
                id=7,
                request_id="conversation-11",
                status="completed",
                summary="已完成回答",
            )

        async def list_loop_steps(self, loop_id):
            assert loop_id == 7
            return [
                SimpleNamespace(
                    id=9,
                    sequence=1,
                    step_type="model_generation",
                    title="生成回答",
                    status="succeeded",
                    output_summary="生成 4 字符",
                    tool_name=None,
                    skill_name=None,
                    skill_version=None,
                    citation_refs=[],
                    error=None,
                )
            ]

    payload = asyncio.run(build_loop_payload(FakeLoopRepository(), 7, 11))

    assert payload == {
        "id": "7",
        "requestId": "conversation-11",
        "status": "completed",
        "summary": "已完成回答",
        "steps": [
            {
                "id": "9",
                "sequence": 1,
                "stepType": "model_generation",
                "title": "生成回答",
                "status": "succeeded",
                "outputSummary": "生成 4 字符",
                "toolName": None,
                "skillName": None,
                "skillVersion": None,
                "citationRefs": [],
                "error": None,
            }
        ],
    }


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
                skill=SimpleNamespace(instruction_template="second", package=None),
            ),
            SimpleNamespace(
                sort_order=1,
                skill=SimpleNamespace(instruction_template="first", package=None),
            ),
        ]


class FakeMcpRepository:
    async def list_enabled_tools_for_agent(self, agent_id, platform_id):
        return [SimpleNamespace(server_id=9, name="lookup", side_effect="none")]


class ScriptSkillRepository:
    def __init__(self, *, allowed: bool):
        self.allowed = allowed

    async def list_enabled_for_agent(self, agent_id, platform_id):
        package = SimpleNamespace(
            id=17,
            name="Report Skill",
            is_active=True,
            allow_script_execution=self.allowed,
            storage_path="/app/storage/skill-packages/2/report",
            files=[SimpleNamespace(relative_path="scripts/report.py", role="script")],
        )
        skill = SimpleNamespace(
            id=23,
            package=package,
            instruction_template="生成报告",
            package_skill_path="SKILL.md",
        )
        return [SimpleNamespace(sort_order=1, skill=skill)]


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
    assert len(context.skill_instructions) == 2
    assert all("load_skill" in instruction for instruction in context.skill_instructions)
    assert context.skill_instruction_tool.name == "load_skill"
    assert context.mcp_tools[0].name == "lookup"


def test_runtime_context_does_not_expose_scripts_without_permission():
    context = asyncio.run(
        load_runtime_context(
            FakeAgentRepository(),
            FakeKnowledgeRepository(),
            ScriptSkillRepository(allowed=False),
            FakeMcpRepository(),
            agent_id=11,
            platform_id=2,
        )
    )

    assert context.skill_script_tools == []


def test_runtime_context_exposes_scripts_alongside_mcp_tools():
    context = asyncio.run(
        load_runtime_context(
            FakeAgentRepository(),
            FakeKnowledgeRepository(),
            ScriptSkillRepository(allowed=True),
            FakeMcpRepository(),
            agent_id=11,
            platform_id=2,
        )
    )

    assert context.skill_script_tools[0].name == "run_skill_script_17"
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


def test_graph_injects_persisted_history_before_current_message():
    captured = []

    class HistoryModel:
        async def ainvoke(self, messages):
            captured.append(messages)
            return AIMessage(content="收到")

    history = [
        SimpleNamespace(role="user", content="我叫小明", tool_call_id=None),
        SimpleNamespace(role="assistant", content="你好，小明", tool_call_id=None),
        SimpleNamespace(role="tool", content="工具结果", tool_call_id="call-1"),
    ]
    asyncio.run(
        run_graph(
            HistoryModel(),
            system_prompt="系统",
            history=history,
            user_message="我叫什么？",
        )
    )

    assert [type(item).__name__ for item in captured[0]] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "HumanMessage",
    ]
    assert captured[0][-2].content == "工具结果"
    assert captured[0][-1].content == "我叫什么？"


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


class StreamingToolCallingModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        assert tools[0]["function"]["name"] == "lookup"
        return self

    async def astream(self, messages):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "lookup",
                        "args": '{"query":"退',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": None, "args": '款"}', "id": None, "index": 0}
                ],
            )
            return

        assert messages[-1].content == "结果"
        yield AIMessageChunk(content="最终")
        await asyncio.sleep(0)
        yield AIMessageChunk(
            content="答案",
            usage_metadata={
                "input_tokens": 8,
                "output_tokens": 2,
                "total_tokens": 10,
            },
        )


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
    assert result.tool_events[0]["tool_type"] == "mcp_tool"
    assert result.tool_events[0]["tool_call_id"] == "call-1"


def test_stream_graph_emits_tool_started_before_tool_finishes():
    async def run():
        tool = SimpleNamespace(
            name="lookup",
            description="查询",
            input_schema={"type": "object"},
            server_id=9,
        )
        release_tool = asyncio.Event()
        tool_invoked = asyncio.Event()

        async def invoke_tool_fn(**_kwargs):
            tool_invoked.set()
            await release_tool.wait()
            return ToolInvocationOutcome(status="completed", audit_id=1, result="结果")

        events = stream_graph(
            StreamingToolCallingModel(),
            system_prompt="回答问题",
            user_message="查询天气",
            tools=[tool],
            invoke_tool_fn=invoke_tool_fn,
        )
        first_event = await anext(events)
        assert first_event["type"] == "tool_started"
        assert first_event["tool"] == "lookup"
        await asyncio.sleep(0)
        assert not tool_invoked.is_set()

        release_tool.set()
        remaining = [event async for event in events]
        assert [event["type"] for event in remaining] == [
            "tool_completed",
            "message_delta",
            "message_delta",
            "completed",
        ]
        assert [event["content"] for event in remaining[1:3]] == ["最终", "答案"]
        assert remaining[-1]["result"].content == "最终答案"
        assert remaining[-1]["result"].usage == {
            "prompt_tokens": 8,
            "completion_tokens": 2,
            "total_tokens": 10,
        }

    asyncio.run(run())


def test_closing_stream_after_tool_started_does_not_invoke_tool():
    async def run():
        tool = SimpleNamespace(
            name="lookup",
            description="查询",
            input_schema={"type": "object"},
            server_id=9,
        )
        tool_invoked = False

        async def invoke_tool_fn(**_kwargs):
            nonlocal tool_invoked
            tool_invoked = True
            return ToolInvocationOutcome(status="completed", audit_id=1, result="结果")

        events = stream_graph(
            StreamingToolCallingModel(),
            system_prompt="回答问题",
            user_message="查询天气",
            tools=[tool],
            invoke_tool_fn=invoke_tool_fn,
        )
        assert (await anext(events))["type"] == "tool_started"
        await events.aclose()
        assert tool_invoked is False

    asyncio.run(run())


def test_skill_script_tool_is_routed_with_mcp_tools():
    script_tool = SimpleNamespace(
        name="run_skill_script_17",
        description="执行脚本",
        input_schema={"type": "object"},
        kind="skill_script",
    )
    mcp_tool = SimpleNamespace(
        name="lookup",
        description="查询",
        input_schema={"type": "object"},
        server_id=9,
    )
    invocations = []

    class MixedToolCallingModel(ToolCallingModel):
        def bind_tools(self, tools):
            assert [item["function"]["name"] for item in tools] == [
                "lookup",
                "run_skill_script_17",
            ]
            return self

    async def invoke_tool_fn(**kwargs):
        invocations.append(kwargs)
        return ToolInvocationOutcome(status="completed", audit_id=1, result="完成")

    result = asyncio.run(
        run_graph(
            MixedToolCallingModel("脚本结果", tool_name="run_skill_script_17"),
            system_prompt="回答问题",
            user_message="生成报告",
            tools=[mcp_tool, script_tool],
            invoke_tool_fn=invoke_tool_fn,
        )
    )

    assert result.content == "脚本结果"
    assert invocations == [
        {
            "tool": script_tool,
            "call": {
                "name": "run_skill_script_17",
                "args": {"query": "退款"},
                "id": "call-1",
                "type": "tool_call",
            },
        }
    ]
    assert result.tool_events[0]["tool_type"] == "skill_tool"


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


class FailingStreamingChatModel:
    async def astream(self, messages):
        raise RuntimeError("HTTP 502 Bad Gateway")
        yield  # pragma: no cover


def test_graph_stream_emits_terminal_error_without_completion():
    async def collect():
        return [
            item
            async for item in stream_graph(
                FailingStreamingChatModel(),
                system_prompt="回答问题",
                user_message="测试",
            )
        ]

    events = asyncio.run(collect())

    assert [item["type"] for item in events] == ["error"]
    assert events[0]["payload"]["code"] == "agent_upstream_unavailable"


class UsageStreamingChatModel:
    async def astream(self, messages):
        yield AIMessage(
            content="答案",
            usage_metadata={
                "input_tokens": 12,
                "output_tokens": 4,
                "total_tokens": 16,
            },
        )


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
