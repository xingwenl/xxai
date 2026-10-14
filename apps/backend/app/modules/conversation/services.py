from datetime import datetime, time, timedelta, timezone

from app.core.logging import get_logger
from app.core.config import get_settings
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    attach_tool_snapshots,
    build_agent_error_payload,
    build_tool_snapshots,
    build_system_prompt,
    build_step_payload,
    apply_runtime_context_guardrail,
    make_context_degrade_recoverer,
    resolve_context_window_tokens,
    custom_content_blocks,
    image_content_blocks,
    rewrite_image_markdown,
    tool_step_values,
    GraphResult,
    load_runtime_context,
)
from app.modules.knowledge.runtime import build_embedding_model
from app.modules.knowledge.services import build_citations, validate_embedding_dimension
from app.modules.conversation.schemas import sanitize_content_blocks
from app.modules.conversation.serializers import (
    build_message_snapshots,
    conversation_preview,
)
from app.modules.agent_runtime.event_adapters import event_to_legacy
from app.modules.agent_runtime.langchain_adapter import build_langchain_messages
from app.modules.agent_runtime.conversation_adapter import stream_runtime_as_conversation
from app.modules.agent_runtime.lifecycle import (
    generation_step_status_for,
    loop_status_for,
    loop_summary_for,
    resolve_result_run_status,
)
from app.modules.agent_runtime.composition import (
    build_langchain_runtime,
    build_runtime_tools,
)
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
    return build_runtime_tools(
        builtin_tools=builtin_tools,
        exclude_names={"ask_user"},
    )


