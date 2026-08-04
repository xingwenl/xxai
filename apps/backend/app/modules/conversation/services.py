from app.core.logging import get_logger
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    build_system_prompt,
    run_graph,
    stream_graph,
)
from app.modules.knowledge.runtime import build_embedding_model
from app.modules.knowledge.services import build_citations, validate_embedding_dimension
from app.shared.exceptions import NotFoundException

logger = get_logger(__name__)


async def retrieve_citations(knowledge_repo, knowledge_bases, query: str):
    logger.info(
        "Retrieving citations knowledge_bases=%s query_chars=%s",
        [getattr(base, "id", None) for base in knowledge_bases],
        len(query),
    )
    chunks = []
    for base in knowledge_bases:
        embedding = await build_embedding_model(base).aget_query_embedding(query)
        validate_embedding_dimension(
            embedding, expected_dimension=base.embedding_dimension
        )
        matches = await knowledge_repo.search(base, embedding, limit=5)
        logger.info(
            "Knowledge search completed base_id=%s matches=%s active_index_version=%s",
            getattr(base, "id", None),
            len(matches),
            getattr(base, "active_index_version", None),
        )
        chunks.extend(matches)
    citations = build_citations(
        [
            {
                "title": chunk.source_metadata.get("title", ""),
                "source_url": chunk.source_metadata.get("source_url"),
                "content": chunk.content,
            }
            for chunk in chunks
        ]
    )
    logger.info(
        "Citation build completed matches=%s citations=%s titles=%s",
        len(chunks),
        len(citations),
        [citation.title for citation in citations[:5]],
    )
    return citations


async def execute_chat(
    repo: ConversationRepository,
    context,
    *,
    platform_id: int,
    user_id: int,
    message: str,
    conversation_id: int | None,
    model,
    citations: list[dict],
    invoke_tool_fn=None,
):
    logger.info(
        "Conversation chat started platform_id=%s user_id=%s agent_id=%s conversation_id=%s message_chars=%s citation_count=%s",
        platform_id,
        user_id,
        context.agent.id,
        conversation_id,
        len(message),
        len(citations),
    )
    conversation = None
    if conversation_id is not None:
        conversation = await repo.get(conversation_id, platform_id, user_id)
        if conversation is None or conversation.agent_id != context.agent.id:
            raise NotFoundException("conversation not found")
    if conversation is None:
        conversation = await repo.create(
            platform_id, context.agent.id, user_id, message
        )
    await repo.create_message(
        conversation.id,
        role="user",
        content=message,
        citations=[],
        knowledge_grounded=False,
    )
    result = await run_graph(
        model,
        system_prompt=build_system_prompt(
            context.version, context.skill_instructions, citations
        ),
        user_message=message,
        citations=citations,
        tools=[*context.mcp_tools, *context.skill_script_tools],
        invoke_tool_fn=invoke_tool_fn,
    )
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        citations=result.citations,
        knowledge_grounded=result.knowledge_grounded,
    )
    logger.info(
        "Conversation chat completed conversation_id=%s assistant_id=%s knowledge_grounded=%s citation_count=%s usage=%s",
        conversation.id,
        assistant.id,
        result.knowledge_grounded,
        len(result.citations),
        result.usage,
    )
    return conversation, assistant, result


async def stream_chat(
    repo: ConversationRepository,
    context,
    *,
    platform_id: int,
    user_id: int,
    message: str,
    conversation_id: int | None,
    model,
    citations: list[dict],
):
    logger.info(
        "Conversation stream chat started platform_id=%s user_id=%s agent_id=%s conversation_id=%s message_chars=%s citation_count=%s",
        platform_id,
        user_id,
        context.agent.id,
        conversation_id,
        len(message),
        len(citations),
    )
    conversation = None
    if conversation_id is not None:
        conversation = await repo.get(conversation_id, platform_id, user_id)
        if conversation is None or conversation.agent_id != context.agent.id:
            raise NotFoundException("conversation not found")
    if conversation is None:
        conversation = await repo.create(
            platform_id, context.agent.id, user_id, message
        )
    await repo.create_message(
        conversation.id,
        role="user",
        content=message,
        citations=[],
        knowledge_grounded=False,
    )
    async for item in stream_graph(
        model,
        system_prompt=build_system_prompt(
            context.version, context.skill_instructions, citations
        ),
        user_message=message,
        citations=citations,
    ):
        if item["type"] == "message_delta":
            yield {"type": "message_delta", "conversation": conversation, **item}
            continue
        result = item["result"]
        assistant = await repo.create_message(
            conversation.id,
            role="assistant",
            content=result.content,
            citations=result.citations,
            knowledge_grounded=result.knowledge_grounded,
        )
        logger.info(
            "Conversation stream chat completed conversation_id=%s assistant_id=%s knowledge_grounded=%s citation_count=%s usage=%s",
            conversation.id,
            assistant.id,
            result.knowledge_grounded,
            len(result.citations),
            result.usage,
        )
        yield {
            "type": "completed",
            "conversation": conversation,
            "assistant": assistant,
            "result": result,
        }
