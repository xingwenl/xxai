import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk

from app.core.config import get_settings
from app.modules.gateway.runtime import (
    filter_conflicting_runtime_tools,
    merge_model_tools,
    stream_embed_chat,
)
from app.modules.gateway.runtime import _finish_embed_chat
from app.modules.agent_runtime.events import LoopEventBuilder, to_wire


def wire(event, sequence: int = 1) -> dict:
    """把运行时事件转成线协议信封。

    网关内部现在统一产出 ``RunEvent``；断言针对客户端真正收到的形状，
    因此这里统一走 ``to_wire``，也顺带覆盖信封字段。
    """

    return to_wire(event, sequence=sequence)


class FakeConversation:
    def __init__(self, identifier=101):
        self.id = identifier
        self.agent_id = 11


class FakeMessage:
    def __init__(self, identifier, content):
        self.id = identifier
        self.content = content


class FakeLoop:
    def __init__(self, identifier=1):
        self.id = identifier
        self.status = "running"
        self.summary = "正在处理请求"
        self.assistant_message_id = None


class FakeConversationRepository:
    def __init__(self):
        self.conversation = None
        self.messages = []
        self.history = []
        self.usage_records = []
        self.next_message_id = 1
        self.loop = None
        self.next_step_id = 1

    async def get_for_principal(self, conversation_id, platform_id, *, end_user_id):
        if self.conversation and self.conversation.id == conversation_id:
            return self.conversation
        return None

    async def create_for_principal(self, platform_id, agent_id, *, end_user_id, title):
        self.conversation = FakeConversation()
        return self.conversation

    async def create_message(self, conversation_id, **values):
        message = FakeMessage(self.next_message_id, values["content"])
        self.next_message_id += 1
        self.messages.append(values)
        return message

    async def list_recent_context_messages(self, conversation_id, *, since):
        assert conversation_id == self.conversation.id
        assert since.tzinfo is not None
        return self.history

    async def record_model_usage(self, **values):
        self.usage_records.append(values)

    async def create_loop(self, _conversation_id, **values):
        self.loop = FakeLoop()
        for key, value in values.items():
            setattr(self.loop, key, value)
        return self.loop

    async def create_loop_step(self, _loop_run_id, **values):
        # 补齐真实 ORM 对象的列默认字段，避免事件构造（output_summary、
        # error 等）在未显式传入时触发 AttributeError；与 REST 替身对齐。
        step = SimpleNamespace(
            id=self.next_step_id,
            sequence=None,
            step_type=None,
            title=None,
            status=None,
            input_summary=None,
            output_summary=None,
            citation_refs=None,
            skill_name=None,
            skill_version=None,
            tool_name=None,
            tool_call_id=None,
            error=None,
            thinking_text=None,
            step_metadata=None,
        )
        for key, value in values.items():
            setattr(step, key, value)
        self.next_step_id += 1
        return step

    async def save_loop(self, loop):
        self.loop = loop
        return loop


class FakeStreamingModel:
    async def astream(self, _messages):
        for content in ("你好", "，这里是回答"):
            yield SimpleNamespace(content=content)


class GrayStreamingModel:
    """AgentRuntime 灰度路径使用的可累积 LangChain chunk 替身。"""

    async def astream(self, _messages):
        yield AIMessageChunk(content="你好")
        yield AIMessageChunk(content="，这里是回答")


class FakeUsageStreamingModel:
    """流式模型：携带 usage_metadata 的 AIMessageChunk（真实供应商形状）。

    运行时通过模型响应累积 usage；用 AIMessageChunk 而不是 SimpleNamespace，
    与 AgentLoop 的 LangChain 适配器（模型调用即 AIMessage/AIMessageChunk）
    保持一致，确保 message_completed 能透出 token 用量并落独立用量表。
    """

    # 用量记录里的模型名快照取自真实客户端，这里显式给出以断言落库内容。
    model_name = "deepseek-v4-pro"

    async def astream(self, _messages):
        yield AIMessageChunk(
            content="你好",
            usage_metadata={
                "input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 17,
            },
        )


class FailingStreamingModel:
    async def astream(self, _messages):
        raise RuntimeError("HTTP 502 Bad Gateway")
        yield  # pragma: no cover


class RecordingBindModel:
    """记录 bind_tools 收到的工具 Schema，用于验证模型可见的工具集合。"""

    def __init__(self):
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def astream(self, _messages):
        yield SimpleNamespace(content="已收到")


