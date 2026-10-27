"""按已落库的运行记录回放工具组加载，产出一张可对比的基线表。

用法（在 ``apps/backend`` 下）::

    .venv/bin/python -m scripts.tool_group_report --limit 200
    .venv/bin/python -m scripts.tool_group_report --conversation-id 12
    .venv/bin/python -m scripts.tool_group_report --limit 500 --json
    .venv/bin/python -m scripts.tool_group_report --since-days 7

注意口径：回放用的是**当前**工具清单与当前的预取规则，因此「启用按组加载之前」
的旧运行会被算成「调用了未加载的工具」。比较基线时用 ``--since-days`` 或干脆
只统计上线之后的数据。

只读：不改表、不写文件、不触发任何模型调用。回放口径的解释见
``app/modules/agent_runtime/tool_group_stats.py`` 的模块注释。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import get_session_factory
from app.modules.agent_runtime.tool_group_stats import (
    STEP_CALL,
    STEP_LOAD,
    observe_run,
    render_markdown,
    summarize,
)
from app.modules.agent_runtime.tool_groups import (
    LOAD_TOOL_GROUP_NAME,
    LOADED_GROUP_METADATA_KEY,
)
from app.modules.builtin_tool.registry import list_builtin_tools
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    ConversationMessage,
)


def step_actions(steps: list[AgentLoopStep]) -> list[tuple[str, str]]:
    """把落库的工具步骤压成 ``(加载组 / 调用工具)`` 的动作序列。

    只有**成功**的 ``load_tool_group`` 才带 ``step_metadata``（失败时故意不写，
    避免把「假装加载过」重放成既成事实），因此这里只认元数据里的组名。
    """

    actions: list[tuple[str, str]] = []
    for step in steps:
        name = step.tool_name or ""
        if not name:
            continue
        if name == LOAD_TOOL_GROUP_NAME:
            metadata = step.step_metadata if isinstance(step.step_metadata, dict) else {}
            group = metadata.get(LOADED_GROUP_METADATA_KEY)
            if group:
                actions.append((STEP_LOAD, str(group)))
            continue
        actions.append((STEP_CALL, name))
    return actions


async def collect_stats(
    *,
    limit: int,
    conversation_id: int | None,
    since_days: int | None = None,
) -> dict[str, Any]:
    """读取最近的运行并按 run 回放，返回聚合后的统计字典。"""

    # 回放用的是**当前**内置工具清单：宿主与 MCP 工具没有落库的清单可依，
    # 它们对应的调用会被 observe_run 记为 external_calls，不参与未加载判断。
    tools = list(list_builtin_tools())
    async with get_session_factory()() as session:
        runs_query = select(AgentLoopRun).order_by(AgentLoopRun.id.desc()).limit(limit)
        if conversation_id is not None:
            runs_query = runs_query.where(
                AgentLoopRun.conversation_id == conversation_id
            )
        if since_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            runs_query = runs_query.where(AgentLoopRun.created_at >= cutoff)
        runs = list((await session.execute(runs_query)).scalars().all())
        if not runs:
            return summarize([])

        run_ids = [run.id for run in runs]
        steps = list(
            (
                await session.execute(
                    select(AgentLoopStep)
                    .where(AgentLoopStep.loop_run_id.in_(run_ids))
                    .order_by(AgentLoopStep.loop_run_id, AgentLoopStep.sequence)
                )
            )
            .scalars()
            .all()
        )
        steps_by_run: dict[int, list[AgentLoopStep]] = {run_id: [] for run_id in run_ids}
        for step in steps:
            steps_by_run.setdefault(step.loop_run_id, []).append(step)

        message_ids = [run.user_message_id for run in runs if run.user_message_id]
        messages = (
            list(
                (
                    await session.execute(
                        select(ConversationMessage).where(
                            ConversationMessage.id.in_(message_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if message_ids
            else []
        )
        content_by_message = {message.id: message.content or "" for message in messages}

    observations = [
        observe_run(
            tools,
            user_message=content_by_message.get(run.user_message_id or -1, ""),
            steps=step_actions(steps_by_run.get(run.id, [])),
        )
        for run in runs
    ]
    return summarize(observations)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="回放 agent_loop_steps，输出工具组预取与加载的基线统计"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="回放最近多少次运行（按 id 倒序），默认 200",
    )
    parser.add_argument(
        "--conversation-id",
        type=int,
        default=None,
        help="只统计指定会话",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="只统计最近 N 天内创建的运行；建议按组加载上线后再用",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 而不是 markdown，便于跨版本对比",
    )
    args = parser.parse_args()

    stats = asyncio.run(
        collect_stats(
            limit=args.limit,
            conversation_id=args.conversation_id,
            since_days=args.since_days,
        )
    )
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    print(render_markdown(stats))


if __name__ == "__main__":
    main()
