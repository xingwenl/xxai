"""DAG 化的定义校验：依赖语义、分层、引用范围与扇出上限。

与 ``test_validators.py`` 的分工：那个文件锁的是**线性时代**的节点/边形状与
逐字错误文案（本次改造只加了 ``depends_on``/``position`` 两个键，其余断言不动）；
这个文件专门覆盖「线性不再成立」之后新长出来的规则——依赖怎么解析、层怎么分、
引用为什么只能指向上游、扇出为什么要有上限。
"""

from __future__ import annotations

import pytest

from app.modules.workflows.validators import (
    MAX_PARALLEL_BRANCHES,
    compile_definition,
    execution_layers,
    resolve_depends_on,
    steps_from_definition,
    validate_definition,
    validate_steps,
)
from app.shared.exceptions import BadRequestException
from helpers import agent_step, tool_step


def _fan_out_steps() -> list[dict]:
    """一个入口 + 三个并行分支 + 一个显式汇聚步骤。

    这是本次改造的核心形状：分支之间互不可见，只有汇聚点能读到全部上游。
    """

    return [
        agent_step("entry", prompt="拆解问题"),
        agent_step("research", depends_on=["entry"], prompt="查资料"),
        agent_step("draft", depends_on=["entry"], prompt="写初稿"),
        agent_step("critique", depends_on=["entry"], prompt="挑毛病"),
        agent_step(
            "merge",
            depends_on=["research", "draft", "critique"],
            prompt="汇总 {{research.output}} / {{draft.output}} / {{critique.output}}",
        ),
    ]


def _legacy_steps() -> list[dict]:
    """改造前保存的形状：**没有** depends_on / position 两个键。"""

    return [
        {"step_id": "collect", "name": "收集", "kind": "agent", "prompt": "收集资料"},
        {
            "step_id": "query",
            "name": "查询",
            "kind": "agent",
            "prompt": "查询 {{collect.output}}",
        },
    ]


# --------------------------------------------------------------------------- 依赖解析


def test_resolve_depends_on_defaults_to_previous_step() -> None:
    """缺省 depends_on = 依赖序列中的前一个步骤，首步无依赖。"""

    steps = [agent_step("a"), agent_step("b"), agent_step("c")]
    assert resolve_depends_on(steps) == [[], ["a"], ["b"]]


def test_resolve_depends_on_honours_explicit_empty_list() -> None:
    """显式 ``[]`` 是「我是起点」，不是「沿用前一步」。

    并行分支的第二条及以后全靠这个区分；若把 ``[]`` 当成缺省处理，
    就会把并行定义静默解释成线性链。
    """

    steps = [
        agent_step("root"),
        agent_step("branch_a", depends_on=[]),
        agent_step("branch_b", depends_on=[]),
        agent_step("merge", depends_on=["branch_a", "branch_b"]),
    ]
    assert resolve_depends_on(steps) == [[], [], [], ["branch_a", "branch_b"]]


def test_resolve_depends_on_rejects_non_list() -> None:
    steps = [agent_step("a", depends_on="b")]
    with pytest.raises(BadRequestException, match="depends_on must be a list"):
        resolve_depends_on(steps)


def test_legacy_linear_definition_still_validates() -> None:
    """存量定义（节点上没有 depends_on 键）必须继续可用。

    这是「零迁移」承诺的落点：缺省语义就是线性继任，因此旧定义不需要回填字段。
    """

    steps = _legacy_steps()
    validate_steps(steps, max_steps=50)
    definition = compile_definition(steps)
    assert definition["edges"] == [
        {
            "edge_id": "collect->query",
            "source": "collect",
            "target": "query",
            "source_handle": "default",
        }
    ]
    restored = validate_definition(definition, max_steps=50)
    assert [step["step_id"] for step in restored] == ["collect", "query"]
    # 旧定义没有这两个键，还原后补成 None（= 沿用缺省语义），定义本身不回写。
    assert [step["depends_on"] for step in restored] == [None, None]
    assert [step["position"] for step in restored] == [None, None]


# --------------------------------------------------------------------------- 编译与分层