def test_runtime_tool_name_conflicts_exclude_all_duplicates():
    tools = [
        SimpleNamespace(name="same", kind="builtin"),
        SimpleNamespace(name="same", server_id=4),
        SimpleNamespace(name="read_only", server_id=4),
    ]

    filtered = filter_conflicting_runtime_tools(tools)

    assert [tool.name for tool in filtered] == ["read_only"]


def test_merge_model_tools_keeps_runtime_and_host_tools():
    """入口工具与宿主工具必须同时保留，同名工具统一剔除。"""

    runtime_tools = [
        SimpleNamespace(name="http_get", kind="builtin"),
        SimpleNamespace(name="share_name", kind="builtin"),
    ]
    host_tools = [
        SimpleNamespace(name="debug_ping"),
        SimpleNamespace(name="share_name"),
    ]

    merged = merge_model_tools(runtime_tools, host_tools)

    assert [tool.name for tool in merged] == ["http_get", "debug_ping"]


def test_embed_chat_binds_host_tools_to_model():
    """注册的页面宿主工具必须进入 bind_tools。

    回归用例：此前 ``runtime_tools`` 与 ``host_tools`` 被写成二选一，宿主工具
    只出现在 system prompt 里，模型无法产生 tool_call，表现为"页面注册成功但
    工具永远不被调用"。
    """

    model = RecordingBindModel()
    host_tool = SimpleNamespace(
        name="debug_ping",
        description="调试用页面方法",
        input_schema={"type": "object", "properties": {}},
    )
    runtime_tool = SimpleNamespace(
        name="http_get",
        description="请求网页",
        input_schema={"type": "object"},
        kind="builtin",
    )

    async def run():
        events = []
        async for event in stream_embed_chat(
            FakeConversationRepository(),
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=model,
            platform_id=1,
            end_user_id=2,
            message="调用 debug_ping",
            conversation_id=None,
            request_id="req-host-bind",
            citations=[],
            host_tools=[host_tool],
            runtime_tools=[runtime_tool],
        ):
            events.append(wire(event, len(events) + 1))
        return events

    events = asyncio.run(run())

    assert [item["function"]["name"] for item in model.bound_tools] == [
        "http_get",
        "debug_ping",
    ]
    assert any(event["type"] == "message_completed" for event in events)


class HostToolCallStreamingModel:
    """第一轮请求宿主工具，第二轮基于工具结果作答。"""

    def __init__(self):
        self.calls = 0

    async def astream(self, _messages):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "debug_ping",
                        "args": "{}",
                        "id": "call-host-1",
                        "index": 0,
                    }
                ],
            )
            return
        yield AIMessageChunk(content="页面标题是 repro-page。")


def test_embed_chat_dispatches_registered_host_tool_call():
    """注册的宿主工具必须能被模型调用，并把页面结果回填给模型。

    覆盖"注册 -> 绑定 -> 模型 tool_call -> 页面结果回传 -> 继续作答"整条链路，
    防止再次出现只注册、不绑定导致工具永不被调用的回归。
    """

    invoked: list[tuple[str, dict]] = []

    async def invoke_host_tool(tool=None, call=None, **_kwargs):
        invoked.append((tool.name, dict(call or {})))
        return {"status": "completed", "result": {"title": "repro-page"}}

    host_tool = SimpleNamespace(
        name="debug_ping",
        description="调试用页面方法",
        input_schema={"type": "object", "properties": {}},
    )

    async def run():
        model = HostToolCallStreamingModel()
        events = []
        async for event in stream_embed_chat(
            FakeConversationRepository(),
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=model,
            platform_id=1,
            end_user_id=2,
            message="调用 debug_ping",
            conversation_id=None,
            request_id="req-host-call",
            citations=[],
            host_tools=[host_tool],
            runtime_tools=[lookup_runtime_tool()],
            invoke_host_tool_fn=invoke_host_tool,
        ):
            events.append(wire(event, len(events) + 1))
        return model, events

    model, events = asyncio.run(run())

    assert [name for name, _ in invoked] == ["debug_ping"]
    assert model.calls == 2

    host_steps = [
        event
        for event in events
        if event["type"] == "agent_step_completed"
        and event["payload"].get("toolName") == "debug_ping"
    ]
    assert [step["payload"]["status"] for step in host_steps] == ["succeeded"]
    assert host_steps[0]["payload"]["stepType"] == "host_tool"

    final_text = next(
        event["payload"]["content"]
        for event in events
        if event["type"] == "message_completed"
    )
    assert "repro-page" in final_text


