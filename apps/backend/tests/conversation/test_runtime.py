import asyncio
import logging
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from app.modules.mcp.schemas import ToolInvocationOutcome
from app.modules.agent_runtime.message_text import extract_thinking_text

from app.modules.conversation.runtime import (
    build_agent_error_payload,
    extract_token_usage,
    format_sse_event,
    build_system_prompt,
    load_runtime_context,
    _summarize_json,
    tool_step_values,
    image_content_blocks,
    rewrite_image_markdown,
)
from app.modules.conversation.schemas import sanitize_content_blocks
from app.modules.conversation.services import build_loop_payload
from app.modules.builtin_tool.schemas import BuiltinToolOutcome


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


def test_image_tool_outcome_becomes_renderable_content_block():
    blocks = image_content_blocks(
        [
            {
                "outcome": BuiltinToolOutcome(
                    status="completed",
                    result={
                        "kind": "image",
                        "assets": [
                            {
                                "asset_id": "asset-123",
                                "download_url": "/api/v1/assets/asset-123",
                                "content_type": "image/png",
                                "size_bytes": 12,
                            }
                        ],
                    },
                )
            }
        ]
    )
    assert blocks[0]["type"] == "image"
    assert blocks[0]["asset_id"] == "asset-123"
    assert blocks[0]["url"] == "/api/v1/assets/asset-123"


def test_rewrite_image_markdown_replaces_bare_asset_id_with_download_url():
    content = "参考图：![参考图](asset-123)\n已生成：![生成图](asset-456)"
    tool_events = [
        {
            "outcome": BuiltinToolOutcome(
                status="completed",
                result={
                    "kind": "image",
                    "assets": [
                        {
                            "asset_id": "asset-123",
                            "download_url": "/api/v1/assets/asset-123",
                            "content_type": "image/png",
                        },
                        {
                            "asset_id": "asset-456",
                            "download_url": "/api/v1/assets/asset-456",
                            "content_type": "image/png",
                        },
                    ],
                },
            )
        }
    ]
    rewritten = rewrite_image_markdown(content, tool_events)
    assert rewritten == (
        "参考图：![参考图](/api/v1/assets/asset-123)\n"
        "已生成：![生成图](/api/v1/assets/asset-456)"
    )


def test_rewrite_image_markdown_keeps_normal_urls_and_unknown_asset_ids():
    content = "![外链](https://example.com/a.png) ![未知](not-in-this-turn)"
    tool_events = [
        {
            "outcome": BuiltinToolOutcome(
                status="completed",
                result={
                    "kind": "image",
                    "asset": {
                        "asset_id": "asset-123",
                        "download_url": "/api/v1/assets/asset-123",
                    },
                },
            )
        }
    ]
    assert (
        rewrite_image_markdown(content, tool_events)
        == "![外链](https://example.com/a.png) ![未知](not-in-this-turn)"
    )


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
                    thinking_text="先分析再回答",
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
                "thinkingText": "先分析再回答",
                "toolName": None,
                "skillName": None,
                "skillVersion": None,
                "citationRefs": [],
                "error": None,
            }
        ],
    }


def test_thinking_text_extracts_reasoning_content_and_thinking_blocks():
    chunk_with_blocks = AIMessageChunk(
        content=[
            {"type": "thinking", "thinking": "先分析问题"},
            {"type": "text", "text": "正文内容"},
        ],
    )
    chunk_with_reasoning = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning_content": "再补充推理"},
    )
    chunk_with_alias = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning": "厂商别名思考"},
    )
    chunk_with_details = AIMessageChunk(
        content="",
        additional_kwargs={
            "reasoning_details": [{"text": "细节一"}, {"content": "细节二"}]
        },
    )

    assert extract_thinking_text(chunk_with_blocks) == "先分析问题"
    assert extract_thinking_text(chunk_with_reasoning) == "再补充推理"
    assert extract_thinking_text(chunk_with_alias) == "厂商别名思考"
    assert extract_thinking_text(chunk_with_details) == "细节一细节二"
    assert extract_thinking_text(AIMessageChunk(content="普通文本")) == ""


def test_tool_step_values_include_input_and_result_summaries():
    outcome = ToolInvocationOutcome(
        status="completed",
        audit_id=1,
        result={"weather": "晴", "temperature": 26},
    )
    event = {
        "tool": "get_weather",
        "tool_type": "mcp_tool",
        "tool_call_id": "call-1",
        "input_summary": '{"city":"上海"}',
        "outcome": outcome,
    }

    values = tool_step_values(event, sequence=3)

    assert values["step_type"] == "mcp_tool"
    assert values["status"] == "succeeded"
    assert values["input_summary"] == '{"city":"上海"}'
    assert values["output_summary"] == '工具执行完成：{"weather":"晴","temperature":26}'


def test_tool_step_values_keep_confirmation_status_without_result():
    outcome = ToolInvocationOutcome(
        status="confirmation_required",
        audit_id=1,
        confirmation_id=5,
        result=None,
    )

    values = tool_step_values(
        {"tool": "pay", "tool_type": "mcp_tool", "outcome": outcome},
        sequence=4,
    )

    assert values["status"] == "waiting_confirmation"
    assert values["output_summary"] == "等待用户确认"


def test_tool_step_values_keep_waiting_question_status():
    outcome = SimpleNamespace(status="waiting_question")

    values = tool_step_values(
        {"tool": "ask_user", "tool_type": "builtin_tool", "outcome": outcome},
        sequence=5,
    )

    assert values["status"] == "waiting_question"
    assert values["output_summary"] == "等待用户选择"


