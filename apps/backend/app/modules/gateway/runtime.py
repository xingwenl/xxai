import asyncio
from collections.abc import AsyncIterator

from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import build_system_prompt, stream_graph
from app.shared.exceptions import NotFoundException


class RequestRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed: set[str] = set()

    def register(self, request_id: str, task: asyncio.Task) -> bool:
        existing = self._tasks.get(request_id)
        if existing is not None and not existing.done():
            return False
        if request_id in self._completed:
            return False
        self._tasks[request_id] = task
        return True

    def complete(self, request_id: str) -> None:
        self._tasks.pop(request_id, None)
        self._completed.add(request_id)

    async def cancel(self, request_id: str) -> bool:
        task = self._tasks.get(request_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._tasks.pop(request_id, None)
        return True


async def stream_embed_chat(
    repo: ConversationRepository,
    context,
    *,
    model,
    platform_id: int,
    end_user_id: int,
    message: str,
    conversation_id: int | None,
    request_id: str,
    citations: list[dict],
) -> AsyncIterator[dict]:
    conversation = None
    if conversation_id is not None:
        conversation = await repo.get_for_principal(
            conversation_id, platform_id, end_user_id=end_user_id
        )
        if conversation is None or conversation.agent_id != context.agent.id:
            raise NotFoundException("conversation not found")
    if conversation is None:
        conversation = await repo.create_for_principal(
            platform_id,
            context.agent.id,
            end_user_id=end_user_id,
            title=message,
        )

    await repo.create_message(
        conversation.id,
        role="user",
        content=message,
        citations=[],
        knowledge_grounded=False,
    )
    yield {
        "type": "message_started",
        "conversation": conversation,
        "request_id": request_id,
    }

    result = None
    async for item in stream_graph(
        model,
        system_prompt=build_system_prompt(
            context.version, context.skill_instructions, citations
        ),
        user_message=message,
        citations=citations,
    ):
        if item["type"] == "message_delta":
            yield {
                "type": "message_delta",
                "content": item["content"],
                "conversation": conversation,
                "request_id": request_id,
            }
            continue
        result = item["result"]

    if result is None:
        return
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        citations=result.citations,
        knowledge_grounded=result.knowledge_grounded,
    )
    for citation in result.citations:
        yield {
            "type": "citation",
            "citation": citation,
            "conversation": conversation,
            "message": assistant,
            "request_id": request_id,
        }
    yield {
        "type": "message_completed",
        "content": result.content,
        "conversation": conversation,
        "message": assistant,
        "result": result,
        "request_id": request_id,
    }