def test_embed_stream_sends_terminal_error_and_marks_loop_failed():
    async def collect():
        repo = FakeConversationRepository()
        events = []
        async for event in stream_embed_chat(
            repo,
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(id=3, system_prompt="回答"),
                skill_usages=[],
                skill_instructions=[],
                knowledge_bases=[],
            ),
            model=FailingStreamingModel(),
            platform_id=1,
            end_user_id=2,
            message="测试",
            conversation_id=None,
            request_id="req-502",
            citations=[],
        ):
            events.append(wire(event, len(events) + 1))
        return repo, events

    repo, events = asyncio.run(collect())

    assert events[-1]["type"] == "error"
    assert events[-1]["payload"]["message"] == "Agent 连接失败（HTTP 502），本轮对话已结束"
    assert repo.loop.status == "failed"
    assert not any(event["type"] == "message_completed" for event in events)


def test_embed_stream_runtime_gray_sends_terminal_error_and_marks_loop_failed(
    monkeypatch,
):
    """灰度开关开启时，模型级错误也必须以 WS error 事件终结并落库 failed。

    AgentRuntime 把未表达为事件的模型错误转成终止 error 事件后，gateway 的
    错误收尾分支与 legacy 一致；否则异常会直接穿过事件流，导致 loop 卡在
    running 且前端收不到稳定终态。
    """

    monkeypatch.setattr(
        "app.modules.gateway.runtime.get_settings",
        lambda: SimpleNamespace(
            agent_runtime_enabled=True,
            agent_max_iterations=20,
        ),
    )

    async def run():
        repo = FakeConversationRepository()
        events = []
        async for event in stream_embed_chat(
            repo,
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=FailingStreamingModel(),
            platform_id=1,
            end_user_id=2,
            message="测试",
            conversation_id=None,
            request_id="req-502-gray",
            citations=[],
        ):
            events.append(wire(event, len(events) + 1))
        return repo, events

    repo, events = asyncio.run(run())

    assert events[-1]["type"] == "error"
    assert events[-1]["payload"]["code"] == "agent_upstream_unavailable"
    assert (
        events[-1]["payload"]["message"]
        == "Agent 连接失败（HTTP 502），本轮对话已结束"
    )
    assert repo.loop.status == "failed"
    assert not any(event["type"] == "message_completed" for event in events)


def test_embed_chat_emits_started_deltas_citation_and_completed():
    async def run():
        events = []
        async for event in stream_embed_chat(
            FakeConversationRepository(),
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=FakeStreamingModel(),
            platform_id=7,
            end_user_id=22,
            message="你好",
            conversation_id=None,
            request_id="req-1",
            citations=[{"title": "FAQ", "text": "说明"}],
        ):
            events.append(wire(event, len(events) + 1)["type"])

        assert events[:4] == [
            "message_started",
            "agent_loop_started",
            "agent_step_completed",
            "agent_step_started",
        ]
        assert events[4:] == [
            "message_delta",
            "message_delta",
            "citation",
            "agent_step_completed",
            "agent_loop_completed",
            "message_completed",
        ]

    asyncio.run(run())


def test_embed_chat_runtime_gray_keeps_legacy_event_shape(monkeypatch):
    """灰度开关开启时，WS 事件流与 legacy 流程保持同一协议形状。"""

    monkeypatch.setattr(
        "app.modules.gateway.runtime.get_settings",
        lambda: SimpleNamespace(
            agent_runtime_enabled=True,
            agent_max_iterations=20,
        ),
    )

    async def run():
        events = []
        async for event in stream_embed_chat(
            FakeConversationRepository(),
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=GrayStreamingModel(),
            platform_id=7,
            end_user_id=22,
            message="你好",
            conversation_id=None,
            request_id="req-gray",
            citations=[{"title": "FAQ", "text": "说明"}],
        ):
            events.append(wire(event, len(events) + 1)["type"])

        assert events[:4] == [
            "message_started",
            "agent_loop_started",
            "agent_step_completed",
            "agent_step_started",
        ]
        assert events[4:] == [
            "message_delta",
            "message_delta",
            "citation",
            "agent_step_completed",
            "agent_loop_completed",
            "message_completed",
        ]

    asyncio.run(run())