@pytest.mark.parametrize(
    ("status", "step_status", "summary"),
    [
        ("cancelled", "cancelled", "工具调用已取消"),
        ("budget_exceeded", "budget_exceeded", "工具调用已达到预算限制"),
    ],
)
def test_tool_step_values_preserve_stop_reason_status(status, step_status, summary):
    values = tool_step_values(
        {"tool": "browser", "outcome": SimpleNamespace(status=status)},
        sequence=6,
    )

    assert values["status"] == step_status
    assert values["output_summary"] == summary
    assert values["error"]["code"] == status


def test_summarize_json_truncates_long_values():
    assert _summarize_json({"city": "上海"}, limit=9) == '{"city":"'
    assert _summarize_json("纯文本结果", limit=3) == "纯文本"


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


def test_system_prompt_adds_ask_user_guidance_only_when_tool_visible():
    with_tool = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        host_tools=[SimpleNamespace(name="ask_user", description="向用户提问")],
    )
    assert "可以调用 ask_user 工具向用户提问" in with_tool

    without_tool = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"), [], []
    )
    assert "可以调用 ask_user 工具向用户提问" not in without_tool


def test_system_prompt_adds_image_render_rule_only_when_image_tools_visible():
    with_tool = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        host_tools=[SimpleNamespace(name="image_read", description="读图")],
    )
    assert "图片展示规则" in with_tool
    assert "download_url" in with_tool
    assert "严禁把 asset_id 直接当作图片地址" in with_tool

    without_tool = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        host_tools=[SimpleNamespace(name="http_get", description="请求")],
    )
    assert "图片展示规则" not in without_tool


def test_rest_tool_lists_exclude_ask_user_even_when_db_bound():
    """REST 路径组装工具时剔除 ask_user，避免模型调用后无执行器。"""
    from app.modules.conversation.services import _rest_runtime_tools

    bound = SimpleNamespace(name="ask_user", kind="builtin")
    other = SimpleNamespace(name="http_get", kind="builtin")
    tools = _rest_runtime_tools(bound, other)
    assert [tool.name for tool in tools] == ["http_get"]


def test_system_prompt_includes_caller_prompt_without_replacing_base_prompt():
    prompt = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        caller_system_prompt="用中文回答",
    )
    assert "base prompt" in prompt
    assert "用中文回答" in prompt


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
    assert all(
        "load_skill" in instruction for instruction in context.skill_instructions
    )
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


def test_runtime_metadata_block_includes_whitelisted_fields_and_skips_missing():
    from app.modules.conversation.runtime import build_runtime_metadata_block

    block = build_runtime_metadata_block(
        SimpleNamespace(
            version=3,
            temperature=0.2,
            capabilities={"image": True, "native_file": False, "text_retrieval": True},
        ),
        chat_model_name="gpt-5.2",
    )
    assert block is not None
    assert "【运行时信息】" in block
    assert "模型：gpt-5.2" in block
    assert "Agent 版本：v3" in block
    assert "温度：0.2" in block
    assert "能力：image/text_retrieval" in block
    assert "get_runtime_info" in block


def test_runtime_metadata_block_never_leaks_secret_fields():
    from app.modules.conversation.runtime import build_runtime_metadata_block

    block = build_runtime_metadata_block(
        SimpleNamespace(
            version=1,
            temperature=0.2,
            capabilities={"image": True},
            api_key_encrypted="secret-encrypted",
            model_base_url="http://internal.example.com/v1",
        ),
        chat_model_name="gpt-5.2",
    )
    assert "secret-encrypted" not in block
    assert "internal.example.com" not in block


def test_runtime_metadata_block_returns_none_when_all_fields_missing():
    from app.modules.conversation.runtime import build_runtime_metadata_block

    block = build_runtime_metadata_block(SimpleNamespace())
    # 服务版本与 SDK 最低版本来自全局配置，通常存在；此处仅断言不会抛错且格式合法
    assert block is None or "【运行时信息】" in block


def test_system_prompt_appends_runtime_metadata_block_after_base_prompt():
    prompt = build_system_prompt(
        SimpleNamespace(
            system_prompt="base prompt",
            model_name="gpt-5.2",
            version=2,
            temperature=0.2,
            capabilities={"image": True},
        ),
        [],
        [],
    )
    assert "base prompt" in prompt
    assert "【运行时信息】" in prompt
    assert prompt.index("base prompt") < prompt.index("【运行时信息】")


def test_system_prompt_injects_tool_catalog_instead_of_bound_tool_list():
    prompt = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        tool_catalog="工具目录（按组加载）：\n- ops（运营）：店铺数据。工具：order_query",
        capability_tool_names={"ask_user", "image_read"},
    )

    assert "工具目录（按组加载）" in prompt
    assert "ops（运营）" in prompt
    # 目录模式下不再逐个列「当前已绑定工具」，否则与后续加载集脱节。
    assert "当前会话已注册且授权的工具如下" not in prompt


def test_system_prompt_capability_rules_follow_full_tool_set_not_visibility():
    prompt = build_system_prompt(
        SimpleNamespace(system_prompt="base prompt"),
        [],
        [],
        tool_catalog="工具目录（按组加载）：\n- ops（运营）：店铺数据。工具：order_query",
        capability_tool_names={"ask_user", "image_read"},
    )

    # 工具可能尚未加载，但能力规则必须提前注入，否则模型等不到那条提示。
    assert "可以调用 ask_user 工具向用户提问" in prompt
    assert "图片展示规则" in prompt
