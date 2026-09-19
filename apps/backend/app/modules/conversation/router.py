import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session, get_session_factory
from app.core.security import require_current_active_user_or_wechat_service
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.schemas import ChatRequest, ChatResponse
from app.modules.conversation.services import (
    build_loop_payload,
    execute_chat,
    retrieve_citations,
    stream_chat,
)
from app.modules.conversation.runtime import (
    build_agent_error_payload,
    format_sse_event,
    load_runtime_context,
)
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.conversation.tool_dispatch import build_tool_invoker
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.agent_runtime.adapters import agent_result_from_legacy
from app.modules.agent_runtime.runtime import cancel_and_join_tasks
from app.shared.exceptions import NotFoundException
from app.shared.responses import success_response

router = APIRouter(prefix="/agents", tags=["conversation"])


async def _prepare(
    agent_id: int,
    payload: ChatRequest,
    current_user,
    session: AsyncSession,
    tool_session: AsyncSession | None = None,
):
    agent_repo = AgentRepository(session)
    agent = await agent_repo.get_published_agent_for_user(agent_id, current_user.id)
    if agent is None:
        raise NotFoundException("published agent not found")
    skill_repo = SkillRepository(session)
    builtin_tool_repo = BuiltinToolRepository(session)
    context = await load_runtime_context(
        agent_repo,
        KnowledgeRepository(session),
        skill_repo,
        McpRepository(session),
        builtin_tool_repo,
        agent_id=agent_id,
        platform_id=agent.platform_id,
    )
    knowledge_repo = KnowledgeRepository(session)
    citations = await retrieve_citations(
        knowledge_repo, context.knowledge_bases, payload.message
    )
    # 工具执行使用独立 Session：模型循环跑在 runtime 内部启动的独立 Task 中，
    # 与消费方的会话/消息落库共用同一个 AsyncSession 会触发 SQLAlchemy 并发
    # 状态错误（另一操作进行中 / close 与 commit 相撞）。
    tool_session = tool_session if tool_session is not None else session
    tool_builtin_repo = BuiltinToolRepository(tool_session)
    tool_skill_repo = SkillRepository(tool_session)
    tool_mcp_repo = McpRepository(tool_session)

    # 分派逻辑抽到 conversation/tool_dispatch.py，与无人值守任务共用一份，
    # 避免两边支持的工具范围漂移。会话 id 在 execute_chat 内解析后才可用，
    # 因此用回调延迟求值。
    invoke = build_tool_invoker(
        platform_id=agent.platform_id,
        agent_id=agent_id,
        user_id=current_user.id,
        builtin_repo=tool_builtin_repo,
        skill_repo=tool_skill_repo,
        mcp_repo=tool_mcp_repo,
        tool_session=tool_session,
        conversation_id_provider=lambda: getattr(context, "conversation_id", None),
    )

    return agent, context, citations, invoke


async def _execute(
    agent_id: int,
    payload: ChatRequest,
    current_user,
    session: AsyncSession,
):
    agent, context, citations, invoke = await _prepare(
        agent_id, payload, current_user, session
    )
    conversation, assistant, result = await execute_chat(
        ConversationRepository(session),
        context,
        platform_id=agent.platform_id,
        user_id=current_user.id,
        message=payload.message,
        conversation_id=payload.conversation_id,
        # 会话 id 在 execute_chat 内解析会话后才可用，因此延迟到发请求时求值。
        model=build_chat_model(
            context.version,
            session_id_provider=lambda: getattr(context, "conversation_id", None),
        ),
        citations=[citation.model_dump() for citation in citations],
        invoke_tool_fn=invoke,
    )
    return conversation, assistant, agent_result_from_legacy(result)