def test_embed_chat_records_model_usage_in_independent_detail_table():
    async def run():
        repo = FakeConversationRepository()
        events = []
        async for event in stream_embed_chat(
            repo,
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(
                    id=3,
                    system_prompt="回答",
                ),
                skill_instructions=[],
                mcp_tools=[],
            ),
            model=FakeUsageStreamingModel(),
            platform_id=7,
            client_id="client_live",
            end_user_id=22,
            message="你好",
            conversation_id=None,
            request_id="req-usage",
            citations=[],
        ):
            events.append(wire(event, len(events) + 1))

        completed = events[-1]
        assert completed["type"] == "message_completed"
        assert completed["payload"]["usage"] == {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        }
        assert repo.usage_records == [
            {
                "platform_id": 7,
                "agent_id": 11,
                "agent_version_id": 3,
                "client_id": "client_live",
                "platform_end_user_id": 22,
                "conversation_id": 101,
                "message_id": 2,
                "request_id": "req-usage",
                "model_name": "deepseek-v4-pro",
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            }
        ]

    asyncio.run(run())


def test_embed_chat_emits_loaded_skill_steps_before_generation():
    async def run():
        events = []
        async for event in stream_embed_chat(
            FakeConversationRepository(),
            SimpleNamespace(
                agent=SimpleNamespace(id=11),
                version=SimpleNamespace(system_prompt="回答"),
                skill_instructions=["生成报告"],
                skill_usages=[{"name": "报告技能", "version": "1.2.0", "has_script_tool": True}],
                mcp_tools=[],
            ),
            model=FakeStreamingModel(),
            platform_id=7,
            end_user_id=22,
            message="生成报告",
            conversation_id=None,
            request_id="req-skill",
            citations=[],
        ):
            if str(event.type).startswith("agent_step"):
                events.append(wire(event, len(events) + 1))

        skill_event = next(event for event in events if event["payload"]["stepType"] == "skill_instruction")
        generation_event = next(event for event in events if event["payload"]["stepType"] == "model_generation")
        assert skill_event["payload"]["skillName"] == "报告技能"
        assert skill_event["payload"]["skillVersion"] == "1.2.0"
        assert skill_event["payload"]["sequence"] == 2
        assert generation_event["payload"]["sequence"] == 3

    asyncio.run(run())


def test_cancelled_embed_chat_does_not_write_assistant_completion():
    async def run():
        repo = FakeConversationRepository()

        async def consume():
            async for _event in stream_embed_chat(
                repo,
                SimpleNamespace(
                    agent=SimpleNamespace(id=11),
                    version=SimpleNamespace(system_prompt="回答"),
                    skill_instructions=[],
                    mcp_tools=[],
                ),
                model=FakeStreamingModel(),
                platform_id=7,
                end_user_id=22,
                message="你好",
                conversation_id=None,
                request_id="req-2",
                citations=[],
            ):
                raise asyncio.CancelledError

        try:
            await consume()
        except asyncio.CancelledError:
            pass

        assert [item["role"] for item in repo.messages] == ["user"]

    asyncio.run(run())


def test_cancelled_embed_chat_gray_does_not_write_assistant_completion(
    monkeypatch,
):
    """灰度开关开启时取消同样不写助手消息，与 legacy 行为一致。

    连接层取消模型 Task 时，CancelledError 会直接穿过 stream_embed_chat；
    AgentRuntime 只保证不把取消伪装成失败/完成事件，网关收尾逻辑不得把
    已保存的 running loop 改成 completed/failed，也不得写助手消息。
    """

    monkeypatch.setattr(
        "app.modules.gateway.runtime.get_settings",
        lambda: SimpleNamespace(
            agent_runtime_enabled=True,
            agent_max_iterations=20,
        ),
    )

    async def run():
        repo = FakeConversationRepository()

        async def consume():
            async for _event in stream_embed_chat(
                repo,
                SimpleNamespace(
                    agent=SimpleNamespace(id=11),
                    version=SimpleNamespace(system_prompt="回答"),
                    skill_instructions=[],
                    mcp_tools=[],
                ),
                model=GrayStreamingModel(),
                platform_id=7,
                end_user_id=22,
                message="你好",
                conversation_id=None,
                request_id="req-2-gray-cancel",
                citations=[],
            ):
                # 等模型流式正文真正开始后再取消，确保取消点穿过灰度
                # AgentRuntime 引擎路径，而不是只停在事件序列前端。
                if _event.type == "message_delta":
                    raise asyncio.CancelledError

        try:
            await consume()
        except asyncio.CancelledError:
            pass

        # 取消发生在模型流式输出中途：用户消息已落库、loop 已创建并保持
        # running，但不出现助手完成消息、不把取消伪装成失败/完成终态。
        assert [item["role"] for item in repo.messages] == ["user"]
        assert repo.loop.status == "running"

    asyncio.run(run())


