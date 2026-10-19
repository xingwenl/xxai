import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

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
    load_runtime_context,
)
from app.modules.agent_runtime.events import (
    error as protocol_error,
    run_events_from_stream_item,
    to_sse_block,
)
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.model_registry.resolver import resolve_chat_model
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
        loop_run_id_provider=lambda: getattr(context, "loop_run_id", None),
    )

    # 对话主模型统一从平台模型注册表解析：绑定了 chat 模型就用它，没有绑定才回落
    # `.env` 默认值（resolved 为 None）。已绑定但停用等情况会直接抛稳定错误。
    resolved = await resolve_chat_model(
        session, platform_id=agent.platform_id, agent_id=agent_id
    )

    return agent, context, citations, invoke, resolved


async def _execute(
    agent_id: int,
    payload: ChatRequest,
    current_user,
    session: AsyncSession,
):
    agent, context, citations, invoke, resolved = await _prepare(
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
            resolved=resolved,
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
        # 每次 SSE 请求一个稳定 requestId：断线重连时用于对齐同一次回答的进度。
        request_id = f"sse-{uuid4().hex}"
        sequence = 0
        try:
            agent, context, citations, invoke, resolved = await _prepare(
                agent_id,
                payload,
                current_user,
                session,
                tool_session=tool_session,
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
                    resolved=resolved,
                    session_id_provider=lambda: getattr(
                        context, "conversation_id", None
                    ),
                ),
                citations=[citation.model_dump() for citation in citations],
                invoke_tool_fn=invoke,
                on_model_task_started=model_tasks.add,
            ):
                # 服务层 item 统一由 agent_runtime.events 映射为线协议事件，
                # SSE 只做编码，避免与 WebSocket 各组装一套事件形状。
                for event in run_events_from_stream_item(item, request_id=request_id):
                    sequence += 1
                    yield to_sse_block(event, sequence=sequence)
        except Exception as error:
            sequence += 1
            yield to_sse_block(
                protocol_error(
                    request_id=request_id,
                    payload=build_agent_error_payload(error),
                    conversation_id=payload.conversation_id,
                ),
                sequence=sequence,
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
