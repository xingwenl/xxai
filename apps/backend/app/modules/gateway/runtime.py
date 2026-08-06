"""网关请求任务和 Embed 对话流的运行时编排。"""

import asyncio
from collections.abc import AsyncIterator

from app.core.logging import get_logger
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import build_system_prompt, stream_graph
from app.modules.conversation.schemas import sanitize_content_blocks
from app.shared.exceptions import NotFoundException

logger = get_logger(__name__)


def _tool_step_values(tool_event: dict, sequence: int) -> dict:
    outcome = tool_event["outcome"]
    outcome_status = getattr(outcome, "status", "succeeded")
    status = {
        "confirmation_required": "waiting_confirmation",
        "failed": "failed",
        "error": "failed",
    }.get(outcome_status, "succeeded")
    result_text = "失败" if status == "failed" else "完成"
    return {
        "sequence": sequence,
        "step_type": tool_event.get("tool_type", "host_tool"),
        "title": f"调用工具：{tool_event['tool']}",
        "status": status,
        "input_summary": tool_event.get("input_summary"),
        "output_summary": "等待用户确认" if status == "waiting_confirmation" else f"工具执行{result_text}",
        "tool_name": tool_event["tool"],
        "skill_name": tool_event.get("skill_name"),
        "skill_version": tool_event.get("skill_version"),
        "tool_call_id": str(tool_event.get("tool_call_id", tool_event["tool"])),
        "error": {"code": "tool_failed", "message": "工具执行失败"} if status == "failed" else None,
    }


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

    user_message = await repo.create_message(
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
    loop = await repo.create_loop(
        conversation.id,
        user_message_id=user_message.id,
        request_id=request_id,
        status="running",
        summary="正在处理请求",
    )
    await repo.save_loop(loop)
    yield {
        "type": "agent_loop_started",
        "conversation": conversation,
        "request_id": request_id,
        "loop_run_id": loop.id,
        "payload": {"loopRunId": str(loop.id), "status": "running", "summary": loop.summary},
    }
    retrieval_step = await repo.create_loop_step(
        loop.id,
        sequence=1,
        step_type="knowledge_retrieval",
        title="检索知识库",
        status="succeeded",
        input_summary=f"检索当前问题（{len(message)} 字符）",
        output_summary=f"命中 {len(citations)} 条引用" if citations else "未命中知识库引用",
        citation_refs=citations,
    )
    await repo.save_loop(loop)
    yield {
        "type": "agent_step_completed",
        "conversation": conversation,
        "request_id": request_id,
        "loop_run_id": loop.id,
        "step_id": retrieval_step.id,
        "payload": {"loopRunId": str(loop.id), "stepId": str(retrieval_step.id), "sequence": 1, "stepType": "knowledge_retrieval", "title": retrieval_step.title, "status": retrieval_step.status, "outputSummary": retrieval_step.output_summary, "citationRefs": citations},
    }
    skill_steps = []
    for sequence, usage in enumerate(getattr(context, "skill_usages", []), start=2):
        skill_step = await repo.create_loop_step(
            loop.id,
            sequence=sequence,
            step_type="skill_instruction",
            title=f"应用技能：{usage['name']}",
            status="succeeded",
            output_summary="技能指令已加载" + ("，可调用脚本工具" if usage.get("has_script_tool") else ""),
            skill_name=usage["name"],
            skill_version=usage.get("version"),
            step_metadata={"slug": usage.get("slug"), "hasScriptTool": usage.get("has_script_tool", False)},
        )
        skill_steps.append(skill_step)
        await repo.save_loop(loop)
        yield {"type": "agent_step_completed", "conversation": conversation, "request_id": request_id, "loop_run_id": loop.id, "step_id": skill_step.id, "payload": {"loopRunId": str(loop.id), "stepId": str(skill_step.id), "sequence": sequence, "stepType": "skill_instruction", "title": skill_step.title, "status": "succeeded", "outputSummary": skill_step.output_summary, "skillName": skill_step.skill_name, "skillVersion": skill_step.skill_version}}
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
        "request_id": request_id,
        "loop_run_id": loop.id,
        "step_id": generation_step.id,
        "payload": {"loopRunId": str(loop.id), "stepId": str(generation_step.id), "sequence": generation_sequence, "stepType": "model_generation", "title": generation_step.title, "status": "running"},
    }
    result = None
    tool_steps = {}
    next_step_sequence = generation_sequence + 1
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
        if item["type"] == "tool_started":
            call_id = str(item["tool_call_id"])
            tool_step = await repo.create_loop_step(
                loop.id,
                sequence=next_step_sequence,
                step_type=item["tool_type"],
                title=f"调用工具：{item['tool']}",
                status="running",
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
                "request_id": request_id,
                "loop_run_id": loop.id,
                "step_id": tool_step.id,
                "payload": {
                    "loopRunId": str(loop.id),
                    "stepId": str(tool_step.id),
                    "sequence": tool_step.sequence,
                    "stepType": tool_step.step_type,
                    "title": tool_step.title,
                    "status": tool_step.status,
                    "toolName": tool_step.tool_name,
                    "skillName": tool_step.skill_name,
                    "skillVersion": tool_step.skill_version,
                },
            }
            continue
        if item["type"] == "tool_completed":
            call_id = str(item["tool_call_id"])
            tool_step = tool_steps.get(call_id)
            if tool_step is not None:
                values = _tool_step_values(item, tool_step.sequence)
                tool_step.status = values["status"]
                tool_step.output_summary = values["output_summary"]
                tool_step.error = values["error"]
                await repo.save_loop(loop)
                yield {
                    "type": "agent_step_completed",
                    "conversation": conversation,
                    "request_id": request_id,
                    "loop_run_id": loop.id,
                    "step_id": tool_step.id,
                    "payload": {
                        "loopRunId": str(loop.id),
                        "stepId": str(tool_step.id),
                        "sequence": tool_step.sequence,
                        "stepType": tool_step.step_type,
                        "title": tool_step.title,
                        "status": tool_step.status,
                        "outputSummary": tool_step.output_summary,
                        "toolName": tool_step.tool_name,
                        "skillName": tool_step.skill_name,
                        "skillVersion": tool_step.skill_version,
                    },
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
                "loop_run_id": loop.id,
                "request_id": request_id,
                "payload": item["payload"],
            }
            return
        result = item["result"]

    if result is None:
        return
    content_blocks = sanitize_content_blocks([{"id": f"message_{request_id}_markdown", "type": "markdown", "text": result.content, "status": "completed"}])
    assistant = await repo.create_message(
        conversation.id,
        role="assistant",
        content=result.content,
        content_blocks=content_blocks,
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
    for offset, tool_event in enumerate(result.tool_events or [], start=2):
        if str(tool_event.get("tool_call_id", tool_event["tool"])) in tool_steps:
            continue
        tool_step = await repo.create_loop_step(
            loop.id,
            **_tool_step_values(tool_event, offset),
        )
        await repo.save_loop(loop)
        yield {
            "type": "agent_step_completed",
            "conversation": conversation,
            "message": assistant,
            "request_id": request_id,
            "loop_run_id": loop.id,
            "step_id": tool_step.id,
            "payload": {
                "loopRunId": str(loop.id),
                "stepId": str(tool_step.id),
                "sequence": tool_step.sequence,
                "stepType": tool_step.step_type,
                "title": tool_step.title,
                "status": tool_step.status,
                "outputSummary": tool_step.output_summary,
                "toolName": tool_step.tool_name,
            },
        }
    generation_step.sequence = next_step_sequence
    generation_step.status = "succeeded" if result.pending_confirmation_id is None else "waiting_confirmation"
    generation_step.output_summary = f"生成 {len(result.content)} 字符"
    loop.assistant_message_id = assistant.id
    loop.status = "waiting_confirmation" if result.pending_confirmation_id is not None else "completed"
    loop.summary = "已完成回答" if loop.status == "completed" else "等待用户确认后继续"
    await repo.save_loop(loop)
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
        "type": "agent_step_completed",
        "conversation": conversation,
        "message": assistant,
        "request_id": request_id,
        "loop_run_id": loop.id,
        "step_id": generation_step.id,
        "payload": {"loopRunId": str(loop.id), "stepId": str(generation_step.id), "sequence": generation_step.sequence, "stepType": "model_generation", "title": generation_step.title, "status": generation_step.status, "outputSummary": generation_step.output_summary},
    }
    yield {
        "type": "agent_loop_completed",
        "conversation": conversation,
        "message": assistant,
        "request_id": request_id,
        "loop_run_id": loop.id,
        "payload": {"loopRunId": str(loop.id), "status": loop.status, "summary": loop.summary},
    }
    yield {
        "type": "message_completed",
        "content": result.content,
        "content_blocks": content_blocks,
        "conversation": conversation,
        "message": assistant,
        "result": result,
        "request_id": request_id,
    }