def test_failed_tool_outcome_does_not_mark_agent_loop_failed():
    """工具失败只影响工具 step，不能把整个 Agent 请求错误升级为 failed。"""
    async def run():
        repo = FakeConversationRepository()
        conversation = SimpleNamespace(id=101)
        loop = SimpleNamespace(
            id=1,
            status="running",
            summary="正在处理请求",
            assistant_message_id=None,
        )
        generation_step = SimpleNamespace(
            id=2,
            sequence=2,
            step_type="model_generation",
            title="生成回答",
            status="running",
            output_summary="",
            thinking_text="",
            error=None,
        )
        result = SimpleNamespace(
            content="最终回答",
            citations=[],
            knowledge_grounded=False,
            content_blocks=[],
            tool_events=[
                {
                    "tool_call_id": "call-1",
                    "tool": "get_weather",
                    "tool_type": "mcp_tool",
                    "outcome": SimpleNamespace(
                        status="failed",
                        result=None,
                        error={"code": "tool_error"},
                    ),
                }
            ],
            usage=None,
            thinking_text="",
            pending_confirmation_id=None,
        )
        events = []
        async for event in _finish_embed_chat(
            repo,
            SimpleNamespace(agent=SimpleNamespace(id=11)),
            conversation=conversation,
            loop=loop,
            generation_step=generation_step,
            tool_steps={},
            next_step_sequence=3,
            result=result,
            request_id="req-tool-failed",
            platform_id=1,
            end_user_id=2,
            client_id=None,
            events=LoopEventBuilder(conversation, loop, request_id="req-tool-failed"),
        ):
            events.append(wire(event, len(events) + 1))

        failed_step = next(
            event
            for event in events
            if event["type"] == "agent_step_completed"
            and event["payload"].get("stepType") == "mcp_tool"
        )
        assert failed_step["payload"]["status"] == "failed"
        assert events[-1]["type"] == "message_completed"
        assert loop.status == "completed"
        assert generation_step.status == "succeeded"

    asyncio.run(run())


class MaxTurnsEmbedStreamingModel:
    """WS max_turns 场景：前两轮流式请求工具，收尾提示到达后输出正文。

    第 3 次调用时首条消息是内部收尾提示（两种路径都包含“最大执行轮数”
    字样），此时模型只能直接回答、不得再请求工具；用同一个替身同时驱动
    legacy 与灰度路径，才能对比两路的调用次数和终止行为。
    """

    def __init__(self):
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        first = messages[0]
        if "最大执行轮数" in getattr(first, "content", ""):
            yield AIMessageChunk(content="已到执行上限，基于已有信息回答。")
            return
        if self.calls in (1, 2):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "lookup",
                        "args": '{"city": "上海"}',
                        "id": f"call-{self.calls}",
                        "index": 0,
                    }
                ],
            )
            return
        # 兜底：若轮次控制意外失效，模型直接回答，避免测试进程挂起。
        yield AIMessageChunk(content="兜底回答。")


def lookup_runtime_tool():
    """与 REST parity 同形状的内置工具替身，供 WS 两条路径绑定。"""

    return SimpleNamespace(
        name="lookup",
        kind="builtin",
        description="查天气",
        input_schema={"type": "object"},
    )


async def invoke_ws_lookup(tool=None, call=None, **kwargs):
    """legacy kwargs 风格与灰度 call 风格都接受，统一返回成功结果。"""

    return {"status": "completed", "result": {"weather": "晴", "temperature": 26}}