def build_runtime_tool_list(context) -> list:
    """组装一次运行里 Agent 可见的完整工具清单。

    清单构成只在这里定义：内置工具（REST 路径排除 ask_user）、MCP 工具、
    技能脚本工具、技能指令工具。抽成函数是因为工作流的「工具步骤」也要按
    **同一份清单**去找工具对象——复制一份的话，两边的工具支持范围迟早漂移
    （新增一类工具只改了其中一处），这正是 ``tool_dispatch`` 当初被抽出来的
    同一个理由。
    """

    return [
        *_rest_runtime_tools(*context.builtin_tools),
        *context.mcp_tools,
        *context.skill_script_tools,
        *([context.skill_instruction_tool] if context.skill_instruction_tool else []),
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
    user_id: int | None,
    message: str,
    conversation_id: int | None,
    end_user_id: int | None = None,
):
    """定位或新建会话。

    会话的 principal 恰有一个：后台用户（``user_id``）或 Embed 终端用户
    （``end_user_id``），与 ``conversations`` 表的约束一致。两者都为空
    时无法建会话，直接报错而不是写入一条无归属的会话。
    """

    if user_id is None and end_user_id is None:
        raise NotFoundException("conversation principal is required")
    conversation = None
    if conversation_id is not None:
        conversation = await repo.get_for_principal(
            conversation_id, platform_id, user_id=user_id, end_user_id=end_user_id
        )
        if conversation is None or conversation.agent_id != context.agent.id:
            raise NotFoundException("conversation not found")
    if conversation is None:
        conversation = await repo.create_for_principal(
            platform_id,
            context.agent.id,
            user_id=user_id,
            end_user_id=end_user_id,
            title=message,
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
    result_status = resolve_result_run_status(
        pending_confirmation_id=getattr(result, "pending_confirmation_id", None),
        budget_exceeded=bool(getattr(result, "budget_exceeded", False)),
        error=getattr(result, "error", None),
    )
    generation_step.status = generation_step_status_for(result_status)
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
    loop.status = loop_status_for(result_status)
    loop.summary = loop_summary_for(result_status)
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


async def _run_execute_chat_model_round(
    *,
    model,
    runtime_tools: list,
    invoke_tool_fn,
    context,
    history,
    message: str,
    citations: list[dict],
    request_id: str,
) -> GraphResult:
    """执行 REST 非流式对话的模型轮次（统一 AgentRuntime）。

    AgentLoop 是唯一主循环实现：这里只负责按上下文组装 LangChain 消息、
    构建 runtime（含上下文护栏与 context-length 降级恢复），并把统一结果
    收敛为 REST 的 GraphResult，供 execute_chat 统一失败收尾。
    """

    system_prompt = build_system_prompt(
        context.version, context.skill_instructions, citations
    )
    runtime = build_langchain_runtime(
        model,
        runtime_tools,
        invoke_tool_fn,
        streaming=False,
        context_transform=lambda messages: apply_runtime_context_guardrail(
            messages,
            window_tokens=resolve_context_window_tokens(context.version),
        ),
        max_turns=get_settings().agent_max_iterations,
        on_model_error=make_context_degrade_recoverer(system_prompt, message),
    )
    messages = build_langchain_messages(
        system_prompt=system_prompt,
        history=history,
        user_message=message,
    )
    runtime_result = await runtime.run(messages, request_id=request_id)
    runtime_tool_events = runtime_result.tool_events or []
    # runtime 结果只提供纯文本与工具事件；图片 URL 改写与内容块必须与收尾
    # 保持同一口径，否则 ChatResponse.content_blocks 和 assistant 消息内容
    # 会与既有 REST 行为不一致。
    return GraphResult(
        content=rewrite_image_markdown(
            runtime_result.content, runtime_tool_events
        ),
        citations=runtime_result.citations or citations,
        knowledge_grounded=bool(runtime_result.citations or citations),
        tool_events=runtime_result.tool_events,
        usage=runtime_result.usage,
        pending_confirmation_id=runtime_result.pending_confirmation_id,
        thinking_text=runtime_result.thinking_text or "",
        content_blocks=[
            *image_content_blocks(runtime_tool_events),
            *custom_content_blocks(runtime_tool_events),
        ],
    )


async def execute_chat(
    repo: ConversationRepository,
    context,
    *,
    platform_id: int,
    user_id: int | None,
    message: str,
    conversation_id: int | None,
    model,
    citations: list[dict],
    invoke_tool_fn=None,
    end_user_id: int | None = None,
):
    logger.info(
        "Conversation chat started platform_id=%s user_id=%s end_user_id=%s agent_id=%s conversation_id=%s message_chars=%s citation_count=%s",
        platform_id,
        user_id,
        end_user_id,
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
        end_user_id=end_user_id,
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
    runtime_tools = build_runtime_tool_list(context)
    try:
        result = await _run_execute_chat_model_round(
            model=model,
            runtime_tools=runtime_tools,
            invoke_tool_fn=invoke_tool_fn,
            context=context,
            history=history,
            message=message,
            citations=citations,
            request_id=loop.request_id,
        )
    except Exception as error:
        # REST 非流式与流式入口共用同一错误语义：模型失败不能把 loop 留在
        # running 假象里。这里补写一条 failed 的生成步骤并把 loop 更新为
        # failed 后继续上抛原异常，保持 REST 公开错误响应与 legacy 一致；
        # CancelledError 属 BaseException，不会被本分支吞掉。
        error_payload = build_agent_error_payload(error)
        await repo.create_loop_step(
            loop.id,
            sequence=2 + len(skill_steps),
            step_type="model_generation",
            title="生成回答",
            status="failed",
            output_summary="模型生成失败",
            error=error_payload,
        )
        loop.status = "failed"
        loop.summary = error_payload["message"]
        await repo.save_loop(loop)
        raise
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
    # 同一结果只解析一次请求终态，后续生成步骤/loop 落库字段统一经
    # lifecycle 助手推导，避免三个收尾站点各自维护口径。
    result_status = resolve_result_run_status(
        pending_confirmation_id=getattr(result, "pending_confirmation_id", None),
        budget_exceeded=bool(getattr(result, "budget_exceeded", False)),
        error=getattr(result, "error", None),
    )
    await repo.create_loop_step(
        loop.id,
        sequence=tool_start + len(result.tool_events or []),
        step_type="model_generation",
        title="生成回答",
        status=generation_step_status_for(result_status),
        output_summary=f"生成 {len(result.content)} 字符",
        thinking_text=result.thinking_text,
    )
    loop.assistant_message_id = assistant.id
    loop.status = loop_status_for(result_status)
    loop.summary = loop_summary_for(result_status)
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
    on_model_task_started=None,
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
    runtime_tools = build_runtime_tool_list(context)
    system_prompt = build_system_prompt(
        context.version, context.skill_instructions, citations
    )
    runtime = build_langchain_runtime(
        model,
        runtime_tools,
        invoke_tool_fn,
        streaming=True,
        context_transform=lambda messages: apply_runtime_context_guardrail(
            messages,
            window_tokens=resolve_context_window_tokens(context.version),
        ),
        max_turns=get_settings().agent_max_iterations,
        on_model_error=make_context_degrade_recoverer(system_prompt, message),
        on_task_started=on_model_task_started,
    )
    event_stream = stream_runtime_as_conversation(
        runtime.stream(
            build_langchain_messages(
                system_prompt=system_prompt,
                history=history,
                user_message=message,
            ),
            request_id=loop.request_id,
        )
    )

    async for agent_event in event_stream:
        # REST SSE 与 WebSocket 共用统一内部事件 seam；这里保留旧字段出口，
        # 让后续的消息持久化和 SSE 组装可以渐进迁移而不改变公开响应格式。
        item = (
            agent_event
            if isinstance(agent_event, dict)
            else event_to_legacy(agent_event)
        )
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
            if str(outcome.status) == "confirmation_required":
                # legacy stream_graph 在确认等待时会把 GraphResult 终态交给
                # 收尾逻辑；AgentRuntime 等待态不再调用模型，事件流也自然
                # 结束，这里补一次等效收尾，避免 loop/step 永远停在 running。
                wait_result = GraphResult(
                    content="",
                    citations=citations,
                    knowledge_grounded=bool(citations),
                    pending_confirmation_id=getattr(
                        outcome, "confirmation_id", None
                    ),
                    tool_events=[
                        {
                            "tool_call_id": item.get("tool_call_id"),
                            "tool": item.get("tool"),
                            "tool_type": item.get("tool_type"),
                            "arguments": item.get("arguments"),
                            "outcome": outcome,
                        }
                    ],
                    usage=None,
                    thinking_text="",
                    loop_id=loop.id,
                )
                async for event in _finish_stream_chat(
                    repo,
                    conversation,
                    loop,
                    generation_step,
                    tool_steps=tool_steps,
                    next_step_sequence=next_step_sequence,
                    result=wait_result,
                ):
                    yield event
                return
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
        # Bridge 已提供统一 AgentResult；旧 GraphResult 作为 fallback，确保
        # 灰度期间不同事件来源仍能完成同一套消息与 loop 收尾。
        result = item.get("agent_result") or item.get("result")
        if result is None and item["type"] == "completed":
            payload = item.get("payload", {})
            payload_tool_events = payload.get("tool_events", [])
            result = GraphResult(
                # legacy 流式 Graph 在收尾时已按工具结果改写图片 URL；runtime
                # 事件只有纯文本，这里补一次相同改写，避免灰度流输出差异。
                content=rewrite_image_markdown(
                    payload.get("content", ""), payload_tool_events
                ),
                citations=citations,
                knowledge_grounded=bool(citations),
                tool_events=payload_tool_events,
                usage=payload.get("usage"),
                pending_confirmation_id=payload.get("pending_confirmation_id"),
                thinking_text=payload.get("thinking_text", "") or "",
                loop_id=loop.id,
            )
        if result is None:
            continue
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


async def execute_unattended_chat(
    session,
    *,
    platform_id: int,
    agent_id: int,
    message: str,
    run_as_type: str = "user",
    user_id: int | None = None,
    end_user_id: int | None = None,
    model_id: int | None = None,
    confirmation_decider=None,
    tool_session=None,
):
    """无人值守执行一轮 Agent 对话（非 HTTP 入口）。

    这是给任务调度用的系统入口：它把「HTTP 层原来替调用方做掉的那些装配」
    收拢到一处，避免任务模块自己去拼运行时上下文、检索引用与模型客户端——
    那些装配一旦在两边各写一份，行为漂移很难被发现。

    与 REST 链路的差异只有两点，都是无人值守场景的必然要求：
    1. 执行身份由调用方显式给定，不来自 token；后台任务传 ``user_id``，
       Embed 链路创建的任务传 ``end_user_id``；
    2. 需要确认的工具调用由 ``confirmation_decider`` 当场裁决，
       而不是挂起等待一个不会到来的用户回复。

    每轮都新建会话（``conversation_id=None``），因此一次任务运行对应一个
    独立会话，执行记录可以精确回溯到它。返回
    ``(conversation, assistant_message, GraphResult)``。
    """

    from app.modules.agent.repositories import AgentRepository
    from app.modules.agent.services import build_chat_model
    from app.modules.builtin_tool.repositories import BuiltinToolRepository
    from app.modules.conversation.tool_dispatch import build_tool_invoker
    from app.modules.knowledge.repositories import KnowledgeRepository
    from app.modules.mcp.repositories import McpRepository
    from app.modules.skill.repositories import SkillRepository

    # 执行身份二选一，与会话的 principal 约束保持一致。
    if run_as_type == "user":
        end_user_id = None
    elif run_as_type == "end_user":
        user_id = None
    else:
        raise NotFoundException(f"unsupported run_as_type: {run_as_type}")
    if user_id is None and end_user_id is None:
        raise NotFoundException("unattended run requires an execution identity")

    tool_session = tool_session if tool_session is not None else session
    agent_repo = AgentRepository(session)
    # 平台作用域查询：确保任务用的智能体确实属于该平台且已发布。
    agent = await agent_repo.get_published_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("published agent not found")

    context = await load_runtime_context(
        agent_repo,
        KnowledgeRepository(session),
        SkillRepository(session),
        McpRepository(session),
        BuiltinToolRepository(session),
        agent_id=agent_id,
        platform_id=platform_id,
    )
    citations = await retrieve_citations(
        KnowledgeRepository(session), context.knowledge_bases, message
    )

    invoke = build_tool_invoker(
        platform_id=platform_id,
        agent_id=agent_id,
        builtin_repo=BuiltinToolRepository(tool_session),
        skill_repo=SkillRepository(tool_session),
        mcp_repo=McpRepository(tool_session),
        tool_session=tool_session,
        user_id=user_id,
        platform_end_user_id=end_user_id,
        conversation_id_provider=lambda: getattr(context, "conversation_id", None),
        confirmation_decider=confirmation_decider,
    )

    model = build_chat_model(
        context.version,
        session_id_provider=lambda: getattr(context, "conversation_id", None),
    )
    if model_id is not None:
        # 任务可覆盖智能体默认模型；解析不到就沿用智能体自身配置，
        # 不因为一个失效的模型 ID 把整轮运行打断。
        override = await _resolve_task_model(session, platform_id, model_id)
        if override is not None and override.model_name:
            model.model_name = override.model_name
            if override.base_url:
                model.openai_api_base = override.base_url

    return await execute_chat(
        ConversationRepository(session),
        context,
        platform_id=platform_id,
        user_id=user_id,
        end_user_id=end_user_id,
        message=message,
        # 每轮新建会话：不传 conversation_id 即自动创建。
        conversation_id=None,
        model=model,
        citations=[citation.model_dump() for citation in citations],
        invoke_tool_fn=invoke,
    )


async def _resolve_task_model(session, platform_id: int, model_id: int):
    """解析任务指定的平台模型；不存在或不属于该平台时返回 None。"""

    from app.modules.model_registry.repositories import ModelRegistryRepository

    return await ModelRegistryRepository(session).get_for_platform(
        model_id, platform_id
    )


# ---------------------------------------------------------------------------
# 后台会话记录（平台级只读视图）
#
# 与 embed 侧的区别只有两点：隔离条件从「会话主体」放宽到「平台」（管理员有权
# 查阅本平台全部主体的会话），以及消息投影与 embed 共用同一份实现。所有函数都
# 要求调用方已完成平台管理员校验（见 admin_router），这里不再重复鉴权。
# ---------------------------------------------------------------------------


def _console_time_range(start_date, end_date) -> tuple[datetime | None, datetime | None]:
    """把日期区间转成半开区间 `[start_at, end_at)`，与用量统计口径一致。

    用「次日零点」而非「当日 23:59:59」作为上界，避免毫秒级尾巴漏掉当天最后
    一刻产生的会话。
    """
    start_at = datetime.combine(start_date, time.min) if start_date is not None else None
    end_at = (
        datetime.combine(end_date + timedelta(days=1), time.min)
        if end_date is not None
        else None
    )
    return start_at, end_at


def _console_conversation_payload(row) -> dict:
    """会话行 → 后台接口响应体。

    末条消息摘要复用 serializers 里的单行化处理，使后台列表的预览与 embed
    会话列表的预览口径一致（都是压成一行、超长截断）。
    """
    conversation = row.conversation
    return {
        "id": conversation.id,
        "platform_id": conversation.platform_id,
        "agent_id": conversation.agent_id,
        "agent_name": row.agent_name,
        "principal_type": row.principal_type,
        "principal_id": row.principal_id,
        "principal_name": row.principal_name,
        "title": conversation.title,
        "status": conversation.status,
        "message_count": row.message_count,
        "last_message_preview": conversation_preview(row.last_message_preview),
        "last_message_at": row.last_message_at,
        "created_at": conversation.created_at,
    }


def _console_usage_payload(usage: tuple[int, int, int, int]) -> dict:
    """会话级用量汇总；计费口径与 /model-usage 页保持一致（同源表）。"""
    prompt_tokens, completion_tokens, total_tokens, record_count = usage
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "record_count": record_count,
    }


async def list_console_conversation_principals(
    session,
    platform_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    principal_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> dict:
    """第一层：本平台内「有会话」的会话主体分页列表。"""
    repo = ConversationRepository(session)
    rows = await repo.list_principals_for_platform(
        platform_id,
        page=page,
        page_size=page_size,
        principal_type=principal_type,
        keyword=keyword,
        status=status,
        include_deleted=include_deleted,
    )
    total = await repo.count_principals_for_platform(
        platform_id,
        principal_type=principal_type,
        keyword=keyword,
        status=status,
        include_deleted=include_deleted,
    )
    return {
        "items": [
            {
                "principal_type": row.principal_type,
                "principal_id": row.principal_id,
                "display_name": row.display_name,
                "conversation_count": row.conversation_count,
                "last_conversation_at": row.last_conversation_at,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def list_console_conversations(
    session,
    platform_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    agent_id: int | None = None,
    principal_type: str | None = None,
    principal_id: int | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    start_date=None,
    end_date=None,
    keyword: str | None = None,
) -> dict:
    """第二层：平台内会话分页列表；默认排除软删除。"""
    start_at, end_at = _console_time_range(start_date, end_date)
    filters = {
        "agent_id": agent_id,
        "principal_type": principal_type,
        "principal_id": principal_id,
        "status": status,
        "include_deleted": include_deleted,
        "start_at": start_at,
        "end_at": end_at,
        "keyword": keyword,
    }
    repo = ConversationRepository(session)
    rows = await repo.list_for_platform(
        platform_id, page=page, page_size=page_size, **filters
    )
    total = await repo.count_for_platform(platform_id, **filters)
    return {
        "items": [_console_conversation_payload(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_console_conversation(session, platform_id: int, conversation_id: int) -> dict:
    """第二层详情：单个会话 + 会话级用量汇总。

    这里刻意包含已软删除的会话：删掉只是从默认列表隐藏，管理员仍能打开查看
    历史消息与计费记录（见验收标准 4）。
    """
    repo = ConversationRepository(session)
    row = await repo.get_for_platform(
        conversation_id, platform_id, include_deleted=True
    )
    if row is None:
        raise NotFoundException("conversation not found")
    payload = _console_conversation_payload(row)
    payload["usage"] = _console_usage_payload(
        await repo.usage_for_conversation(conversation_id)
    )
    return payload


async def list_console_conversation_messages(
    session, platform_id: int, conversation_id: int
) -> list[dict]:
    """第三层：会话消息时间线（含每轮 Agent Loop 步骤）。

    投影与 embed 的 `GET /embed/conversations/{id}/messages` 共用
    `build_message_snapshots`，因此同一份数据下两者逐字段相同。
    """
    repo = ConversationRepository(session)
    row = await repo.get_for_platform(
        conversation_id, platform_id, include_deleted=True
    )
    if row is None:
        raise NotFoundException("conversation not found")
    messages = await repo.list_messages(conversation_id)
    return await build_message_snapshots(
        repo, conversation_id=conversation_id, messages=messages
    )


async def delete_console_conversation(
    session, platform_id: int, conversation_id: int
) -> None:
    """软删除会话：非本平台或已删除一律按 404 处理，不泄露存在性。"""
    repo = ConversationRepository(session)
    deleted = await repo.soft_delete_for_platform(conversation_id, platform_id)
    if not deleted:
        raise NotFoundException("conversation not found")
