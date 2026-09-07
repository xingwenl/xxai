"""REST 非流式 / REST SSE 灰度入口与 legacy Graph 的行为一致性测试。

灰度开关本身不改变 REST 公开协议；这里用替身仓库直接驱动服务层
``execute_chat``/``stream_chat``，锁定引用、工具轮步骤与流式事件序列在
灰度切换前后的结果一致性，避免只验证 gateway WS 而遗漏 REST 分叉。
"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.modules.agent_runtime.contracts import ToolOutcome
from app.core.config import get_settings as get_app_settings
from app.modules.conversation.runtime import build_tool_snapshots, tool_step_values
from app.modules.conversation.services import execute_chat, stream_chat


CITATIONS = [{"title": "退款政策", "source_url": None, "text": "30 天内可申请退款。"}]


class FakeConversation:
    def __init__(self, identifier):
        self.id = identifier
        self.agent_id = 11


class FakeMessage:
    def __init__(self, identifier, content):
        self.id = identifier
        self.content = content


class FakeLoop:
    def __init__(self, identifier, request_id):
        self.id = identifier
        self.request_id = request_id
        self.status = "running"
        self.summary = "正在处理请求"
        self.assistant_message_id = None


class FakeStep:
    """携带 loop step 常用默认字段，替身缺失字段时不会破坏 payload 组装。"""

    def __init__(self, identifier, **values):
        self.id = identifier
        self.sequence = None
        self.step_type = None
        self.title = None
        self.status = None
        self.input_summary = None
        self.output_summary = None
        self.citation_refs = None
        self.skill_name = None
        self.skill_version = None
        self.tool_name = None
        self.tool_call_id = None
        self.error = None
        self.thinking_text = None
        self.step_metadata = None
        for key, value in values.items():
            setattr(self, key, value)


class FakeConversationRepository:
    def __init__(self):
        self.next_conversation_id = 1
        self.next_message_id = 1
        self.next_loop_id = 1
        self.next_step_id = 1
        self.conversation = None
        self.messages = []
        self.steps = []
        self.loops = []

    async def get(self, conversation_id, platform_id, user_id):
        if self.conversation and self.conversation.id == conversation_id:
            return self.conversation
        return None

    async def create(self, platform_id, agent_id, user_id, title):
        self.conversation = FakeConversation(self.next_conversation_id)
        self.next_conversation_id += 1
        return self.conversation

    async def list_recent_context_messages(self, conversation_id, *, since):
        return []

    async def create_message(self, conversation_id, **values):
        message = FakeMessage(self.next_message_id, values["content"])
        self.next_message_id += 1
        self.messages.append(values)
        return message

    async def create_loop(self, conversation_id, **values):
        loop = FakeLoop(self.next_loop_id, values["request_id"])
        self.next_loop_id += 1
        self.loops.append(loop)
        for key, value in values.items():
            setattr(loop, key, value)
        return loop

    async def create_loop_step(self, loop_id, **values):
        step = FakeStep(self.next_step_id, **values)
        self.next_step_id += 1
        self.steps.append(step)
        return step

    async def save_loop(self, loop):
        return loop


def make_context(*, builtin_tools=None):
    """构造最小可运行的 RuntimeContext 替身。"""

    return SimpleNamespace(
        agent=SimpleNamespace(id=11),
        version=SimpleNamespace(
            system_prompt="回答",
            model_name=None,
            version=None,
            temperature=None,
            capabilities={},
            context_window_tokens=None,
        ),
        knowledge_bases=[],
        skill_instructions=[],
        skill_usages=[],
        skill_script_tools=[],
        skill_instruction_tool=None,
        mcp_tools=[],
        builtin_tools=builtin_tools or [],
        host_tools=[],
        conversation_id=None,
    )


class PlainAnswerModel:
    """非流式模型：一次 ainvoke 返回正文与 usage。"""

    async def ainvoke(self, messages):
        assert isinstance(messages[-1], HumanMessage)
        return AIMessage(
            content="退款规则是 30 天内申请。",
            usage_metadata={
                "input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 17,
            },
        )


class ToolThenAnswerModel:
    """非流式模型：第一轮请求工具，第二轮基于工具结果给出正文。"""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "lookup",
                        "args": {"city": "上海"},
                    }
                ],
            )
        assert "晴" in messages[-1].content
        return AIMessage(
            content="上海天气晴，26 度。",
            usage_metadata={
                "input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 17,
            },
        )


class PlainStreamingModel:
    async def astream(self, _messages):
        yield AIMessageChunk(content="退款规则是 30 天内申请。")


class ThinkingStreamingModel:
    async def astream(self, _messages):
        yield AIMessageChunk(
            content="",
            additional_kwargs={"reasoning_content": "先分析引用内容"},
        )
        yield AIMessageChunk(content="退款规则是 30 天内申请。")


class ThinkingAnswerModel:
    async def ainvoke(self, _messages):
        return AIMessage(
            content="退款规则是 30 天内申请。",
            additional_kwargs={"reasoning_content": "先对照引用再回答"},
        )


class StreamingToolThenAnswerModel:
    """REST SSE 场景：第一轮流式请求工具，第二轮输出正文。"""

    def __init__(self):
        self.astream_calls = 0

    async def astream(self, _messages):
        self.astream_calls += 1
        if self.astream_calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "lookup",
                        "args": '{"city": "上海"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
            return
        yield AIMessageChunk(content="上海天气晴，26 ")
        yield AIMessageChunk(content="度。")


class ToolThenConfirmModel:
    """非流式模型：首轮请求工具后工具要求确认，不再继续模型调用。"""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        return AIMessage(
            content="",
            tool_calls=[
                {"id": "call-1", "name": "pay", "args": {"amount": 100}}
            ],
        )


class StreamingToolThenConfirmModel:
    """流式模型：同样只执行一次工具调用，之后进入确认等待。"""

    async def astream(self, _messages):
        yield AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "pay",
                    "args": '{"amount": 100}',
                    "id": "call-1",
                    "index": 0,
                }
            ],
        )


async def invoke_lookup(tool=None, call=None, **kwargs):
    if kwargs:
        return {
            "status": "completed",
            "result": {"weather": "晴", "temperature": 26},
        }
    assert call["name"] == "lookup"
    return {
        "status": "completed",
        "result": {"weather": "晴", "temperature": 26},
    }


def lookup_tool():
    return SimpleNamespace(
        name="lookup",
        kind="builtin",
        description="查天气",
        input_schema={"type": "object"},
    )


def pay_tool():
    return SimpleNamespace(
        name="pay",
        kind="builtin",
        description="发起支付",
        input_schema={"type": "object"},
    )


async def confirm_invoke(tool=None, call=None, **kwargs):
    return {"status": "confirmation_required", "confirmation_id": 42}


def step_signature(steps):
    """提取持久化 loop step 的可比较字段，忽略自增 id 与状态细节。"""

    return [
        (
            step.sequence,
            step.step_type,
            step.title,
            step.status,
            step.tool_name,
            step.tool_call_id,
            step.input_summary,
        )
        for step in steps
    ]


def snapshots_without_time(message_metadata):
    """去掉快照写入时间后比较内容，避免两次运行的时间戳差异干扰。"""

    return [
        {
            key: value
            for key, value in entry.items()
            if key != "queried_at"
        }
        for entry in (message_metadata or {}).get("tool_snapshots", [])
    ]


def test_execute_chat_gray_plain_answer_matches_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        conversation, assistant, result = await execute_chat(
            repo,
            make_context(),
            platform_id=3,
            user_id=5,
            message="退款规则？",
            conversation_id=None,
            model=PlainAnswerModel(),
            citations=CITATIONS,
            use_agent_runtime=gray,
        )
        return conversation, assistant, result, repo

    legacy = asyncio.run(run(False))
    gray = asyncio.run(run(True))

    for _, assistant, result, repo in (legacy, gray):
        assert assistant.content == "退款规则是 30 天内申请。"
        assert result.content == "退款规则是 30 天内申请。"
        assert result.knowledge_grounded is True
        assert len(result.citations) == 1
        assert result.usage == {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        }
        assert repo.messages[-1]["knowledge_grounded"] is True

    assert step_signature(legacy[3].steps) == step_signature(gray[3].steps)
    assert legacy[3].messages[-1]["content_blocks"] == gray[3].messages[-1][
        "content_blocks"
    ]


def test_execute_chat_gray_tool_round_persists_same_steps_as_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        _, _, result = await execute_chat(
            repo,
            make_context(builtin_tools=[lookup_tool()]),
            platform_id=3,
            user_id=5,
            message="上海天气？",
            conversation_id=None,
            model=ToolThenAnswerModel(),
            citations=CITATIONS,
            invoke_tool_fn=invoke_lookup,
            use_agent_runtime=gray,
        )
        return result, repo

    legacy_result, legacy_repo = asyncio.run(run(False))
    gray_result, gray_repo = asyncio.run(run(True))

    assert gray_result.content == legacy_result.content == "上海天气晴，26 度。"
    assert gray_result.knowledge_grounded is legacy_result.knowledge_grounded is True
    assert gray_result.usage == legacy_result.usage
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)

    # 工具步骤必须是 builtin_tool 而不是默认 host_tool，input_summary 也要
    # 与 legacy 一致，否则消息快照与 SSE step payload 会在灰度开关下分叉。
    gray_tool_steps = [
        step for step in gray_repo.steps if step.tool_name == "lookup"
    ]
    assert gray_tool_steps
    assert gray_tool_steps[0].step_type == "builtin_tool"
    assert gray_tool_steps[0].input_summary == '{"city":"上海"}'


def test_stream_chat_gray_event_sequence_and_result_match_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        events = []
        async for event in stream_chat(
            repo,
            make_context(),
            platform_id=3,
            user_id=5,
            message="退款规则？",
            conversation_id=None,
            model=PlainStreamingModel(),
            citations=CITATIONS,
            use_agent_runtime=gray,
        ):
            events.append(event)
        return events, repo

    legacy_events, legacy_repo = asyncio.run(run(False))
    gray_events, gray_repo = asyncio.run(run(True))

    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert [
        event.get("content") for event in gray_events if event["type"] == "message_delta"
    ] == [
        event.get("content")
        for event in legacy_events
        if event["type"] == "message_delta"
    ]

    def completed_result(events):
        return next(event["result"] for event in events if event["type"] == "completed")

    legacy_result = completed_result(legacy_events)
    gray_result = completed_result(gray_events)
    assert gray_result.content == legacy_result.content == "退款规则是 30 天内申请。"
    assert gray_result.knowledge_grounded is legacy_result.knowledge_grounded is True
    assert gray_result.usage == legacy_result.usage
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)


def test_execute_chat_gray_thinking_text_matches_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        _, _, result = await execute_chat(
            repo,
            make_context(),
            platform_id=3,
            user_id=5,
            message="退款规则？",
            conversation_id=None,
            model=ThinkingAnswerModel(),
            citations=CITATIONS,
            use_agent_runtime=gray,
        )
        generation_step = next(
            step for step in repo.steps if step.step_type == "model_generation"
        )
        return result, generation_step

    legacy_result, legacy_step = asyncio.run(run(False))
    gray_result, gray_step = asyncio.run(run(True))

    assert gray_result.thinking_text == "先对照引用再回答"
    assert legacy_result.thinking_text == gray_result.thinking_text
    assert gray_step.thinking_text == legacy_step.thinking_text


def test_stream_chat_gray_thinking_deltas_and_result_match_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        events = []
        async for event in stream_chat(
            repo,
            make_context(),
            platform_id=3,
            user_id=5,
            message="退款规则？",
            conversation_id=None,
            model=ThinkingStreamingModel(),
            citations=CITATIONS,
            use_agent_runtime=gray,
        ):
            events.append(event)
        return events, repo

    legacy_events, legacy_repo = asyncio.run(run(False))
    gray_events, gray_repo = asyncio.run(run(True))

    def thinking_deltas(events):
        return [
            event["payload"]["content"]
            for event in events
            if event["type"] == "agent_step_delta"
        ]

    assert thinking_deltas(gray_events) == ["先分析引用内容"]
    assert thinking_deltas(gray_events) == thinking_deltas(legacy_events)
    assert [
        event["type"] for event in gray_events
    ] == [event["type"] for event in legacy_events]

    def completed_result(events):
        return next(event["result"] for event in events if event["type"] == "completed")

    assert (
        completed_result(gray_events).thinking_text
        == completed_result(legacy_events).thinking_text
        == "先分析引用内容"
    )
    gray_step = next(
        step for step in gray_repo.steps if step.step_type == "model_generation"
    )
    legacy_step = next(
        step for step in legacy_repo.steps if step.step_type == "model_generation"
    )
    assert gray_step.thinking_text == legacy_step.thinking_text == "先分析引用内容"


def test_runtime_tool_event_arguments_feed_step_and_snapshot_params():
    """runtime 工具事件没有 input_summary 时按结构化参数生成等价摘要。"""

    outcome = ToolOutcome(
        status="completed", result={"weather": "晴"}, call_id="call-1"
    )
    event = {
        "tool_call_id": "call-1",
        "tool": "lookup",
        "arguments": {"city": "上海"},
        "tool_type": "builtin_tool",
        "outcome": outcome,
    }

    step_values = tool_step_values(event, sequence=3)
    snapshots = build_tool_snapshots(
        [event], max_chars=500, total_chars=1000, max_entries=5
    )

    assert step_values["step_type"] == "builtin_tool"
    assert step_values["input_summary"] == '{"city":"上海"}'
    assert snapshots[0]["params"] == '{"city":"上海"}'


def test_stream_chat_gray_tool_round_events_and_steps_match_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        events = []
        async for event in stream_chat(
            repo,
            make_context(builtin_tools=[lookup_tool()]),
            platform_id=3,
            user_id=5,
            message="上海天气？",
            conversation_id=None,
            model=StreamingToolThenAnswerModel(),
            citations=CITATIONS,
            invoke_tool_fn=invoke_lookup,
            use_agent_runtime=gray,
        ):
            events.append(event)
        return events, repo

    legacy_events, legacy_repo = asyncio.run(run(False))
    gray_events, gray_repo = asyncio.run(run(True))

    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert [
        event["payload"]
        for event in gray_events
        if event["type"] == "tool_call"
    ] == [
        event["payload"]
        for event in legacy_events
        if event["type"] == "tool_call"
    ]
    assert [
        event["payload"]["status"]
        for event in gray_events
        if event["type"] == "tool_result"
    ] == ["completed"]

    def completed_result(events):
        return next(event["result"] for event in events if event["type"] == "completed")

    assert completed_result(gray_events).content == "上海天气晴，26 度。"
    assert completed_result(gray_events).content == completed_result(
        legacy_events
    ).content
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)
    assert snapshots_without_time(
        gray_repo.messages[-1]["message_metadata"]
    ) == snapshots_without_time(legacy_repo.messages[-1]["message_metadata"])


def test_execute_chat_gray_confirmation_waiting_matches_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        _, _, result = await execute_chat(
            repo,
            make_context(builtin_tools=[pay_tool()]),
            platform_id=3,
            user_id=5,
            message="支付 100 元",
            conversation_id=None,
            model=ToolThenConfirmModel(),
            citations=CITATIONS,
            invoke_tool_fn=confirm_invoke,
            use_agent_runtime=gray,
        )
        return result, repo

    legacy_result, legacy_repo = asyncio.run(run(False))
    gray_result, gray_repo = asyncio.run(run(True))

    assert gray_result.pending_confirmation_id == 42
    assert legacy_result.pending_confirmation_id == gray_result.pending_confirmation_id
    assert gray_repo.loops[-1].status == "waiting_confirmation"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)


def test_stream_chat_gray_confirmation_waiting_terminates_like_legacy():
    async def run(gray):
        repo = FakeConversationRepository()
        events = []
        async for event in stream_chat(
            repo,
            make_context(builtin_tools=[pay_tool()]),
            platform_id=3,
            user_id=5,
            message="支付 100 元",
            conversation_id=None,
            model=StreamingToolThenConfirmModel(),
            citations=CITATIONS,
            invoke_tool_fn=confirm_invoke,
            use_agent_runtime=gray,
        ):
            events.append(event)
        return events, repo

    legacy_events, legacy_repo = asyncio.run(run(False))
    gray_events, gray_repo = asyncio.run(run(True))

    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert gray_events[-1]["type"] == "completed"
    assert gray_events[-1]["result"].pending_confirmation_id == 42
    assert gray_repo.loops[-1].status == "waiting_confirmation"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)


class FailingStreamingModel:
    """REST SSE 场景：模型在发布任何事件前失败。"""

    async def astream(self, _messages):
        raise RuntimeError("HTTP 502 Bad Gateway")
        yield  # pragma: no cover


class FailingNonStreamingModel:
    """REST 非流式场景：模型首次调用即失败。"""

    async def ainvoke(self, _messages):
        raise RuntimeError("HTTP 502 Bad Gateway")


def test_stream_chat_gray_model_error_terminates_like_legacy():
    """模型级错误在灰度流中必须以 error 事件终结，而不是向协议层抛异常。

    legacy ``stream_graph`` 会把异常转成终止 error 事件，服务层据此把 loop
    与生成步骤落为 failed；AgentRuntime 修复后同样以 error 事件结束事件流，
    保证灰度开启时 SSE 客户端与 loop 状态不会出现分叉。
    """

    async def run(gray):
        repo = FakeConversationRepository()
        events = []
        async for event in stream_chat(
            repo,
            make_context(),
            platform_id=3,
            user_id=5,
            message="退款规则？",
            conversation_id=None,
            model=FailingStreamingModel(),
            citations=CITATIONS,
            use_agent_runtime=gray,
        ):
            events.append(event)
        return events, repo

    legacy_events, legacy_repo = asyncio.run(run(False))
    gray_events, gray_repo = asyncio.run(run(True))

    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert gray_events[-1]["type"] == "error"
    legacy_error = legacy_events[-1]["payload"]
    gray_error = gray_events[-1]["payload"]
    # details 允许不同：灰度刻意不把供应商原始文本放进错误详情，但公开的
    # code/message/retryable 语义必须与 legacy 一致。
    assert gray_error["code"] == legacy_error["code"] == "agent_upstream_unavailable"
    assert gray_error["message"] == legacy_error["message"]
    assert gray_error["retryable"] is legacy_error["retryable"] is True
    assert gray_repo.loops[-1].status == "failed"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status
    generation_step = next(
        step for step in gray_repo.steps if step.step_type == "model_generation"
    )
    assert generation_step.status == "failed"
    assert generation_step.error is not None


def test_execute_chat_gray_model_error_propagates_like_legacy():
    """REST 非流式模型错误：灰度与 legacy 都向调用方抛出同一异常。

    模型失败时两条路径必须同时：向调用方抛出原异常（REST 公开错误响应
    不变）、补写 failed 的 model_generation 步骤并把 loop 更新为 failed，
    避免非流式请求在错误后留下“处理中”的 loop 假象（与流式 error 收尾
    同一语义）。
    """

    async def run(gray):
        repo = FakeConversationRepository()
        try:
            await execute_chat(
                repo,
                make_context(),
                platform_id=3,
                user_id=5,
                message="退款规则？",
                conversation_id=None,
                model=FailingNonStreamingModel(),
                citations=CITATIONS,
                use_agent_runtime=gray,
            )
        except RuntimeError as error:
            return str(error), repo
        raise AssertionError("expected model error")

    legacy_message, legacy_repo = asyncio.run(run(False))
    gray_message, gray_repo = asyncio.run(run(True))

    assert gray_message == legacy_message == "HTTP 502 Bad Gateway"
    assert gray_repo.loops[-1].status == "failed"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status
    assert step_signature(gray_repo.steps) == step_signature(legacy_repo.steps)
    gray_generation_step = next(
        step for step in gray_repo.steps if step.step_type == "model_generation"
    )
    legacy_generation_step = next(
        step for step in legacy_repo.steps if step.step_type == "model_generation"
    )
    assert gray_generation_step.status == "failed"
    assert gray_generation_step.error == legacy_generation_step.error
    assert gray_generation_step.error["code"] == "agent_upstream_unavailable"


class MaxTurnsToolThenAnswerModel:
    """达到 max_turns 场景：前几轮返回工具调用，收尾提示到达后直接回答。"""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        first = messages[0]
        if "最大执行轮数" in getattr(first, "content", ""):
            # runtime 与 legacy 的收尾提示都会把“停止调用工具、基于已有信息
            # 回答”放为首条系统消息；模型据此给出最终回答，不再请求工具。
            return AIMessage(
                content="已到执行上限，我基于已有信息直接回答：无法继续查询。",
                usage_metadata={
                    "input_tokens": 30,
                    "output_tokens": 8,
                    "total_tokens": 38,
                },
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"call-{self.calls}",
                    "name": "lookup",
                    "args": {"city": "上海"},
                }
            ],
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            },
        )


def test_execute_chat_gray_max_turns_wrapup_matches_legacy(monkeypatch):
    """REST 非流式达到最大轮数时，灰度与 legacy 的收尾回答与落库一致。

    legacy run_graph 与 AgentLoop 都按 settings 的 agent_max_iterations 触发
    收尾：前两轮执行工具，第三轮收到“停止调用工具”提示后给出最终回答。
    这里锁定两路结果文本、usage、工具事件数与 loop step 一致。
    """

    # get_settings 是 lru_cache 单例，灰度 helper 与 legacy run_graph 都读取
    # 同一实例；Settings 为 frozen dataclass，只能经 object.__setattr__ 覆盖
    # max_turns，其余字段保持真实配置，避免替身缺字段，finally 中恢复原值。
    settings = get_app_settings()
    original_max_turns = settings.agent_max_iterations
    object.__setattr__(settings, "agent_max_iterations", 2)

    async def run(gray):
        repo = FakeConversationRepository()
        model = MaxTurnsToolThenAnswerModel()
        _, _, result = await execute_chat(
            repo,
            make_context(builtin_tools=[lookup_tool()]),
            platform_id=3,
            user_id=5,
            message="上海天气？",
            conversation_id=None,
            model=model,
            citations=CITATIONS,
            invoke_tool_fn=invoke_lookup,
            use_agent_runtime=gray,
        )
        return model, result, repo

    try:
        legacy_model, legacy_result, legacy_repo = asyncio.run(run(False))
        gray_model, gray_result, gray_repo = asyncio.run(run(True))
    finally:
        object.__setattr__(settings, "agent_max_iterations", original_max_turns)

    assert gray_result.content == legacy_result.content
    assert "已到执行上限" in gray_result.content
    assert gray_result.usage == legacy_result.usage
    # 已按 Pi/legacy 对齐（2026-09-07 用户确认）：达到上限的那次模型请求
    # 工具时，该轮新工具不再执行。两路都只成功执行第 1 轮工具；灰度额外把
    # 上限轮调用记录为 failed（max_turns_reached）并回填模型，legacy 不记录
    # 该轮调用，因此工具事件数相差一条 failed。
    gray_statuses = [
        str(event["outcome"].status)
        for event in (gray_result.tool_events or [])
    ]
    assert gray_statuses == ["completed", "failed"]
    assert (
        gray_result.tool_events[-1]["outcome"].error["code"]
        == "max_turns_reached"
    )
    assert len(legacy_result.tool_events or []) == 1
    assert str(legacy_result.tool_events[0]["outcome"].status) == "completed"
    # 成功执行（completed）的工具轮数两路一致为 1；模型调用总数同为 3：
    # 第 1 轮执行工具、第 2 轮达到上限拒绝执行、第 3 轮收尾直接回答。
    assert gray_model.calls == 3
    assert legacy_model.calls == 3
    assert gray_repo.loops[-1].status == "completed"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status


class MaxTurnsStreamingModel:
    """REST SSE max_turns 场景：前两轮流式请求工具，收尾提示后输出正文。"""

    def __init__(self):
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        first = messages[0]
        if "最大执行轮数" in getattr(first, "content", ""):
            yield AIMessageChunk(content="已到执行上限，")
            yield AIMessageChunk(content="基于已有信息回答。")
            return
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "lookup",
                        "args": '{"city": "上海"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
            return
        yield AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "lookup",
                    "args": '{"city": "上海"}',
                    "id": "call-2",
                    "index": 0,
                }
            ],
        )


def test_stream_chat_gray_max_turns_wrapup_terminates_like_legacy():
    """REST SSE 达到 max_turns 时，灰度与 legacy 都以收尾完成事件结束。

    legacy 与 AgentLoop（已按 Pi 对齐）都不会执行达到上限那轮的新工具；
    灰度会多发布该轮的 failed 工具事件（记录口径差异），但两路都必须正常
    产出收尾回答、完成事件与 loop 终态，不能卡死或中断 SSE。
    """

    async def run(gray):
        settings = get_app_settings()
        original_max_turns = settings.agent_max_iterations
        object.__setattr__(settings, "agent_max_iterations", 2)
        repo = FakeConversationRepository()
        model = MaxTurnsStreamingModel()
        events = []
        try:
            async for event in stream_chat(
                repo,
                make_context(builtin_tools=[lookup_tool()]),
                platform_id=3,
                user_id=5,
                message="上海天气？",
                conversation_id=None,
                model=model,
                citations=CITATIONS,
                invoke_tool_fn=invoke_lookup,
                use_agent_runtime=gray,
            ):
                events.append(event)
        finally:
            object.__setattr__(
                settings, "agent_max_iterations", original_max_turns
            )
        return model, events, repo

    legacy_model, legacy_events, legacy_repo = asyncio.run(run(False))
    gray_model, gray_events, gray_repo = asyncio.run(run(True))

    legacy_types = [event["type"] for event in legacy_events]
    gray_types = [event["type"] for event in gray_events]
    assert legacy_types[-1] == "completed"
    assert gray_types[-1] == "completed"
    assert "agent_loop_completed" in gray_types
    assert gray_repo.loops[-1].status == "completed"
    assert legacy_repo.loops[-1].status == gray_repo.loops[-1].status

    # 两路模型调用次数相同（第 1 轮执行、第 2 轮达上限、第 3 轮收尾）。
    assert gray_model.calls == 3
    assert legacy_model.calls == 3
    # 收尾正文都完整到达 SSE；completed 结果内容一致。
    def completed_text(events):
        return next(
            event["result"].content
            for event in events
            if event["type"] == "completed"
        )

    assert gray_types.count("message_delta") == legacy_types.count(
        "message_delta"
    )
    assert "已到执行上限" in completed_text(gray_events)
    assert completed_text(gray_events) == completed_text(legacy_events)

    # 灰度把上限轮（call-2）记录为 failed(max_turns_reached)；legacy 不记录。
    gray_failed = [
        event
        for event in gray_events
        if event["type"] == "tool_result"
        and event["payload"].get("status") == "failed"
    ]
    assert len(gray_failed) == 1
    # tool_result 的服务层 payload 是 outcome.model_dump() 后的 dict，
    # 失败原因位于 payload["error"]["code"]（键名保留 dataclass 字段名 error）。
    assert gray_failed[0]["payload"]["error"]["code"] == "max_turns_reached"
    assert not any(
        event["type"] == "tool_result"
        and event["payload"].get("status") == "failed"
        for event in legacy_events
    )