def test_embed_chat_gray_max_turns_wrapup_terminates_like_legacy():
    """WS 达到 max_turns 时，灰度与 legacy 都以收尾回答正常结束。

    AgentLoop 的 max_turns 对齐语义（达上限轮不执行新工具、随后禁工具收尾）
    在 REST 非流式与 SSE 已由 parity 用例覆盖；这里补充 WS 入口（gateway
    ``stream_embed_chat``）的对照：验证协议事件、loop 终态和模型调用次数在
    灰度切换前后一致，灰度达上限轮只多一条 failed 工具步骤记录（legacy
    不记录未执行的上限轮调用），且不会卡死或产生重复完成事件。
    """

    async def run(gray):
        settings = get_settings()
        original_max_turns = settings.agent_max_iterations
        object.__setattr__(settings, "agent_max_iterations", 2)
        repo = FakeConversationRepository()
        model = MaxTurnsEmbedStreamingModel()
        events = []
        try:
            async for event in stream_embed_chat(
                repo,
                SimpleNamespace(
                    agent=SimpleNamespace(id=11),
                    version=SimpleNamespace(system_prompt="回答"),
                    skill_instructions=[],
                    mcp_tools=[],
                ),
                model=model,
                platform_id=7,
                end_user_id=22,
                message="上海天气？",
                conversation_id=None,
                request_id=f"req-max-{gray}",
                citations=[],
                runtime_tools=[lookup_runtime_tool()],
                invoke_host_tool_fn=invoke_ws_lookup,
            ):
                events.append(wire(event, len(events) + 1))
        finally:
            object.__setattr__(
                settings, "agent_max_iterations", original_max_turns
            )
        return model, events, repo

    legacy_model, legacy_events, legacy_repo = asyncio.run(run(False))
    gray_model, gray_events, gray_repo = asyncio.run(run(True))

    # 两路都恰好调用 3 次模型：第 1 轮执行工具、第 2 轮达上限、第 3 轮收尾。
    assert gray_model.calls == 3
    assert legacy_model.calls == gray_model.calls

    # 两路都以 message_completed 终结且 loop 状态一致，不会中途卡死。
    assert legacy_events[-1]["type"] == "message_completed"
    assert gray_events[-1]["type"] == "message_completed"
    assert gray_repo.loop.status == "completed"
    assert legacy_repo.loop.status == gray_repo.loop.status

    # 收尾正文完整到达前端且两路内容一致（协议事件层可读性检查）。
    def completed_text(events):
        return next(
            event["payload"]["content"]
            for event in events
            if event["type"] == "message_completed"
        )

    gray_text = completed_text(gray_events)
    assert "已到执行上限" in gray_text
    assert gray_text == completed_text(legacy_events)

    # 工具步骤对比：两路第 1 轮 lookup 都成功；灰度把第 2 轮（达上限）的
    # lookup 记为 failed 工具步骤，legacy 不记录未执行的上限轮调用。
    def tool_steps(events):
        return [
            event
            for event in events
            if event["type"] == "agent_step_completed"
            and event["payload"].get("toolName") == "lookup"
        ]

    gray_steps = tool_steps(gray_events)
    legacy_steps = tool_steps(legacy_events)
    assert len(gray_steps) == 2
    assert [step["payload"]["status"] for step in gray_steps] == [
        "succeeded",
        "failed",
    ]
    # 单一 AgentLoop 下 legacy 臂与灰度臂同源：上限轮同样记录为 failed。
    assert [step["payload"]["status"] for step in legacy_steps] == [
        "succeeded",
        "failed",
    ]


class ConfirmWaitStreamingModel:
    """WS 确认场景：第 1 轮请求 pay 工具，确认放行后第 2 轮输出正文。

    第 1 轮结束后引擎会阻塞在工具回调内部（模拟 dispatcher 等待页面确认），
    只有测试侧放行确认 Future 后才会发生第 2 次模型调用；用同一替身驱动
    legacy 与灰度路径，可对比“确认后恢复”的调用次数和最终结果。
    """

    def __init__(self):
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "pay",
                        "args": '{"amount": 100}',
                        "id": "call-confirm",
                        "index": 0,
                    }
                ],
            )
            return
        # 第 2 轮：工具确认已返回，模型直接给出最终正文。
        yield AIMessageChunk(content="确认后继续执行，操作已完成。")


def pay_runtime_tool():
    """WS 确认场景使用的内置工具替身（pay 语义）。"""

    return SimpleNamespace(
        name="pay",
        kind="builtin",
        description="发起支付",
        input_schema={"type": "object"},
    )


def make_blocking_confirm_invoke(*, approved: bool):
    """构造“等待页面确认后放行”的 WS dispatcher 风格工具回调。

    回调在引擎的工具执行点挂起（等价于真实 dispatcher 等待页面确认
    Future），测试侧通过 ``entered`` 感知已进入等待，再用 ``gate`` 注入
    用户决策；批准返回 completed，拒绝返回 rejected。返回值形状与
    gateway/dispatcher.py 的 MCP 确认解析结果一致。
    """

    entered = asyncio.Event()
    gate = asyncio.get_running_loop().create_future()

    async def confirm_invoke(tool=None, call=None, **kwargs):
        entered.set()
        await gate
        if approved:
            return {
                "status": "completed",
                "result": {"approved": True, "amount": 100},
            }
        return {
            "status": "rejected",
            "error": {"code": "rejected", "message": "用户拒绝执行该工具"},
        }

    return confirm_invoke, entered, gate