@router.post("/{agent_id}/chat")
async def chat_endpoint(
    agent_id: int,
    payload: ChatRequest,
    current_user=Depends(require_current_active_user_or_wechat_service),
    session: AsyncSession = Depends(get_db_session),
):
    if not payload.stream:
        conversation, assistant, result = await _execute(
            agent_id, payload, current_user, session
        )
        loop = (
            await build_loop_payload(
                ConversationRepository(session), result.loop_id, conversation.id
            )
            if result.loop_id
            else None
        )
        data = ChatResponse(
            conversation_id=conversation.id,
            message_id=assistant.id,
            content=result.content,
            citations=result.citations,
            knowledge_grounded=result.knowledge_grounded,
            pending_confirmation_id=result.pending_confirmation_id,
            content_blocks=assistant.content_blocks,
            loop=loop,
        )
        return success_response(data=data)

    async def _events_impl(
        tool_session: AsyncSession,
        model_tasks: set[asyncio.Task],
    ) -> AsyncIterator[str]:
        try:
            agent, context, citations, invoke = await _prepare(
                agent_id,
                payload,
                current_user,
                session,
                tool_session=tool_session,
            )
            sequence = 0

            def emit(
                event_type: str,
                payload_data: dict,
                conversation_id: int,
                message_id: int | None,
            ):
                nonlocal sequence
                sequence += 1
                return format_sse_event(
                    {
                        "type": event_type,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "sequence": sequence,
                        "payload": payload_data,
                    }
                )

            async for item in stream_chat(
                ConversationRepository(session),
                context,
                platform_id=agent.platform_id,
                user_id=current_user.id,
                message=payload.message,
                conversation_id=payload.conversation_id,
                # 同上：会话在 stream_chat 内解析，这里只传求值入口。
                model=build_chat_model(
                    context.version,
                    session_id_provider=lambda: getattr(
                        context, "conversation_id", None
                    ),
                ),
                citations=[citation.model_dump() for citation in citations],
                invoke_tool_fn=invoke,
                on_model_task_started=model_tasks.add,
            ):
                conversation = item["conversation"]
                if item["type"] == "message_delta":
                    yield emit(
                        "message_delta",
                        {"content": item["content"]},
                        conversation.id,
                        None,
                    )
                    continue
                if item["type"].startswith("agent_"):
                    yield emit(
                        item["type"],
                        item.get("payload", {}),
                        item["conversation"].id,
                        getattr(item.get("assistant"), "id", None),
                    )
                    continue
                if item["type"] in {
                    "tool_call",
                    "tool_result",
                    "confirmation_required",
                }:
                    yield emit(item["type"], item["payload"], conversation.id, None)
                    continue
                if item["type"] == "error":
                    yield emit("error", item["payload"], conversation.id, None)
                    return
                assistant = item["assistant"]
                result = item["result"]
                for citation in result.citations:
                    yield emit("citation", citation, conversation.id, assistant.id)
                yield emit(
                    "message_completed",
                    {
                        "content": result.content,
                        "contentBlocks": assistant.content_blocks,
                        "citations": result.citations,
                        "knowledge_grounded": result.knowledge_grounded,
                        "loop": (
                            {
                                "id": str(result.loop_id),
                                "requestId": f"conversation-{conversation.id}",
                                "status": "completed",
                                "summary": "已完成回答",
                                "steps": [],
                            }
                            if result.loop_id
                            else None
                        ),
                    },
                    conversation.id,
                    assistant.id,
                )
        except Exception as error:
            yield format_sse_event(
                {
                    "type": "error",
                    "conversation_id": payload.conversation_id or 0,
                    "message_id": None,
                    "sequence": 1,
                    "payload": build_agent_error_payload(error),
                }
            )

    async def events() -> AsyncIterator[str]:
        """SSE 出口，负责工具 Session 与模型 Task 的生命周期收口。

        客户端断开或生成器被提前关闭时，内层模型 Task 可能仍在写库；必须先
        取消并等它收尾，再退出 `async with` 关闭工具 Session，否则会出现
        close() 与 commit() 相撞的 SQLAlchemy 状态错误。
        """

        model_tasks: set[asyncio.Task] = set()
        async with get_session_factory()() as tool_session:
            try:
                async for chunk in _events_impl(tool_session, model_tasks):
                    yield chunk
            finally:
                await cancel_and_join_tasks(model_tasks)

    return StreamingResponse(events(), media_type="text/event-stream")
