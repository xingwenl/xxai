"""条件分支的**运行期**语义：判定、跳过传播、到达触发汇聚与 fail_branch。

保存期（定义能不能存下来）在 ``test_validators_conditions.py``。这个文件只回答
运行时的四个问题：

1. 条件步骤怎么判定、何时走兜底（``evaluate_predicate`` 真值表 + 集成用例）；
2. 没被选中的分支上那些步骤，状态与记录长什么样（``skipped``，每步恰好一条）；
3. 下游凭什么执行——**依赖边到达**而不是「依赖步骤成功」，所以只有一条分支
   到达时汇聚步骤照样跑，而被跳过的依赖会继续往下传播；
4. ``fail_branch`` 失败后走 ``@failed`` 出口，整条 run 仍以 ``completed`` 收尾。

复用 ``test_runner_parallel`` 的库/夹具（文件库 + WAL 才能承受并发写），但替身
换成**剧本化**的：按提示词里的标记返回指定输出，否则无法让上游输出驱动谓词。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.conversation.models import AgentLoopRun, Conversation
from app.modules.workflows import runner
from app.modules.workflows.models import WorkflowRun
from helpers import agent_step, condition_step, output_ref, predicate, seed
from test_runner_parallel import (
    _make_parallel_session,
    _make_run,
    _make_workflow,
    _patch_execution,
    _step_records,
)


def _make_scripted_probe(
    script: dict[str, str],
    *,
    fail_prompts: frozenset[str] = frozenset(),
    delay: float = 0.0,
):
    """剧本化替身：命中标记就返回对应输出，命中失败标记就抛错。

    并发语义由 ``test_runner_parallel`` 用时间窗证明；这里要的是**可预测的上游
    输出**，好让谓词的真假由用例完全掌控。
    """

    probe = SimpleNamespace(calls=[])
    state = {"index": 0}

    async def fake_execute(session, **kwargs):
        index = state["index"]
        state["index"] += 1
        message = kwargs["message"]
        probe.calls.append({"index": index, "message": message, "kwargs": kwargs})
        await asyncio.sleep(delay)
        if any(fragment in message for fragment in fail_prompts):
            raise RuntimeError(f"注入失败：{message}")
        content = next(
            (text for marker, text in script.items() if marker in message), ""
        )
        conversation = Conversation(
            platform_id=kwargs["platform_id"],
            agent_id=kwargs["agent_id"],
            user_id=kwargs["user_id"],
            platform_end_user_id=kwargs["end_user_id"],
            title="工作流步骤",
        )
        session.add(conversation)
        await session.flush()
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            request_id=f"conditions-test-{index}",
            status="completed",
        )
        session.add(loop)
        await session.flush()
        return (
            conversation,
            SimpleNamespace(id=1, content=content),
            SimpleNamespace(content=content, loop_id=loop.id),
        )

    return probe, fake_execute


async def _run_workflow(
    tmp_path, monkeypatch, steps, *, script, fail_prompts=frozenset()
):
    """建库 → 存定义 → 跑一次 → 回收（状态、记录、run 计数、替身）。"""

    engine, session_factory = await _make_parallel_session(tmp_path / "conditions.db")
    try:
        async with session_factory() as session:
            meta = await seed(session)
            workflow = await _make_workflow(session, meta, steps)
            run_id = await _make_run(session, workflow)
            await session.commit()

        probe, fake = _make_scripted_probe(script, fail_prompts=fail_prompts)
        _patch_execution(monkeypatch, fake)

        status = await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
        records = await _step_records(session_factory, run_id)
        async with session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            summary = SimpleNamespace(
                completed_steps=run.completed_steps, status=run.status
            )
        return status, records, summary, probe
    finally:
        await engine.dispose()


def _decision_steps(branches: list[dict]) -> list[dict]:
    """入口 → 条件闸门 → 两条互斥分支。"""

    return [
        agent_step("entry", prompt="入口标记"),
        condition_step("gate", depends_on=["entry"], branches=branches),
        agent_step("on_yes", depends_on=["gate@yes"], prompt="走 yes"),
        agent_step("on_no", depends_on=["gate@no"], prompt="走 no"),
    ]


def _yes_no_branches() -> list[dict]:
    return [
        {
            "name": "yes",
            "when": predicate("contains", left=output_ref("entry"), right="赞成"),
        },
        {"name": "no", "when": None},
    ]


def test_predicate_truth_table() -> None:
    """验收 3：四个比较算子与 all/any/not 组合的真值表。"""

    outputs = {"entry": "hello world 123"}
    ref = output_ref("entry")

    assert runner.evaluate_predicate(
        predicate("equals", left=ref, right="hello world 123"), outputs
    )
    assert not runner.evaluate_predicate(
        predicate("equals", left=ref, right="hello"), outputs
    )
    assert runner.evaluate_predicate(
        predicate("contains", left=ref, right="world"), outputs
    )
    assert not runner.evaluate_predicate(
        predicate("contains", left=ref, right="地球"), outputs
    )
    assert runner.evaluate_predicate(predicate("not_empty", left=ref), outputs)
    assert runner.evaluate_predicate(
        predicate("matches", left=ref, right=r"\d+"), outputs
    )
    assert not runner.evaluate_predicate(
        predicate("matches", left=ref, right=r"^\d+$"), outputs
    )
    assert not runner.evaluate_predicate(
        predicate("not_empty", left=ref), {"entry": "   "}
    )

    equals = predicate("equals", left=ref, right="hello world 123")
    empty = predicate("not_empty", left=output_ref("missing"))
    assert (
        runner.evaluate_predicate(predicate("all", children=[equals, empty]), outputs)
        is False
    )
    assert (
        runner.evaluate_predicate(predicate("any", children=[empty, equals]), outputs)
        is True
    )
    assert (
        runner.evaluate_predicate(predicate("not", children=[empty]), outputs) is True
    )
    assert runner.evaluate_predicate(
        predicate("all", children=[equals, predicate("not", children=[empty])]), outputs
    )


def test_predicate_reads_a_missing_upstream_as_an_empty_string() -> None:
    """上游没有输出（被跳过）时按空串比较——跳过是正常结果，不是运行失败。"""

    assert runner.evaluate_predicate(
        predicate("equals", left=output_ref("skipped_step"), right=""), {}
    )
    assert not runner.evaluate_predicate(
        predicate("not_empty", left=output_ref("skipped_step")), {}
    )


def test_predicate_rejects_an_unknown_operator() -> None:
    with pytest.raises(runner.StepFailedError):
        runner.evaluate_predicate({"op": "roughly", "left": "{{a.output}}"}, {"a": "x"})


def test_condition_takes_the_first_matching_branch(monkeypatch, tmp_path) -> None:
    """验收 3：多分支命中时取定义顺序里的第一个；未命中的分支被跳过。"""

    branches = [
        {
            "name": "yes",
            "when": predicate("contains", left=output_ref("entry"), right="同意"),
        },
        # 第二个条件同样为真，但排序在前面的 already 命中，这个分支不该被选中。
        {"name": "anyway", "when": predicate("not_empty", left=output_ref("entry"))},
        {"name": "no", "when": None},
    ]

    async def run() -> None:
        status, records, summary, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            _decision_steps(branches),
            script={"入口标记": "我同意这个方案"},
        )

        assert status == "completed"
        assert summary.status == "completed"
        # 条件步骤不算「执行过的步骤」之外的东西：entry + gate + on_yes。
        assert summary.completed_steps == 3

        gate = records["gate"]
        assert gate.status == "succeeded"
        assert gate.model_visible_output == "yes"
        # 条件步骤不建会话、不调模型：记录里没有会话，替身也没被它调用。
        assert gate.conversation_id is None
        assert gate.agent_loop_run_id is None
        assert [call["message"] for call in probe.calls] == ["入口标记", "走 yes"]

        skipped = records["on_no"]
        assert skipped.status == "skipped"
        assert skipped.error_message == runner.SKIPPED_MESSAGE
        # 跳过也要有完整的起止时间，否则前端时间轴上会出现一个空洞步骤。
        assert skipped.started_at is not None
        assert skipped.finished_at is not None
        # 每个步骤恰好一条记录（uq_workflow_step_runs_run_step 的要求）。
        assert set(records) == {"entry", "gate", "on_yes", "on_no"}

    asyncio.run(run())


def test_condition_falls_back_when_nothing_matches(monkeypatch, tmp_path) -> None:
    """验收 3：所有具名分支都不成立时走无条件兜底分支。"""

    async def run() -> None:
        status, records, _, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            _decision_steps(_yes_no_branches()),
            script={"入口标记": "说不清楚"},
        )

        assert status == "completed"
        assert records["gate"].model_visible_output == "no"
        assert records["on_no"].status == "succeeded"
        assert records["on_yes"].status == "skipped"
        assert [call["message"] for call in probe.calls] == ["入口标记", "走 no"]

    asyncio.run(run())


def test_merge_runs_when_only_one_branch_arrives(monkeypatch, tmp_path) -> None:
    """验收 5：汇聚步骤在「至少一条依赖边到达」时执行，不等齐所有分支。"""

    steps = [
        *_decision_steps(_yes_no_branches()),
        agent_step(
            "merge",
            depends_on=["on_yes", "on_no"],
            prompt="汇总 " + output_ref("on_yes") + " / " + output_ref("on_no"),
        ),
    ]

    async def run() -> None:
        status, records, summary, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            steps,
            script={"入口标记": "我赞成", "走 yes": "已同意", "汇总": "汇总结果"},
        )

        assert status == "completed"
        assert records["on_no"].status == "skipped"
        assert records["merge"].status == "succeeded"
        assert records["merge"].model_visible_output == "汇总结果"
        # 到达的依赖渲染出自己的输出，被跳过的依赖渲染成空串——同一条提示词里
        # 两种来源并存，这是「跳过不是错误」最直观的证据。
        assert probe.calls[-1]["message"] == "汇总 已同意 / "
        assert summary.completed_steps == 4

    asyncio.run(run())


def test_skip_propagates_downstream(monkeypatch, tmp_path) -> None:
    """验收 4：未选中分支上的步骤被跳过，它的下游同样被跳过（沿下游传播）。"""

    steps = [
        *_decision_steps(_yes_no_branches()),
        agent_step("after_no", depends_on=["on_no"], prompt="只有 no 分支在时才跑"),
        agent_step("after_after_no", depends_on=["after_no"], prompt="后果的后果"),
    ]

    async def run() -> None:
        status, records, _, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            steps,
            script={"入口标记": "我赞成"},
        )

        assert status == "completed"
        assert records["on_yes"].status == "succeeded"
        for step_id in ("on_no", "after_no", "after_after_no"):
            assert records[step_id].status == "skipped", step_id
            assert records[step_id].error_message == runner.SKIPPED_MESSAGE
        assert [call["message"] for call in probe.calls] == ["入口标记", "走 yes"]

    asyncio.run(run())


def _followup_steps() -> list[dict]:
    """两条互斥分支之后再接一个条件步骤，同时依赖两条分支。"""

    return [
        *_decision_steps(_yes_no_branches()),
        condition_step(
            "followup",
            depends_on=["on_yes", "on_no"],
            branches=[
                {
                    "name": "had_yes",
                    "when": predicate("not_empty", left=output_ref("on_yes")),
                },
                {"name": "none", "when": None},
            ],
        ),
        agent_step("report_yes", depends_on=["followup@had_yes"], prompt="报告 yes"),
        agent_step("report_none", depends_on=["followup@none"], prompt="报告 none"),
    ]


@pytest.mark.parametrize(
    ("entry_output", "expected_branch", "ran", "skipped"),
    [
        ("我赞成", "had_yes", "report_yes", "report_none"),
        ("我反对", "none", "report_none", "report_yes"),
    ],
)
def test_condition_reads_a_skipped_sibling_as_empty(
    monkeypatch,
    tmp_path,
    entry_output: str,
    expected_branch: str,
    ran: str,
    skipped: str,
) -> None:
    """验收 5：只有一条分支到达时条件步骤照样执行；被跳过的分支读成空串。

    这是「跳过不是错误」最直接的证据：如果被跳过的上游让求值抛错，条件分支就
    退化成了「必须等所有分支到齐」，而这正是本方案要摆脱的语义。
    """

    async def run() -> None:
        status, records, _, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            _followup_steps(),
            script={"入口标记": entry_output, "走 yes": "赞成详情", "报告": "报告内容"},
        )

        assert status == "completed"
        assert records["followup"].status == "succeeded"
        assert records["followup"].model_visible_output == expected_branch
        assert records[ran].status == "succeeded"
        assert records[skipped].status == "skipped"
        assert probe.calls[-1]["message"] == (
            "报告 yes" if ran == "report_yes" else "报告 none"
        )

    asyncio.run(run())


def test_fail_branch_routes_the_failure_to_its_own_outlet(
    monkeypatch, tmp_path
) -> None:
    """验收 6：失败走 ``@failed`` 出口，``@default`` 下游被跳过，run 仍 completed。"""

    steps = [
        agent_step("entry", prompt="入口标记", on_error="fail_branch"),
        agent_step("rescue", depends_on=["entry@failed"], prompt="补救"),
        agent_step("normal", depends_on=["entry"], prompt="正常路径"),
    ]

    async def run() -> None:
        status, records, summary, probe = await _run_workflow(
            tmp_path,
            monkeypatch,
            steps,
            script={"补救": "补救内容", "正常路径": "正常内容"},
            fail_prompts=frozenset({"入口标记"}),
        )

        assert status == "completed"
        assert summary.status == "completed"

        failed = records["entry"]
        assert failed.status == "failed"
        # 失败没有被「处理掉」：on_error_applied 保持假，记录如实说明这是一次失败。
        assert failed.on_error_applied is False
        assert failed.error_message and "注入失败" in failed.error_message

        assert records["rescue"].status == "succeeded"
        assert records["normal"].status == "skipped"
        assert records["normal"].error_message == runner.SKIPPED_MESSAGE
        # 失败的那次尝试也走完了替身，所以「入口标记」在列表里。
        assert [call["message"] for call in probe.calls] == ["入口标记", "补救"]
        # 失败步骤不计入 completed_steps（rescue 才是这一步链上真正完成的那一个）。
        assert summary.completed_steps == 1

    asyncio.run(run())


def test_condition_step_never_reaches_the_model() -> None:
    """条件步骤是纯数据判定：分支选择只看上游输出，不经过模型。"""

    step = condition_step(
        "gate",
        branches=[
            {
                "name": "yes",
                "when": predicate("equals", left=output_ref("entry"), right="x"),
            },
            {"name": "no", "when": None},
        ],
    )

    assert runner._match_branch(step, {"entry": "x"}) == "yes"
    assert runner._match_branch(step, {"entry": "y"}) == "no"
    # 上游被跳过时读成空串，仍然落在兜底分支上而不是抛错。
    assert runner._match_branch(step, {}) == "no"