def _run_embed_confirm_scenario(gray, approved):
    """执行一次 WS 确认场景，返回 (model, events, repo)。"""

    async def run():
        repo = FakeConversationRepository()
        model = ConfirmWaitStreamingModel()
        invoke, entered, gate = make_blocking_confirm_invoke(approved=approved)

        async def consume():
            events = []
            async for event in stream_embed_chat(
                repo,
                SimpleNamespace(
                    agent=SimpleNamespace(id=11),
                    version=SimpleNamespace(system_prompt="回答"),
                    skill_instructions=[],
                    mcp_tools=[],
                ),
                model=model,
                platform_id=7,
                end_user_id=22,
                message="确认支付 100 元？",
                conversation_id=None,
                request_id=f"req-confirm-{gray}-{approved}",
                citations=[],
                runtime_tools=[pay_runtime_tool()],
                invoke_host_tool_fn=invoke,
            ):
                events.append(wire(event, len(events) + 1))
            return events

        task = asyncio.create_task(consume())
        try:
            # 等待引擎进入工具确认等待点，再由测试侧模拟页面放行。
            await asyncio.wait_for(entered.wait(), timeout=5)
            gate.set_result(True)
            events = await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
        return model, events, repo

    return asyncio.run(run())


def test_embed_chat_gray_confirmation_approval_resumes_like_legacy():
    """WS 灰度路径：用户批准确认后模型循环恢复，事件与 legacy 一致。

    真实 WS 的 MCP/页面确认由连接层 dispatcher 在工具回调内等待并解析；
    这里用同一“阻塞等待→批准放行”回调分别驱动 legacy 与灰度，锁定两路
    引擎在确认后都恰好再调用一次模型、以相同工具步骤和收尾正文终结，
    不会卡死、不会把确认事件误当作普通失败或终止。
    """

    legacy_model, legacy_events, legacy_repo = _run_embed_confirm_scenario(
        False, approved=True
    )
    gray_model, gray_events, gray_repo = _run_embed_confirm_scenario(
        True, approved=True
    )

    assert gray_model.calls == 2
    assert legacy_model.calls == gray_model.calls
    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert gray_events[-1]["type"] == "message_completed"
    assert legacy_events[-1]["type"] == "message_completed"
    assert gray_repo.loop.status == "completed"
    assert legacy_repo.loop.status == gray_repo.loop.status

    def completed_text(events):
        return next(
            event["payload"]["content"]
            for event in events
            if event["type"] == "message_completed"
        )

    assert completed_text(gray_events) == completed_text(legacy_events)


class AskUserWaitStreamingModel:
    """WS ask_user 场景：第 1 轮调用 ask_user 工具，答复返回后第 2 轮输出正文。

    真实 WS 中 dispatcher 会先发送 question_required 事件，再在工具回调内
    等待连接层回传用户答复；本替身只关心引擎层“等待后恢复”语义，question
    事件的协议形状由 dispatcher 层测试覆盖。
    """

    def __init__(self):
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "ask_user",
                        "args": json.dumps(
                            {
                                "question": "选择订单处理方式？",
                                "options": [
                                    {"id": "merge", "label": "合并"},
                                    {"id": "skip", "label": "跳过"},
                                ],
                            }
                        ),
                        "id": "call-question",
                        "index": 0,
                    }
                ],
            )
            return
        # 第 2 轮：工具结果已携带用户答复，模型据此给出最终正文。
        yield AIMessageChunk(content="根据你的选择，我会合并重复订单。")


def ask_user_runtime_tool():
    """WS ask_user 场景使用的内置工具替身。"""

    return SimpleNamespace(
        name="ask_user",
        kind="builtin",
        description="向用户提问并等待选择或文字答复",
        input_schema={"type": "object"},
    )


def make_blocking_question_invoke():
    """构造“等待用户答复后返回结果”的 WS dispatcher 风格 ask_user 回调。"""

    entered = asyncio.Event()
    gate = asyncio.get_running_loop().create_future()

    async def question_invoke(tool=None, call=None, **kwargs):
        entered.set()
        await gate
        return {
            "status": "completed",
            "result": {
                "question": "选择订单处理方式？",
                "answer": {"selectedOptionId": "merge"},
            },
        }

    return question_invoke, entered, gate


