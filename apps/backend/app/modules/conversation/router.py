from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.schemas import ChatRequest, ChatResponse
from app.modules.conversation.services import (
    execute_chat,
    retrieve_citations,
    stream_chat,
)
from app.modules.conversation.runtime import format_sse_event, load_runtime_context
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.mcp.runtime import RepositoryMcpExecutor
from app.modules.mcp.services import invoke_tool
from app.modules.skill.repositories import SkillRepository
from app.modules.skill_runner.client import SkillRunnerClient
from app.modules.skill_runner.services import execute_skill_script
from app.shared.exceptions import NotFoundException
from app.shared.responses import success_response

router = APIRouter(prefix="/agents", tags=["conversation"])


async def _prepare(
    agent_id: int,
    payload: ChatRequest,
    current_user,
    session: AsyncSession,
):
    agent_repo = AgentRepository(session)
    agent = await agent_repo.get_published_agent_for_user(agent_id, current_user.id)
    if agent is None:
        raise NotFoundException("published agent not found")
    skill_repo = SkillRepository(session)
    context = await load_runtime_context(
        agent_repo,
        KnowledgeRepository(session),
        skill_repo,
        McpRepository(session),
        agent_id=agent_id,
        platform_id=agent.platform_id,
    )
    knowledge_repo = KnowledgeRepository(session)
    citations = await retrieve_citations(
        knowledge_repo, context.knowledge_bases, payload.message
    )
    mcp_repo = McpRepository(session)

    async def invoke(**kwargs):
        tool = kwargs.get("tool")
        if getattr(tool, "kind", None) == "skill_script":
            return await execute_skill_script(
                skill_repo,
                SkillRunnerClient(),
                tool=tool,
                call=kwargs["call"],
                platform_id=agent.platform_id,
                agent_id=agent_id,
                user_id=current_user.id,
            )
        return await invoke_tool(
            mcp_repo,
            RepositoryMcpExecutor(mcp_repo),
            platform_id=agent.platform_id,
            agent_id=agent_id,
            user_id=current_user.id,
            **{key: value for key, value in kwargs.items() if key not in {"tool", "call"}},
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
    return await execute_chat(
        ConversationRepository(session),
        context,
        platform_id=agent.platform_id,
        user_id=current_user.id,
        message=payload.message,
        conversation_id=payload.conversation_id,
        model=build_chat_model(context.version),
        citations=[citation.model_dump() for citation in citations],
        invoke_tool_fn=invoke,
    )


@router.post("/{agent_id}/chat")
async def chat_endpoint(
    agent_id: int,
    payload: ChatRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    if not payload.stream:
        conversation, assistant, result = await _execute(
            agent_id, payload, current_user, session
        )
        data = ChatResponse(
            conversation_id=conversation.id,
            message_id=assistant.id,
            content=result.content,
            citations=result.citations,
            knowledge_grounded=result.knowledge_grounded,
            pending_confirmation_id=result.pending_confirmation_id,
        )
        return success_response(data=data)

    async def events() -> AsyncIterator[str]:
        try:
            agent, context, citations, invoke = await _prepare(
                agent_id, payload, current_user, session
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

            if context.mcp_tools or context.skill_script_tools:
                conversation, assistant, result = await execute_chat(
                    ConversationRepository(session),
                    context,
                    platform_id=agent.platform_id,
                    user_id=current_user.id,
                    message=payload.message,
                    conversation_id=payload.conversation_id,
                    model=build_chat_model(context.version),
                    citations=[citation.model_dump() for citation in citations],
                    invoke_tool_fn=invoke,
                )
                for citation in result.citations:
                    yield emit("citation", citation, conversation.id, assistant.id)
                for tool_event in result.tool_events or []:
                    yield emit(
                        "tool_call",
                        {"tool": tool_event["tool"]},
                        conversation.id,
                        assistant.id,
                    )
                    outcome = tool_event["outcome"]
                    yield emit(
                        (
                            "confirmation_required"
                            if outcome.status == "confirmation_required"
                            else "tool_result"
                        ),
                        outcome.model_dump(),
                        conversation.id,
                        assistant.id,
                    )
                if result.content:
                    yield emit(
                        "message_delta",
                        {"content": result.content},
                        conversation.id,
                        assistant.id,
                    )
                yield emit(
                    "message_completed",
                    {
                        "content": result.content,
                        "citations": result.citations,
                        "knowledge_grounded": result.knowledge_grounded,
                    },
                    conversation.id,
                    assistant.id,
                )
            else:
                async for item in stream_chat(
                    ConversationRepository(session),
                    context,
                    platform_id=agent.platform_id,
                    user_id=current_user.id,
                    message=payload.message,
                    conversation_id=payload.conversation_id,
                    model=build_chat_model(context.version),
                    citations=[citation.model_dump() for citation in citations],
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
                    assistant = item["assistant"]
                    result = item["result"]
                    for citation in result.citations:
                        yield emit("citation", citation, conversation.id, assistant.id)
                    yield emit(
                        "message_completed",
                        {
                            "content": result.content,
                            "citations": result.citations,
                            "knowledge_grounded": result.knowledge_grounded,
                        },
                        conversation.id,
                        assistant.id,
                    )
        except Exception:
            yield format_sse_event(
                {
                    "type": "error",
                    "conversation_id": payload.conversation_id or 0,
                    "message_id": None,
                    "sequence": 1,
                    "payload": {"message": "chat failed"},
                }
            )

    return StreamingResponse(events(), media_type="text/event-stream")
