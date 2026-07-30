import asyncio
from types import SimpleNamespace

from app.modules.gateway.runtime import stream_embed_chat


class FakeConversation:
    def __init__(self, identifier=101):
        self.id = identifier
        self.agent_id = 11


class FakeMessage:
    def __init__(self, identifier, content):
        self.id = identifier
        self.content = content


class FakeConversationRepository:
    def __init__(self):
        self.conversation = None
        self.messages = []
        self.usage_records = []
        self.next_message_id = 1

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

    async def record_model_usage(self, **values):
        self.usage_records.append(values)


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

        assert events == [
            "message_started",
            "message_delta",
            "message_delta",
            "citation",
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