def test_compile_definition_emits_fan_out_and_fan_in_edges() -> None:
    """边由依赖编译：入口扇出三条、汇聚收三条。"""

    steps = _fan_out_steps()
    definition = compile_definition(steps)
    pairs = {(edge["source"], edge["target"]) for edge in definition["edges"]}
    assert pairs == {
        ("entry", "research"),
        ("entry", "draft"),
        ("entry", "critique"),
        ("research", "merge"),
        ("draft", "merge"),
        ("critique", "merge"),
    }
    assert steps_from_definition(definition) == steps


def test_execution_layers_groups_parallel_branches_together() -> None:
    """分层结果直接等于调度计划：入口一层、三分支一层、汇聚一层。"""

    layers = execution_layers(_fan_out_steps())
    assert [[step["step_id"] for step in layer] for layer in layers] == [
        ["entry"],
        ["research", "draft", "critique"],
        ["merge"],
    ]


def test_execution_layers_keeps_definition_order_within_a_layer() -> None:
    """同层内按定义顺序排列，保证步骤记录的顺序稳定可复现。"""

    steps = [
        agent_step("root"),
        agent_step("c", depends_on=["root"]),
        agent_step("a", depends_on=["root"]),
        agent_step("b", depends_on=["root"]),
    ]
    layers = execution_layers(steps)
    assert [step["step_id"] for step in layers[1]] == ["c", "a", "b"]


def test_execution_layers_starts_a_step_as_early_as_possible() -> None:
    """跨层的传递依赖不能把无关步骤也推迟：``b`` 只等 ``a``，不必等同层的 ``slow``。"""

    steps = [
        agent_step("root"),
        agent_step("slow", depends_on=["root"]),
        agent_step("a", depends_on=["root"]),
        agent_step("b", depends_on=["a"]),
    ]
    layers = execution_layers(steps)
    assert [[step["step_id"] for step in layer] for layer in layers] == [
        ["root"],
        ["slow", "a"],
        ["b"],
    ]


# --------------------------------------------------------------------------- 依赖结构校验


