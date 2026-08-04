"""网关请求任务和 Embed 对话流的运行时编排。"""

import asyncio
from collections.abc import AsyncIterator

from app.core.logging import get_logger
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import build_system_prompt, stream_graph
from app.shared.exceptions import NotFoundException

logger = get_logger(__name__)


class RequestRegistry:
    """按 requestId 管理连接内任务，提供幂等和取消能力。

    ``_completed`` 防止同一个 requestId 在任务结束后被重复提交；
    ``_tasks`` 保存仍可取消的 asyncio Task。它只管理请求生命周期，
    宿主工具的 callId 幂等由 HostToolRepository 单独负责。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed: set[str] = set()

    def register(self, request_id: str, task: asyncio.Task) -> bool:
        """注册新任务；活跃或已完成的同一 requestId 都不重复执行。"""
        existing = self._tasks.get(request_id)
        if existing is not None and not existing.done():
            return False
        if request_id in self._completed:
            return False
        self._tasks[request_id] = task
        return True

    def complete(self, request_id: str) -> None:
        """将请求标记为完成，释放 Task 引用并保留幂等记录。"""
        self._tasks.pop(request_id, None)
        self._completed.add(request_id)

    async def cancel(self, request_id: str) -> bool:
        """取消仍在运行的请求，并等待 Task 真正收尾。"""
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
    client_id: str | None = None,
    message: str,
    conversation_id: int | None,
    request_id: str,
    citations: list[dict],
    host_tools: list | None = None,
    invoke_host_tool_fn=None,
) -> AsyncIterator[dict]:
    """把一次 Embed 消息转换为网关事件流。

    流程分为四段：先按平台和最终用户校验/创建会话，再写入用户消息，
    然后把模型和宿主工具的中间事件转成网关事件，最后保存并发送助手消息。
    ``host_tools`` 与 ``invoke_host_tool_fn`` 由 WebSocket 连接层注入，
    因此这个运行时不会绕过当前连接的 token 和页面注册权限。
    """
    logger.info(
        "Embed chat started request_id=%s platform_id=%s end_user_id=%s client_id=%s conversation_id=%s message_chars=%s citation_count=%s host_tool_count=%s",
        request_id,
        platform_id,
        end_user_id,
        client_id,
        conversation_id,
        len(message),
        len(citations),
        len(host_tools or []),
    )
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
        # 先通知前端请求已被接受，后续模型调用可能需要等待外部服务或页面工具。
        "type": "message_started",
        "conversation": conversation,
        "request_id": request_id,
    }

    result = None
    async for item in stream_graph(
        model,
        system_prompt=build_system_prompt(
            context.version,
            context.skill_instructions,
            citations,
            host_tools=host_tools,
        ),
        user_message=message,
        citations=citations,
        tools=host_tools,
        invoke_tool_fn=invoke_host_tool_fn,
    ):
        # message_delta 立即向前端流式发送；completed 事件只保留最终 GraphResult，
        # 避免同一段回答被重复写入消息表。
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
    if result.usage is not None:
        await repo.record_model_usage(
            platform_id=platform_id,
            agent_id=context.agent.id,
            agent_version_id=getattr(context.version, "id", None),
            client_id=client_id,
            platform_end_user_id=end_user_id,
            conversation_id=conversation.id,
            message_id=assistant.id,
            request_id=request_id,
            model_name=getattr(context.version, "model_name", None),
            prompt_tokens=result.usage["prompt_tokens"],
            completion_tokens=result.usage["completion_tokens"],
            total_tokens=result.usage["total_tokens"],
        )
    logger.info(
        "Embed chat completed request_id=%s conversation_id=%s assistant_id=%s knowledge_grounded=%s citation_count=%s usage=%s",
        request_id,
        conversation.id,
        assistant.id,
        result.knowledge_grounded,
        len(result.citations),
        result.usage,
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