def test_embed_chat_gray_ask_user_resumes_like_legacy():
    """WS 灰度路径：ask_user 用户答复返回后模型循环恢复，与 legacy 一致。

    用户提问不是终止也不是失败：两路引擎都应在工具回调阻塞等待后恢复，
    恰好再调用一次模型并给出基于答复的最终正文；事件类型序列、工具步骤与
    loop 终态保持一致，验证灰度没有把 ask_user 误判为需要终止的等待态。
    """

    async def run(gray):
        repo = FakeConversationRepository()
        model = AskUserWaitStreamingModel()
        invoke, entered, gate = make_blocking_question_invoke()

        async def consume():
            events = []
            async for event in stream_embed_chat(
                repo,
                SimpleNamespace(
                    agent=SimpleNamespace(id=11),
                    version=SimpleNamespace(system_prompt="回答"),
                    skill_instructions=[],
                    mcp_tools=[],
                ),
                model=model,
                platform_id=7,
                end_user_id=22,
                message="帮我处理重复订单",
                conversation_id=None,
                request_id=f"req-question-{gray}",
                citations=[],
                runtime_tools=[ask_user_runtime_tool()],
                invoke_host_tool_fn=invoke,
            ):
                events.append(wire(event, len(events) + 1))
            return events

        task = asyncio.create_task(consume())
        try:
            # 等待引擎进入 ask_user 等待点，再由测试侧模拟连接层回传答复。
            await asyncio.wait_for(entered.wait(), timeout=5)
            gate.set_result(True)
            events = await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
        return model, events, repo

    legacy_model, legacy_events, legacy_repo = asyncio.run(run(False))
    gray_model, gray_events, gray_repo = asyncio.run(run(True))

    assert gray_model.calls == 2
    assert legacy_model.calls == gray_model.calls
    assert [event["type"] for event in gray_events] == [
        event["type"] for event in legacy_events
    ]
    assert gray_events[-1]["type"] == "message_completed"
    assert legacy_events[-1]["type"] == "message_completed"
    assert gray_repo.loop.status == "completed"
    assert legacy_repo.loop.status == gray_repo.loop.status

    def completed_text(events):
        return next(
            event["payload"]["content"]
            for event in events
            if event["type"] == "message_completed"
        )

    assert completed_text(gray_events) == completed_text(legacy_events)

    def tool_steps(events):
        return [
            event
            for event in events
            if event["type"] == "agent_step_completed"
            and event["payload"].get("toolName") == "ask_user"
        ]

    assert [step["payload"]["status"] for step in tool_steps(gray_events)] == [
        "succeeded"
    ]
    assert [step["payload"]["status"] for step in tool_steps(legacy_events)] == [
        "succeeded"
    ]


def test_embed_chat_gray_confirmation_rejection_fails_step_like_legacy():
    """WS 灰度路径：用户拒绝确认时转为失败工具步骤，模型仍可正常收尾。

    拒绝不是取消也不是引擎终止：两路都只把该轮 pay 工具记为 failed 步骤，
    随后模型能基于拒绝原因给出最终正文并以 completed 结束；验证灰度不会
    把拒绝升级为整请求失败，也不会自动重试被拒绝的工具。
    """

    legacy_model, legacy_events, legacy_repo = _run_embed_confirm_scenario(
        False, approved=False
    )
    gray_model, gray_events, gray_repo = _run_embed_confirm_scenario(
        True, approved=False
    )

    assert gray_model.calls == 2
    assert legacy_model.calls == gray_model.calls
    assert gray_events[-1]["type"] == "message_completed"
    assert legacy_events[-1]["type"] == "message_completed"
    assert gray_repo.loop.status == "completed"
    assert legacy_repo.loop.status == gray_repo.loop.status

    def tool_steps(events):
        return [
            event
            for event in events
            if event["type"] == "agent_step_completed"
            and event["payload"].get("toolName") == "pay"
        ]

    assert [step["payload"]["status"] for step in tool_steps(gray_events)] == [
        "failed"
    ]
    assert [step["payload"]["status"] for step in tool_steps(legacy_events)] == [
        "failed"
    ]

    def completed_text(events):
        return next(
            event["payload"]["content"]
            for event in events
            if event["type"] == "message_completed"
        )

    assert completed_text(gray_events) == completed_text(legacy_events)
