from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    build_system_prompt,
    run_graph,
)
from app.modules.knowledge.runtime import build_embedding_model
from app.modules.knowledge.services import build_citations, validate_embedding_dimension
from app.shared.exceptions import NotFoundException


async def retrieve_citations(knowledge_repo, knowledge_bases, query: str):
    chunks = []
    for base in knowledge_bases:
        embedding = await build_embedding_model(base).aget_query_embedding(query)
        validate_embedding_dimension(
            embedding, expected_dimension=base.embedding_dimension
        )
        chunks.extend(await knowledge_repo.search(base, embedding, limit=5))
    return build_citations(
        [
            {
                "title": chunk.source_metadata.get("title", ""),
                "source_url": chunk.source_metadata.get("source_url"),
                "content": chunk.content,
            }
            for chunk in chunks
        ]
    )


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
        tools=context.mcp_tools,
        invoke_tool_fn=invoke_tool_fn,
    )
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        citations=result.citations,
        knowledge_grounded=result.knowledge_grounded,
    )
    return conversation, assistant, result
