from datetime import datetime, timedelta, timezone

from app.core.logging import get_logger
from app.core.config import get_settings
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    attach_tool_snapshots,
    build_tool_snapshots,
    build_system_prompt,
    build_step_payload,
    resolve_context_window_tokens,
    run_graph,
    stream_graph,
    tool_step_values,
)
from app.modules.knowledge.runtime import build_embedding_model
from app.modules.knowledge.services import build_citations, validate_embedding_dimension
from app.modules.conversation.schemas import sanitize_content_blocks
from app.shared.exceptions import NotFoundException


def _content_blocks(content: str, extra_blocks: list[dict] | None = None) -> list[dict]:
    return sanitize_content_blocks(
        [
            {
                "id": "answer_markdown",
                "type": "markdown",
                "text": content,
                "status": "completed",
            }
        ]
        + (extra_blocks or [])
    )


def _rest_runtime_tools(*builtin_tools) -> list:
    """REST 路径可用的内置工具列表。

    ask_user 只在 embed WebSocket 链路可用（网关按客户端能力注入）；
    REST 路径即使后台绑定了该工具也不暴露，避免模型调用后无执行器。
    """
    return [
        tool for tool in builtin_tools if getattr(tool, "name", None) != "ask_user"
    ]


async def build_loop_payload(
    repo: ConversationRepository, loop_id: int, conversation_id: int
) -> dict | None:
    loop = await repo.get_loop(loop_id, conversation_id)
    if loop is None:
        return None
    steps = await repo.list_loop_steps(loop.id)
    return {
        "id": str(loop.id),
        "requestId": loop.request_id,
        "status": loop.status,
        "summary": loop.summary,
        "steps": [
            {
                "id": str(step.id),
                "sequence": step.sequence,
                "stepType": step.step_type,
                "title": step.title,
                "status": step.status,
                "outputSummary": step.output_summary,
                "thinkingText": step.thinking_text,
                "toolName": step.tool_name,
                "skillName": step.skill_name,
                "skillVersion": step.skill_version,
                "citationRefs": step.citation_refs,
                "error": step.error,
            }
            for step in steps
        ],
    }


async def build_loop_with_steps(
    repo,
    conversation,
    user_message,
    request_id: str,
    citations: list[dict],
    skill_usages: list[dict] | None = None,
    *,
    retrieval_input_summary: str | None = None,
):
    """创建 Loop 与检索/技能初始步骤（仅 flush，不提交）。

    提交时机由调用方控制：REST 路径在全部步骤创建后统一 save_loop，
    Embed 网关路径按原逻辑在每类步骤创建后分别 save_loop，保证两边
    落库进度一致。
    """
    loop = await repo.create_loop(
        conversation.id,
        user_message_id=user_message.id,
        request_id=request_id,
        status="running",
        summary="正在处理请求",
    )
    retrieval = await repo.create_loop_step(
        loop.id,
        sequence=1,
        step_type="knowledge_retrieval",
        title="检索知识库",
        status="succeeded",
        input_summary=retrieval_input_summary,
        output_summary=(
            f"命中 {len(citations)} 条引用" if citations else "未命中知识库引用"
        ),
        citation_refs=citations,
    )
    skill_steps = []
    for offset, usage in enumerate(skill_usages or [], start=2):
        skill_steps.append(
            await repo.create_loop_step(
                loop.id,
                sequence=offset,
                step_type="skill_instruction",
                title=f"应用技能：{usage['name']}",
                status="succeeded",
                output_summary="技能元数据已加载"
                + ("，可调用脚本工具" if usage.get("has_script_tool") else ""),
                skill_name=usage["name"],
                skill_version=usage.get("version"),
                step_metadata={
                    "slug": usage.get("slug"),
                    "hasScriptTool": usage.get("has_script_tool", False),
                },
            )
        )
    return loop, retrieval, skill_steps


async def _start_loop(
    repo,
    conversation,
    user_message,
    request_id: str,
    citations: list[dict],
    skill_usages: list[dict] | None = None,
):
    loop, retrieval, skill_steps = await build_loop_with_steps(
        repo,
        conversation,
        user_message,
        request_id,
        citations,
        skill_usages,
    )
    await repo.save_loop(loop)
    return loop, retrieval, skill_steps


logger = get_logger(__name__)


