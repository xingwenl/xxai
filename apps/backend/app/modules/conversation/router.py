import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session, get_session_factory
from app.core.security import (
    require_current_active_user,
    require_current_active_user_or_wechat_service,
)
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import build_chat_model
from app.modules.conversation.approval import (
    SOURCE_BUILTIN,
    SOURCE_MCP,
    InteractiveConfirmationDecider,
)
from app.modules.conversation.repositories import (
    AgentLoopRunCheckpointRepository,
    ConversationRepository,
)
from app.modules.conversation.schemas import (
    ChatRequest,
    ChatResponse,
    RunResolveRequest,
)
from app.modules.conversation.services import (
    build_loop_payload,
    execute_chat,
    resume_stream_chat,
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
from app.modules.mcp.runtime import RepositoryMcpExecutor
from app.modules.mcp.services import resolve_tool_confirmation
from app.modules.skill.repositories import SkillRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.asset.repositories import AssetRepository
from app.modules.tool_approval.contracts import ConfirmationDecision
from app.modules.tool_approval.repositories import ToolConfirmationRepository
from app.modules.tool_approval.services import ToolApprovalService
from app.modules.agent_runtime.adapters import (
    agent_result_from_legacy,
    tool_outcome_from_legacy,
)
from app.modules.agent_runtime.contracts import ToolOutcome
from app.modules.agent_runtime.error_codes import ErrorCode
from app.modules.agent_runtime.runtime import cancel_and_join_tasks
from app.shared.exceptions import ConflictException, NotFoundException
from app.shared.responses import success_response

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

router = APIRouter(prefix="/agents", tags=["conversation"])


async def _always_approve(tool, call) -> ConfirmationDecision:
    """续跑时的裁决器：确认已经由用户表态过，本次直接执行。

    确认记录的状态与「用户是否同意」在解决端点里已经落定，这里只是把
    「已批准」这个事实告诉比较底层的那道闸口，避免二次弹窗。
    """

    return ConfirmationDecision(
        approved=True, reason="resumed_after_user_approval"
    )


async def _prepare(
    agent_id: int,
    payload: ChatRequest,
    current_user,
    session: AsyncSession,
    tool_session: AsyncSession | None = None,
    stream: bool = False,
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
    #
    # 流式对话（SSE）没有连接级等待通道，因此注入「落库 + 挂起」型裁决器：写工具
    # 在参数校验之后被挂起成 confirmation_required，由解决端点续跑。非流式通路
    # （含微信助手）不注入裁决器，写工具仍按「无确认通道」被拒绝。
    confirmation_decider = None
    if stream:
        confirmation_decider = InteractiveConfirmationDecider(
            session=tool_session,
            platform_id=agent.platform_id,
            agent_id=agent_id,
            conversation_id_provider=lambda: getattr(context, "conversation_id", None),
            user_id=current_user.id,
        )

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
        confirmation_decider=confirmation_decider,
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
                stream=True,
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

    return _sse_response(_events_impl)


def _sse_response(impl) -> StreamingResponse:
    """SSE 出口，负责工具 Session 与模型 Task 的生命周期收口。

    客户端断开或生成器被提前关闭时，内层模型 Task 可能仍在写库；必须先
    取消并等它收尾，再退出 `async with` 关闭工具 Session，否则会出现
    close() 与 commit() 相撞的 SQLAlchemy 状态错误。

    `impl(tool_session, model_tasks)` 是具体的 SSE 生成器：首答（chat）与
    确认后续跑（resolve）各一个，但生命周期收口只有这一份。
    """

    async def events() -> AsyncIterator[str]:
        model_tasks: set[asyncio.Task] = set()
        async with get_session_factory()() as tool_session:
            try:
                async for chunk in impl(tool_session, model_tasks):
                    yield chunk
            finally:
                await cancel_and_join_tasks(model_tasks)

    return StreamingResponse(events(), media_type="text/event-stream")


@dataclass
class _ResumePlan:
    """一次「解决确认并续跑」所需的全部材料。

    流前校验（归属、状态、过期、CAS、工具执行）在端点里同步做完，拿到这个
    计划后才开始推流，这样 404/409 能以普通 REST 错误返回，而不是变成流里
    的一条 error 事件。
    """

    agent: object
    context: object
    conversation: object
    loop: object
    checkpoint: object
    outcome: ToolOutcome
    citations: list
    resolved: object


async def _execute_pending_tool(
    session: AsyncSession,
    *,
    checkpoint,
    approved: bool,
    agent,
    current_user,
    conversation,
    loop,
) -> ToolOutcome:
    """执行那个被挂起的工具，并把结果归一成 AgentRuntime 契约。

    `approved=false` 也返回一个 ToolOutcome（status=rejected）：运行要继续，
    模型必须看到「用户拒绝了」这个工具结果才能换方案。
    """
    if checkpoint.confirmation_source == SOURCE_MCP:
        mcp_repo = McpRepository(session)
        raw = await resolve_tool_confirmation(
            mcp_repo,
            RepositoryMcpExecutor(mcp_repo),
            confirmation_id=checkpoint.confirmation_id,
            platform_id=agent.platform_id,
            approved=approved,
            user_id=current_user.id,
        )
        outcome = tool_outcome_from_legacy(raw)
        # 恢复原调用的 call_id，模型侧的 tool_call/tool_result 才能配上对。
        outcome.call_id = checkpoint.tool_call_id
        return outcome

    if checkpoint.confirmation_source != SOURCE_BUILTIN:
        raise ConflictException(
            "run confirmation is not resumable",
            error_code=ErrorCode.RUN_RESUME_UNAVAILABLE,
        )
    confirmation = await ToolConfirmationRepository(session).get(
        checkpoint.confirmation_id
    )
    if confirmation is None or confirmation.tool_name != checkpoint.tool_name:
        # 确认记录缺失（被清理等）：不能假装用户批准过，交给调用方回 409。
        raise ConflictException(
            "run confirmation is no longer available",
            error_code=ErrorCode.RUN_RESUME_UNAVAILABLE,
        )
    approval = ToolApprovalService(session)
    if not approved:
        await approval.resolve(
            confirmation_id=checkpoint.confirmation_id,
            approved=False,
            actor="user",
        )
        return ToolOutcome(
            status="rejected",
            result={
                "status": "rejected",
                "auto_approved": False,
                "message": "用户拒绝执行该工具，请勿自动重试",
            },
            call_id=checkpoint.tool_call_id,
        )
    await approval.resolve(
        confirmation_id=checkpoint.confirmation_id, approved=True, actor="user"
    )
    raw = await invoke_builtin_tool(
        BuiltinToolRepository(session),
        AssetRepository(session),
        tool=SimpleNamespace(name=checkpoint.tool_name),
        call={
            "id": checkpoint.tool_call_id,
            "args": dict(confirmation.arguments or {}),
        },
        platform_id=agent.platform_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        user_id=current_user.id,
        session=session,
        loop_run_id=loop.id,
        # 用户已经表过态，闸口直接放行，不再二次弹窗。
        confirmation_decider=_always_approve,
    )
    outcome = tool_outcome_from_legacy(raw)
    outcome.call_id = checkpoint.tool_call_id
    return outcome


async def _prepare_resume(
    agent_id: int,
    loop_run_id: int,
    payload: RunResolveRequest,
    current_user,
    session: AsyncSession,
) -> _ResumePlan:
    """流前校验 + 执行挂起的工具，返回续跑计划。"""
    agent_repo = AgentRepository(session)
    agent = await agent_repo.get_published_agent_for_user(agent_id, current_user.id)
    if agent is None:
        raise NotFoundException("published agent not found")

    repo = ConversationRepository(session)
    checkpoint_repo = AgentLoopRunCheckpointRepository(session)
    checkpoint = await checkpoint_repo.get_by_loop_run(loop_run_id)
    # 归属不符与不存在返回同一个 404：不泄露「这次运行存在但不属于你」。
    if (
        checkpoint is None
        or checkpoint.agent_id != agent_id
        or checkpoint.platform_id != agent.platform_id
        or checkpoint.user_id != current_user.id
    ):
        raise NotFoundException(
            "run confirmation not found",
            error_code=ErrorCode.RUN_CONFIRMATION_NOT_FOUND,
        )
    conversation = await repo.get(
        checkpoint.conversation_id, agent.platform_id, current_user.id
    )
    if conversation is None or conversation.agent_id != agent_id:
        raise NotFoundException(
            "run confirmation not found",
            error_code=ErrorCode.RUN_CONFIRMATION_NOT_FOUND,
        )
    loop = await repo.get_loop(loop_run_id, conversation.id)
    if loop is None:
        raise NotFoundException(
            "run confirmation not found",
            error_code=ErrorCode.RUN_CONFIRMATION_NOT_FOUND,
        )
    if checkpoint.status != "pending":
        raise ConflictException(
            "run confirmation already resolved",
            error_code=ErrorCode.RUN_CONFIRMATION_ALREADY_RESOLVED,
        )
    if checkpoint.expires_at <= datetime.now(timezone.utc):
        # 惰性收尾：没有后台清扫作业，过期只在被访问时发现并落定状态。
        await checkpoint_repo.mark_expired(loop_run_id)
        loop.status = "cancelled"
        loop.summary = "确认已过期，运行未继续"
        await repo.save_loop(loop)
        raise ConflictException(
            "run confirmation expired",
            error_code=ErrorCode.RUN_CONFIRMATION_EXPIRED,
        )
    # CAS 抢占：并发的两个解决请求只有一个能继续，另一个拿到 409。
    if not await checkpoint_repo.claim(loop_run_id, "resolved"):
        raise ConflictException(
            "run confirmation already resolved",
            error_code=ErrorCode.RUN_CONFIRMATION_ALREADY_RESOLVED,
        )

    outcome = await _execute_pending_tool(
        session,
        checkpoint=checkpoint,
        approved=payload.approved,
        agent=agent,
        current_user=current_user,
        conversation=conversation,
        loop=loop,
    )
    # 上下文快照用完即清，避免把整段对话长期留在检查点表里。
    await checkpoint_repo.mark_consumed(loop_run_id)

    context = await load_runtime_context(
        agent_repo,
        KnowledgeRepository(session),
        SkillRepository(session),
        McpRepository(session),
        BuiltinToolRepository(session),
        agent_id=agent_id,
        platform_id=agent.platform_id,
    )
    context.conversation_id = conversation.id
    context.loop_run_id = loop.id

    # 续跑不重新检索：挂起那刻的系统提示词里已经带着当时的引用，这里沿用
    # 上次落库的 assistant 消息上的引用，只为了把消息记录补全。消息主键已知，
    # 按主键 + 会话归属读单条即可，不必把整段会话的消息读出来再线性查找。
    citations: list = []
    if loop.assistant_message_id:
        message = await repo.get_message(loop.assistant_message_id, conversation.id)
        if message is not None:
            citations = list(message.citations or [])

    resolved = await resolve_chat_model(
        session, platform_id=agent.platform_id, agent_id=agent_id
    )
    return _ResumePlan(
        agent=agent,
        context=context,
        conversation=conversation,
        loop=loop,
        checkpoint=checkpoint,
        outcome=outcome,
        citations=citations,
        resolved=resolved,
    )


@router.post("/{agent_id}/runs/{loop_run_id}/resolve")
async def resolve_run_endpoint(
    agent_id: int,
    loop_run_id: int,
    payload: RunResolveRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    """解决一次挂起的工具确认，并以 SSE 继续同一次运行。

    平台后台用户才可解决（嵌入端走 WebSocket 的连接级确认通道），因此这里
    用 `require_current_active_user` 而不是对话端点的联合鉴权。
    """
    plan = await _prepare_resume(
        agent_id, loop_run_id, payload, current_user, session
    )

    async def _resume_impl(
        tool_session: AsyncSession,
        model_tasks: set[asyncio.Task],
    ) -> AsyncIterator[str]:
        request_id = f"sse-{uuid4().hex}"
        sequence = 0
        try:
            invoke = build_tool_invoker(
                platform_id=plan.agent.platform_id,
                agent_id=agent_id,
                user_id=current_user.id,
                builtin_repo=BuiltinToolRepository(tool_session),
                skill_repo=SkillRepository(tool_session),
                mcp_repo=McpRepository(tool_session),
                tool_session=tool_session,
                conversation_id_provider=lambda: plan.conversation.id,
                loop_run_id_provider=lambda: plan.loop.id,
                # 续跑阶段不会再弹确认：用户在解决端点里已经表过态。
                confirmation_decider=_always_approve,
            )
            async for item in resume_stream_chat(
                ConversationRepository(session),
                plan.context,
                conversation=plan.conversation,
                loop=plan.loop,
                checkpoint=plan.checkpoint,
                outcome=plan.outcome,
                model=build_chat_model(
                    plan.context.version,
                    resolved=plan.resolved,
                    session_id_provider=lambda: plan.conversation.id,
                ),
                citations=plan.citations,
                invoke_tool_fn=invoke,
                on_model_task_started=model_tasks.add,
            ):
                for event in run_events_from_stream_item(item, request_id=request_id):
                    sequence += 1
                    yield to_sse_block(event, sequence=sequence)
        except Exception as error:
            sequence += 1
            yield to_sse_block(
                protocol_error(
                    request_id=request_id,
                    payload=build_agent_error_payload(error),
                    conversation_id=plan.conversation.id,
                ),
                sequence=sequence,
            )

    return _sse_response(_resume_impl)