def test_validate_steps_rejects_dependency_cycle() -> None:
    steps = [
        agent_step("a", depends_on=["c"]),
        agent_step("b", depends_on=["a"]),
        agent_step("c", depends_on=["b"]),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    message = str(excinfo.value)
    assert "dependency cycle among steps" in message
    # 环上每个步骤都要被点出来，否则用户不知道从哪断。
    assert "a" in message and "b" in message and "c" in message


def test_validate_steps_rejects_unknown_dependency() -> None:
    steps = [agent_step("a"), agent_step("b", depends_on=["ghost"])]
    with pytest.raises(
        BadRequestException, match="depends_on references an unknown step: ghost"
    ):
        validate_steps(steps, max_steps=50)


def test_validate_steps_rejects_self_dependency() -> None:
    steps = [agent_step("a", depends_on=["a"])]
    with pytest.raises(BadRequestException, match="cannot depend on itself"):
        validate_steps(steps, max_steps=50)


def test_validate_steps_rejects_duplicated_dependency() -> None:
    steps = [agent_step("a"), agent_step("b", depends_on=["a", "a"])]
    with pytest.raises(BadRequestException, match="duplicated dependency: a"):
        validate_steps(steps, max_steps=50)


def test_validate_steps_rejects_parallel_width_beyond_limit() -> None:
    """扇出上限必须在保存期就拒绝，否则一次运行会同时打出 N 个模型请求。"""

    steps = [agent_step("root")] + [
        agent_step(f"branch_{index}", depends_on=["root"])
        for index in range(MAX_PARALLEL_BRANCHES + 1)
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert f"exceeds MAX_PARALLEL_BRANCHES {MAX_PARALLEL_BRANCHES}" in str(
        excinfo.value
    )


def test_validate_steps_accepts_width_exactly_at_limit() -> None:
    steps = [agent_step("root")] + [
        agent_step(f"branch_{index}", depends_on=["root"])
        for index in range(MAX_PARALLEL_BRANCHES)
    ]
    validate_steps(steps, max_steps=50)


def test_validate_steps_rejects_orphan_branch_beyond_limit() -> None:
    """起点也可以被并行扇出撑爆：显式 ``[]`` 的步骤同样算在同一层里。"""

    steps = [
        agent_step(f"start_{index}", depends_on=[])
        for index in range(MAX_PARALLEL_BRANCHES + 1)
    ]
    with pytest.raises(BadRequestException, match="can run in parallel"):
        validate_steps(steps, max_steps=50)


# --------------------------------------------------------------------------- 引用范围


def test_validate_steps_allows_transitive_upstream_reference() -> None:
    """间接依赖也算上游：汇聚点可以引用爷爷辈的输出。"""

    steps = [
        agent_step("a"),
        agent_step("b", depends_on=["a"]),
        agent_step("c", depends_on=["b"], prompt="参考 {{a.output}} 与 {{b.output}}"),
    ]
    validate_steps(steps, max_steps=50)


def test_validate_steps_rejects_read_across_parallel_branches() -> None:
    """并行分支之间互不可见——这是「分支不可互读变量」的落点。

    ``draft`` 与 ``critique`` 同层、无依赖关系，因此 ``critique`` 不能引用
    ``draft`` 的输出：运行期两者同时开跑，谁先有输出都不确定。
    """

    steps = [
        agent_step("entry"),
        agent_step("draft", depends_on=["entry"]),
        agent_step("critique", depends_on=["entry"], prompt="评价 {{draft.output}}"),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert "which is not an upstream step" in str(excinfo.value)


def test_validate_steps_rejects_input_binding_across_parallel_branches() -> None:
    steps = [
        agent_step("entry"),
        tool_step("run_a", "http_get", depends_on=["entry"]),
        tool_step(
            "run_b",
            "http_get",
            depends_on=["entry"],
            input_bindings={"url": ["run_a", "output"]},
        ),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert "references 'run_a', which is not an upstream step" in str(excinfo.value)


def test_validate_steps_accepts_input_binding_from_upstream_branch() -> None:
    steps = [
        agent_step("entry"),
        tool_step(
            "notify",
            "http_get",
            depends_on=["entry"],
            input_bindings={"body": ["entry", "output"]},
        ),
    ]
    validate_steps(steps, max_steps=50)


# --------------------------------------------------------------------------- 坐标与边一致性


def test_validate_steps_accepts_numeric_position() -> None:
    validate_steps(
        [agent_step("a", position={"x": 12.5, "y": -3})],
        max_steps=50,
    )


@pytest.mark.parametrize(
    "position",
    [{"x": 1}, {"x": "1", "y": 2}, {"x": 1, "y": None}, [1, 2], {"x": True, "y": 2}],
)
def test_validate_steps_rejects_malformed_position(position: object) -> None:
    with pytest.raises(BadRequestException, match="position must be an object"):
        validate_steps([agent_step("a", position=position)], max_steps=50)


def test_validate_definition_rejects_edges_that_contradict_depends_on() -> None:
    """edges 与 depends_on 打架时必须拒绝。

    运行期只读 nodes 还原出的 steps，不读 edges；若不校验，一份定义会
    「看起来一张图、跑起来另一张图」。
    """

    definition = compile_definition(_fan_out_steps())
    definition["edges"] = [
        edge for edge in definition["edges"] if edge["edge_id"] != "entry->draft"
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_definition(definition, max_steps=50)
    message = str(excinfo.value)
    assert "edges do not match depends_on" in message
    assert "entry->draft" in message


def test_validate_definition_rejects_edges_with_extra_pairs() -> None:
    definition = compile_definition(_fan_out_steps())
    definition["edges"].append(
        {
            "edge_id": "draft->critique",
            "source": "draft",
            "target": "critique",
            "source_handle": "default",
        }
    )
    with pytest.raises(BadRequestException, match="draft->critique"):
        validate_definition(definition, max_steps=50)


# --------------------------------------------------------------------------- 端到端形状


def test_fan_out_definition_round_trips_through_snapshot() -> None:
    """定义进快照再出来，依赖与坐标都不丢——运行期只认快照。"""

    steps = _fan_out_steps()
    steps[1]["position"] = {"x": 100, "y": 0}
    snapshot = compile_definition(steps)
    restored = validate_definition(snapshot, max_steps=50)
    assert restored == steps
    assert resolve_depends_on(restored) == resolve_depends_on(steps)
    assert [len(layer) for layer in execution_layers(restored)] == [1, 3, 1]


def test_fan_out_definition_rejects_step_count_beyond_max_steps() -> None:
    with pytest.raises(BadRequestException, match="exceeds max_steps 3"):
        validate_steps(_fan_out_steps(), max_steps=3)
