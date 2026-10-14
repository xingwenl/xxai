"""会话读取投影：把 ORM 对象拼装成跨接口共用的字典结构。

后台会话记录（`admin_router`）与 embed 消息快照（`embed/services.py`）都需要
同一份「消息 + 该消息对应的 Agent Loop」形状。放在这里共用，避免两处各写一遍
而出现字段漂移——ai-sdk 的两条渲染路径（聊天窗口与历史记录组件）因此消费到
逐字段相同的投影。
"""

from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    ConversationMessage,
)

# 列表项只渲染一行摘要，超长正文在服务端截断，避免把整段消息塞进列表响应。
PREVIEW_LIMIT = 80


def build_loop_payload(loop: AgentLoopRun, steps: list[AgentLoopStep]) -> dict:
    """把一次 Agent Loop 及其步骤压成前端可直接渲染的 payload。

    键名用 camelCase 与 ai-sdk 的 `AgentLoopRun` 对齐（`requestId`/`stepType`/
    `outputSummary` 等），前端无需再做一次字段改名。
    """
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
                "inputSummary": step.input_summary,
                "thinkingText": step.thinking_text,
                "toolName": step.tool_name,
                "skillName": step.skill_name,
                "citationRefs": step.citation_refs,
                "error": step.error,
            }
            for step in steps
        ],
    }


async def build_message_snapshots(
    repo,
    *,
    conversation_id: int,
    messages: list[ConversationMessage],
) -> list[dict]:
    """按消息拼装快照，把 Loop 挂到它所属的 assistant 消息上。

    `repo` 没有 `list_loops` 时原样返回入参：这条兼容分支是为轻量仓储替身与
    旧读取实现保留的，与抽取前的 embed 行为一致。
    """
    if not hasattr(repo, "list_loops"):
        return messages
    loop_payloads: dict[int | None, dict] = {}
    for loop in await repo.list_loops(conversation_id):
        loop_payloads[loop.assistant_message_id] = build_loop_payload(
            loop, await repo.list_loop_steps(loop.id)
        )
    return [
        {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "status": message.status,
            "content_blocks": message.content_blocks,
            "citations": message.citations,
            "knowledge_grounded": message.knowledge_grounded,
            "tool_call_id": message.tool_call_id,
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "loop": loop_payloads.get(message.id),
        }
        for message in messages
    ]


def conversation_preview(value: object, *, limit: int = PREVIEW_LIMIT) -> str | None:
    """把末条消息压成单行摘要，供列表项显示。"""
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    if not collapsed:
        return None
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}…"