async def load_recent_history(repo: ConversationRepository, conversation_id: int):
    """按配置窗口读取近期已完成消息，供模型上下文回填。"""
    settings = get_settings()
    snapshot_retention = (
        settings.tool_snapshot_retention_seconds
        or settings.conversation_history_window_seconds
    )
    # 快照保留期大于普通历史窗口时按较大窗口读取，正文与快照各自按窗口过滤。
    window = max(
        settings.conversation_history_window_seconds, snapshot_retention
    )
    since = datetime.now(timezone.utc) - timedelta(seconds=window)
    return await repo.list_recent_context_messages(conversation_id, since=since)


def _tool_snapshot_metadata(result) -> dict:
    """从一轮 GraphResult 构造快照并写入消息扩展元数据。"""
    return attach_tool_snapshots({}, build_tool_snapshots(result.tool_events))


async def _resolve_conversation(
    repo: ConversationRepository,
    context,
    *,
    platform_id: int,
    user_id: int,
    message: str,
    conversation_id: int | None,
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
    context.conversation_id = conversation.id
    return conversation


async def _finish_stream_chat(
    repo: ConversationRepository,
    conversation,
    loop,
    generation_step,
    *,
    tool_steps: dict,
    next_step_sequence: int,
    result,
):
    """保存助手消息与剩余工具步骤，输出流式收尾事件。"""
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        content_blocks=_content_blocks(result.content, result.content_blocks),
        citations=result.citations,
        knowledge_grounded=result.knowledge_grounded,
        message_metadata=_tool_snapshot_metadata(result),
    )
    generation_step.status = "succeeded"
    for offset, tool_event in enumerate(result.tool_events or [], start=2):
        if str(tool_event.get("tool_call_id", tool_event["tool"])) in tool_steps:
            continue
        tool_step = await repo.create_loop_step(
            loop.id, **tool_step_values(tool_event, offset)
        )
        await repo.save_loop(loop)
        yield {
            "type": "agent_step_completed",
            "conversation": conversation,
            "assistant": assistant,
            "loop_id": loop.id,
            "step_id": tool_step.id,
            "payload": build_step_payload(
                tool_step, loop_run_id=loop.id, with_output=True, with_tool=True
            ),
        }
    generation_step.sequence = next_step_sequence
    generation_step.output_summary = f"生成 {len(result.content)} 字符"
    generation_step.thinking_text = result.thinking_text
    loop.assistant_message_id = assistant.id
    loop.status = "completed"
    loop.summary = "已完成回答"
    await repo.save_loop(loop)
    result.loop_id = loop.id
    yield {
        "type": "agent_step_completed",
        "conversation": conversation,
        "assistant": assistant,
        "loop_id": loop.id,
        "step_id": generation_step.id,
        "payload": build_step_payload(
            generation_step,
            loop_run_id=loop.id,
            sequence=2,
            with_output=True,
            with_thinking=True,
        ),
    }
    yield {
        "type": "agent_loop_completed",
        "conversation": conversation,
        "assistant": assistant,
        "loop_id": loop.id,
        "payload": {
            "loopRunId": str(loop.id),
            "status": loop.status,
            "summary": loop.summary,
        },
    }
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
        matches = await knowledge_repo.search(
            base, embedding, limit=int(getattr(base, "retrieval_top_k", 5))
        )
        logger.info(
            "Knowledge search completed base_id=%s matches=%s active_index_version=%s",
            getattr(base, "id", None),
            len(matches),
            getattr(base, "active_index_version", None),
        )
        accepted = [
            (chunk, similarity, base)
            for chunk, similarity in matches
            if similarity >= float(getattr(base, "retrieval_threshold", 0.5))
        ][: int(getattr(base, "retrieval_top_k", 5))]
        chunks.extend(accepted)
        logger.info(
            "Knowledge threshold applied base_id=%s threshold=%s accepted=%s",
            getattr(base, "id", None),
            getattr(base, "retrieval_threshold", 0.5),
            len(accepted),
        )
    chunks.sort(key=lambda item: item[1], reverse=True)
    deduped = []
    seen = set()
    total_chars = 0
    max_context_chars = get_settings().knowledge_context_max_chars
    for chunk, similarity, base in chunks:
        key = (chunk.document_id, chunk.content.strip())
        if key in seen:
            continue
        remaining = max_context_chars - total_chars
        if remaining <= 0:
            break
        text = chunk.content[:remaining]
        if not text.strip():
            continue
        seen.add(key)
        total_chars += len(text)
        deduped.append((chunk, similarity, text, base))
    citations = build_citations(
        [
            {
                "title": chunk.source_metadata.get("title", ""),
                "source_url": chunk.source_metadata.get("source_url"),
                "content": text,
                "knowledge_base": (
                    {
                        "id": getattr(base, "id", None),
                        "name": getattr(base, "name", None),
                        "slug": getattr(base, "slug", None),
                    }
                    if getattr(base, "id", None) is not None
                    else None
                ),
            }
            for chunk, _similarity, text, base in deduped
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
    conversation = await _resolve_conversation(
        repo,
        context,
        platform_id=platform_id,
        user_id=user_id,
        message=message,
        conversation_id=conversation_id,
    )
    history = await load_recent_history(repo, conversation.id)
    user_message = await repo.create_message(
        conversation.id,
        role="user",
        content=message,
        citations=[],
        knowledge_grounded=False,
    )
    loop, _retrieval_step, skill_steps = await _start_loop(
        repo,
        conversation,
        user_message,
        f"conversation-{conversation.id}",
        citations,
        context.skill_usages,
    )
    result = await run_graph(
        model,
        system_prompt=build_system_prompt(
            context.version, context.skill_instructions, citations
        ),
        user_message=message,
        history=history,
        citations=citations,
        tools=[
            *_rest_runtime_tools(*context.builtin_tools),
            *context.mcp_tools,
            *context.skill_script_tools,
            *(
                [context.skill_instruction_tool]
                if context.skill_instruction_tool
                else []
            ),
        ],
        invoke_tool_fn=invoke_tool_fn,
        context_window_tokens=resolve_context_window_tokens(context.version),
    )
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        content_blocks=_content_blocks(result.content, result.content_blocks),
        citations=result.citations,
        knowledge_grounded=result.knowledge_grounded,
        message_metadata=_tool_snapshot_metadata(result),
    )
    tool_start = 2 + len(skill_steps)
    for offset, tool_event in enumerate(result.tool_events or [], start=tool_start):
        await repo.create_loop_step(loop.id, **tool_step_values(tool_event, offset))
    await repo.create_loop_step(
        loop.id,
        sequence=tool_start + len(result.tool_events or []),
        step_type="model_generation",
        title="生成回答",
        status="succeeded",
        output_summary=f"生成 {len(result.content)} 字符",
        thinking_text=result.thinking_text,
    )
    loop.assistant_message_id = assistant.id
    loop.status = "completed"
    loop.summary = "已完成回答"
    await repo.save_loop(loop)
    result.loop_id = loop.id
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
    invoke_tool_fn=None,
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
    context.conversation_id = conversation.id
    history = await load_recent_history(repo, conversation.id)
    user_message = await repo.create_message(
        conversation.id,
        role="user",
        content=message,
        citations=[],
        knowledge_grounded=False,
    )
    loop, retrieval_step, skill_steps = await _start_loop(
        repo,
        conversation,
        user_message,
        f"conversation-{conversation.id}",
        citations,
        context.skill_usages,
    )
    yield {
        "type": "agent_loop_started",
        "conversation": conversation,
        "loop_id": loop.id,
        "payload": {
            "loopRunId": str(loop.id),
            "status": loop.status,
            "summary": loop.summary,
        },
    }
    yield {
        "type": "agent_step_completed",
        "conversation": conversation,
        "loop_id": loop.id,
        "step_id": retrieval_step.id,
        "payload": build_step_payload(
            retrieval_step,
            loop_run_id=loop.id,
            sequence=1,
            citation_refs=citations,
            with_output=True,
        ),
    }
    for skill_step in skill_steps:
        yield {
            "type": "agent_step_completed",
            "conversation": conversation,
            "loop_id": loop.id,
            "step_id": skill_step.id,
            "payload": build_step_payload(
                skill_step, loop_run_id=loop.id, with_output=True, with_skill=True
            ),
        }
    generation_sequence = 2 + len(skill_steps)
    generation_step = await repo.create_loop_step(
        loop.id,
        sequence=generation_sequence,
        step_type="model_generation",
        title="生成回答",
        status="running",
    )
    await repo.save_loop(loop)
    yield {
        "type": "agent_step_started",
        "conversation": conversation,
        "loop_id": loop.id,
        "step_id": generation_step.id,
        "payload": build_step_payload(generation_step, loop_run_id=loop.id),
    }
    tool_steps = {}
    next_step_sequence = generation_sequence + 1
    async for item in stream_graph(
        model,
        system_prompt=build_system_prompt(
            context.version, context.skill_instructions, citations
        ),
        user_message=message,
        history=history,
        citations=citations,
        tools=[
            *_rest_runtime_tools(*context.builtin_tools),
            *context.mcp_tools,
            *context.skill_script_tools,
            *(
                [context.skill_instruction_tool]
                if context.skill_instruction_tool
                else []
            ),
        ],
        invoke_tool_fn=invoke_tool_fn,
        context_window_tokens=resolve_context_window_tokens(context.version),
    ):
        if item["type"] == "message_delta":
            yield {"type": "message_delta", "conversation": conversation, **item}
            continue
        if item["type"] == "thinking_delta":
            yield {
                "type": "agent_step_delta",
                "conversation": conversation,
                "loop_id": loop.id,
                "step_id": generation_step.id,
                "payload": {
                    "loopRunId": str(loop.id),
                    "stepId": str(generation_step.id),
                    "sequence": generation_step.sequence,
                    "stepType": "model_generation",
                    "field": "thinking",
                    "content": item["content"],
                },
            }
            continue
        if item["type"] == "tool_started":
            call_id = str(item["tool_call_id"])
            tool_step = await repo.create_loop_step(
                loop.id,
                sequence=next_step_sequence,
                step_type=item["tool_type"],
                title=f"调用工具：{item['tool']}",
                status=item.get("waiting_status") or "running",
                input_summary=item.get("input_summary"),
                tool_name=item["tool"],
                tool_call_id=call_id,
                skill_name=item.get("skill_name"),
                skill_version=item.get("skill_version"),
            )
            next_step_sequence += 1
            tool_steps[call_id] = tool_step
            await repo.save_loop(loop)
            yield {
                "type": "agent_step_started",
                "conversation": conversation,
                "loop_id": loop.id,
                "step_id": tool_step.id,
                "payload": build_step_payload(
                    tool_step,
                    loop_run_id=loop.id,
                    with_tool=True,
                    with_skill=True,
                ),
            }
            yield {
                "type": "tool_call",
                "conversation": conversation,
                "payload": {"tool": item["tool"], "toolCallId": call_id},
            }
            continue
        if item["type"] == "tool_completed":
            call_id = str(item["tool_call_id"])
            tool_step = tool_steps.get(call_id)
            if tool_step is not None:
                values = tool_step_values(item, tool_step.sequence)
                tool_step.status = values["status"]
                tool_step.output_summary = values["output_summary"]
                tool_step.error = values["error"]
                await repo.save_loop(loop)
                yield {
                    "type": "agent_step_completed",
                    "conversation": conversation,
                    "loop_id": loop.id,
                    "step_id": tool_step.id,
                    "payload": build_step_payload(
                        tool_step,
                        loop_run_id=loop.id,
                        with_output=True,
                        with_tool=True,
                        with_skill=True,
                    ),
                }
            outcome = item["outcome"]
            yield {
                "type": (
                    "confirmation_required"
                    if outcome.status == "confirmation_required"
                    else "tool_result"
                ),
                "conversation": conversation,
                "payload": outcome.model_dump(),
            }
            continue
        if item["type"] == "error":
            generation_step.status = "failed"
            generation_step.output_summary = "模型生成失败"
            generation_step.error = item["payload"]
            loop.status = "failed"
            loop.summary = item["payload"]["message"]
            await repo.save_loop(loop)
            yield {
                "type": "error",
                "conversation": conversation,
                "loop_id": loop.id,
                "request_id": loop.request_id,
                "payload": item["payload"],
            }
            return
        result = item["result"]
        async for event in _finish_stream_chat(
            repo,
            conversation,
            loop,
            generation_step,
            tool_steps=tool_steps,
            next_step_sequence=next_step_sequence,
            result=result,
        ):
            yield event
