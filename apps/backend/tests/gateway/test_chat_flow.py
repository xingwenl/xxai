import asyncio
from types import SimpleNamespace

from app.modules.gateway.runtime import filter_conflicting_runtime_tools, stream_embed_chat


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
        step = SimpleNamespace(id=self.next_step_id, **values)
        self.next_step_id += 1
        return step

    async def save_loop(self, loop):
        self.loop = loop
        return loop


class FakeStreamingModel:
    async def astream(self, _messages):
        for content in ("你好", "，这里是回答"):
            yield SimpleNamespace(content=content)


class FakeUsageStreamingModel:
    async def astream(self, _messages):
        yield SimpleNamespace(
            content="你好",
            usage_metadata={
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        )


class FailingStreamingModel:
    async def astream(self, _messages):
        raise RuntimeError("HTTP 502 Bad Gateway")
        yield  # pragma: no cover


def test_runtime_tool_name_conflicts_exclude_all_duplicates():
    tools = [
        SimpleNamespace(name="same", kind="builtin"),
        SimpleNamespace(name="same", server_id=4),
        SimpleNamespace(name="read_only", server_id=4),
    ]

    filtered = filter_conflicting_runtime_tools(tools)

    assert [tool.name for tool in filtered] == ["read_only"]


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
            events.append(event)
        return repo, events

    repo, events = asyncio.run(collect())

    assert events[-1]["type"] == "error"
    assert events[-1]["payload"]["message"] == "Agent 连接失败（HTTP 502），本轮对话已结束"
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
            events.append(event["type"])

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
                    model_name="deepseek-v4-pro",
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
            events.append(event)

        completed = events[-1]
        assert completed["type"] == "message_completed"
        assert completed["result"].usage == {
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
            if event["type"].startswith("agent_step"):
                events.append(event)

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
