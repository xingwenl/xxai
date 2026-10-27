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
from app.modules.agent_runtime.usage import usage_from_message_metadata

# 列表项只渲染一行摘要，超长正文在服务端截断，避免把整段消息塞进列表响应。
PREVIEW_LIMIT = 80


def build_delegated_run_payload(
    loop: AgentLoopRun,
    *,
    agent_slug: str | None = None,
    agent_name: str | None = None,
    usage: dict | None = None,
    mode: str | None = None,
) -> dict:
    """把一次**子运行**压成读侧投影里的条目。

    只暴露展示需要的字段：模型与工具的完整过程在子运行自己的会话里，读侧不去
    展开（父子是两条独立会话，跨会话拼过程会让这份投影失去稳定形状）。

    ``usage``（该子运行自己的 token 合计）与 ``mode``（self=自克隆 / bound=绑定）
    只在确实有值时出现——没有委派用量的历史运行，投影形状与引入这两个字段前一致。
    """
    payload = {
        "id": str(loop.id),
        "agentSlug": agent_slug,
        "agentName": agent_name or agent_slug,
        "status": loop.status,
        "summary": loop.summary,
        "conversationId": str(loop.conversation_id),
    }
    if usage:
        # 契约与前端/ai-sdk 的 camelCase 对齐；total 缺失时用前两者相加兜底，
        # 避免上游只返回部分字段时展示层出现 0。
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        payload["usage"] = {
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": int(
                usage.get("total_tokens") or prompt_tokens + completion_tokens
            ),
        }
    if mode:
        payload["mode"] = mode
    return payload


def build_loop_payload(
    loop: AgentLoopRun,
    steps: list[AgentLoopStep],
    delegated_runs: list[dict] | None = None,
) -> dict:
    """把一次 Agent Loop 及其步骤压成前端可直接渲染的 payload。

    键名用 camelCase 与 ai-sdk 的 `AgentLoopRun` 对齐（`requestId`/`stepType`/
    `outputSummary` 等），前端无需再做一次字段改名。

    ``delegatedRuns``/``delegatedRunIds`` 只在**确实有委派**时出现：没有委派的
    运行，这份投影与引入委派之前逐字相同（这是回归口径的一部分）。
    """
    payload = {
        "id": str(loop.id),
        "requestId": loop.request_id,
        "status": loop.status,
        "summary": loop.summary,
        "steps": [_step_payload(step) for step in steps],
    }
    if delegated_runs:
        payload["delegatedRuns"] = delegated_runs
    return payload


def _step_payload(step: AgentLoopStep) -> dict:
    """单个步骤的投影；委派产生的 ``delegatedRunIds`` 只在非空时附带。"""
    payload = {
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
    delegated_ids = delegated_run_ids(step)
    if delegated_ids:
        payload["delegatedRunIds"] = delegated_ids
    return payload


def delegated_run_ids(step: AgentLoopStep) -> list[str]:
    """从步骤扩展元数据里读出该步骤派生出的子运行 ID。

    "同一次扇出"的分组键记在父步骤自己的 metadata 上，而不是给
    ``agent_loop_runs`` 再加一个指向步骤的外键：工具步骤记录是在整轮运行收尾时
    才补建的，而子运行在工具执行期间就已落库，那一刻父步骤行还不存在。
    """
    metadata = getattr(step, "step_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    raw = metadata.get("delegatedRunIds")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


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
    loop_payloads = await _build_loop_payloads(
        repo, await repo.list_loops(conversation_id)
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
            "usage": usage_from_message_metadata(
                getattr(message, "message_metadata", None)
            ),
            "loop": loop_payloads.get(message.id),
        }
        for message in messages
    ]


async def _build_loop_payloads(repo, loops) -> dict[int | None, dict]:
    """按 assistant 消息 ID 归档每条 Loop 的投影。

    仓储具备批量读取能力时走批量路径：步骤、子运行各一次 ``IN`` 查询，子运行
    用量再聚合一次，连同 Loop 列表共 4 次，与轮数无关。轻量替身（测试里的假
    仓储）没有这些方法，退回逐 Loop 读取，行为与批量前逐字一致。
    """
    if not loops:
        return {}
    if hasattr(repo, "list_loop_steps_by_loop_ids") and hasattr(
        repo, "list_child_loops_by_parent_ids"
    ):
        return await _build_loop_payloads_batched(repo, loops)
    payloads: dict[int | None, dict] = {}
    for loop in loops:
        delegated_runs = await load_delegated_runs(repo, loop.id)
        payloads[loop.assistant_message_id] = build_loop_payload(
            loop, await repo.list_loop_steps(loop.id), delegated_runs
        )
    return payloads


async def _build_loop_payloads_batched(repo, loops) -> dict[int | None, dict]:
    """批量路径：步骤、子运行、子运行用量各只查一次。"""
    loop_ids = [loop.id for loop in loops]
    steps_by_loop = await repo.list_loop_steps_by_loop_ids(loop_ids)
    children_by_parent = await repo.list_child_loops_by_parent_ids(loop_ids)
    child_conversation_ids = [
        child.conversation_id
        for rows in children_by_parent.values()
        for child, _slug, _name in rows
    ]
    usage_by_conversation: dict[int, dict] = {}
    if child_conversation_ids and hasattr(repo, "usage_by_conversation_ids"):
        usage_by_conversation = await repo.usage_by_conversation_ids(
            child_conversation_ids
        )
    payloads: dict[int | None, dict] = {}
    for loop in loops:
        delegated_runs = [
            build_delegated_run_payload(
                child,
                agent_slug=slug,
                agent_name=name,
                usage=usage_by_conversation.get(child.conversation_id),
                # 自克隆 / 绑定的区分在运行期决定，落在 loop 的 metadata 里。
                mode=(child.run_metadata or {}).get("delegationMode"),
            )
            for child, slug, name in children_by_parent.get(loop.id, [])
        ]
        payloads[loop.assistant_message_id] = build_loop_payload(
            loop, steps_by_loop.get(loop.id, []), delegated_runs
        )
    return payloads


async def load_delegated_runs(repo, loop_run_id: int) -> list[dict]:
    """读一次运行的子运行列表；仓储没有对应能力时返回空（兼容轻量替身）。"""
    if not hasattr(repo, "list_child_loops"):
        return []
    rows = await repo.list_child_loops(loop_run_id)
    usage_by_conversation: dict[int, dict] = {}
    if rows and hasattr(repo, "usage_by_conversation_ids"):
        usage_by_conversation = await repo.usage_by_conversation_ids(
            [child.conversation_id for child, _slug, _name in rows]
        )
    return [
        build_delegated_run_payload(
            child,
            agent_slug=slug,
            agent_name=name,
            usage=usage_by_conversation.get(child.conversation_id),
            # 自克隆 / 绑定的区分在运行期决定，落在 loop 的 metadata 里。
            mode=(child.run_metadata or {}).get("delegationMode"),
        )
        for child, slug, name in rows
    ]


def conversation_preview(value: object, *, limit: int = PREVIEW_LIMIT) -> str | None:
    """把末条消息压成单行摘要，供列表项显示。"""
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    if not collapsed:
        return None
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}…"
