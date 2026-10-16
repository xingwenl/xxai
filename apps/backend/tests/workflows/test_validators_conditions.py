"""条件分支的**保存期**语义：分支出口、谓词形状、依赖限定语法与拓扑基准。

运行期语义（谁执行、谁跳过、走哪条边）在 ``test_runner_conditions.py``。这个文件
只盯一件事：定义说不清楚时能不能在保存时被拦下来。条件分支最贵的 bug 不是「算
错了」，而是「定义本身无解」——缺兜底、指向一个永远不会到达的出口、谓词读同层
并行分支——这些都要在保存期拒绝，而不是等运行到一半静默跳过下游。
"""

from __future__ import annotations

import pytest

from app.modules.workflows.validators import (
    MAX_CONDITION_BRANCHES,
    MAX_PREDICATE_CHILDREN,
    MAX_PREDICATE_DEPTH,
    MAX_REGEX_LENGTH,
    compile_definition,
    execution_layers,
    steps_from_definition,
    validate_definition,
    validate_steps,
)
from app.shared.exceptions import BadRequestException
from helpers import agent_step, condition_step, output_ref


def _branching_steps() -> list[dict]:
    """入口 → 条件闸门（yes/no）→ 两条互斥分支。"""

    return [
        agent_step("entry", prompt="给个结论"),
        condition_step(
            "gate",
            depends_on=["entry"],
            branches=[
                {
                    "name": "yes",
                    "when": {
                        "op": "contains",
                        "left": output_ref("entry"),
                        "right": "同意",
                        "children": None,
                    },
                },
                {"name": "no", "when": None},
            ],
        ),
        agent_step("on_yes", depends_on=["gate@yes"], prompt="按同意的方向执行"),
        agent_step("on_no", depends_on=["gate@no"], prompt="按否决的方向执行"),
    ]


def test_condition_compiles_edges_with_branch_handles() -> None:
    """验收 1：分支出口落到边的 ``source_handle``，edge_id 具名出口带后缀。"""

    definition = compile_definition(_branching_steps())
    edges = {edge["edge_id"]: edge for edge in definition["edges"]}

    assert edges["entry->gate"]["source_handle"] == "default"
    assert edges["gate:yes->on_yes"]["source_handle"] == "yes"
    assert edges["gate:no->on_no"]["source_handle"] == "no"
    # 条件步骤的分支是定义的一部分，必须随定义一起存下来（运行期判定的依据）。
    gate = next(node for node in definition["nodes"] if node["step_id"] == "gate")
    assert [branch["name"] for branch in gate["branches"]] == ["yes", "no"]


def test_condition_definition_round_trips_through_snapshot() -> None:
    """验收 1：compile → steps_from_definition 逐字还原（快照不失真）。"""

    steps = _branching_steps()
    definition = compile_definition(steps)

    assert steps_from_definition(definition) == steps
    assert validate_definition(definition, max_steps=50) == steps


def test_execution_layers_ignore_handles_for_topology() -> None:
    """出口只决定「何时到达」，不改变「谁是上游」：分层仍按基础 step_id。"""

    layers = execution_layers(_branching_steps())

    assert [[step["step_id"] for step in layer] for layer in layers] == [
        ["entry"],
        ["gate"],
        ["on_yes", "on_no"],
    ]


def test_depends_on_accepts_a_declared_branch() -> None:
    assert validate_steps(_branching_steps(), max_steps=50) is None


def test_depends_on_rejects_an_unknown_branch() -> None:
    steps = _branching_steps()
    steps[2] = agent_step("on_yes", depends_on=["gate@maybe"], prompt="x")

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    message = str(error.value)
    assert "'gate@maybe'" in message
    assert "uses an outlet that step 'gate' never reaches" in message
    assert "available: ['no', 'yes']" in message


def test_depends_on_rejects_the_failed_outlet_of_a_plain_step() -> None:
    """``@failed`` 只对声明了 fail_branch 的上游存在，普通步骤上没有这个出口。"""

    steps = _branching_steps()
    steps.append(agent_step("after", depends_on=["on_yes@failed"], prompt="x"))

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    message = str(error.value)
    assert "'on_yes@failed'" in message
    assert "never reaches" in message
    assert "available: ['default']" in message


def test_depends_on_accepts_the_failed_outlet_of_a_fail_branch_step() -> None:
    steps = _branching_steps()
    steps[2] = agent_step(
        "on_yes", depends_on=["gate@yes"], prompt="x", on_error="fail_branch"
    )
    steps.append(agent_step("rescue", depends_on=["on_yes@failed"], prompt="补救"))

    assert validate_steps(steps, max_steps=50) is None


def test_depends_on_treats_a_default_suffix_as_a_duplicate() -> None:
    """``a`` 与 ``a@default`` 是同一条边，不能编译出两条 edge_id 相同的边。"""

    steps = _branching_steps()
    steps.append(agent_step("dup", depends_on=["entry", "entry@default"], prompt="x"))

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "duplicated dependency: entry@default" in str(error.value)


def test_depends_on_rejects_an_empty_handle() -> None:
    steps = _branching_steps()
    steps[2] = agent_step("on_yes", depends_on=["gate@"], prompt="x")

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "has an empty handle in depends_on: gate@" in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"prompt": "直接回答"}, "cannot declare prompt"),
        ({"tool_name": "echo"}, "cannot declare tool_name"),
        ({"agent_id": 1}, "cannot declare agent_id"),
        ({"input_bindings": {"a": ["b", "output"]}}, "cannot declare input_bindings"),
        ({"tool_arguments": {"text": "x"}}, "cannot declare tool_arguments"),
        ({"on_error": "continue_with_default"}, "can only use on_error=abort"),
        ({"on_error": "fail_branch"}, "can only use on_error=abort"),
        ({"default_output": "兜底"}, "cannot declare default_output"),
        ({"max_retries": 2}, "cannot declare max_retries"),
        ({"timeout_seconds": 60}, "cannot declare timeout_seconds"),
    ],
)
def test_condition_step_rejects_an_execution_body(
    overrides: dict, fragment: str
) -> None:
    """条件步骤没有执行体：任何执行体字段都是误配，不是「无副作用地忽略」。"""

    steps = [agent_step("entry", prompt="x"), condition_step("gate", **overrides)]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert fragment in str(error.value)


def test_plain_step_rejects_branches() -> None:
    steps = [agent_step("entry", prompt="x", branches=[{"name": "yes", "when": None}])]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "is not a condition step and cannot declare branches" in str(error.value)


def test_condition_step_requires_at_least_one_branch() -> None:
    steps = [agent_step("entry", prompt="x"), condition_step("gate", branches=[])]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "requires at least one branch" in str(error.value)


def test_condition_step_rejects_too_many_branches() -> None:
    branches = [
        {"name": f"b{index}", "when": None}
        for index in range(MAX_CONDITION_BRANCHES + 1)
    ]
    steps = [agent_step("entry", prompt="x"), condition_step("gate", branches=branches)]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert f"exceeds MAX_CONDITION_BRANCHES {MAX_CONDITION_BRANCHES}" in str(
        error.value
    )


def test_condition_step_requires_a_fallback_branch() -> None:
    """没有兜底 = 所有谓词都不成立时这一步无路可走，下游被静默跳过。"""

    steps = [
        agent_step("entry", prompt="x"),
        condition_step(
            "gate",
            branches=[
                {
                    "name": "yes",
                    "when": {
                        "op": "not_empty",
                        "left": output_ref("entry"),
                        "right": None,
                        "children": None,
                    },
                }
            ],
        ),
    ]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "requires exactly one unconditional fallback branch" in str(error.value)


def test_condition_step_rejects_two_fallbacks() -> None:
    steps = [
        agent_step("entry", prompt="x"),
        condition_step(
            "gate",
            branches=[{"name": "a", "when": None}, {"name": "b", "when": None}],
        ),
    ]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "more than one unconditional branch" in str(error.value)


def test_condition_step_requires_the_fallback_last() -> None:
    """兜底排在前面会让后面的具名分支永远不可达——那是写错顺序，不是风格问题。"""

    steps = [
        agent_step("entry", prompt="x"),
        condition_step(
            "gate",
            branches=[
                {"name": "fallback", "when": None},
                {
                    "name": "yes",
                    "when": {
                        "op": "not_empty",
                        "left": output_ref("entry"),
                        "right": None,
                        "children": None,
                    },
                },
            ],
        ),
    ]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    message = str(error.value)
    assert "fallback branch must be the last one" in message
    assert "'fallback' is at #1" in message


@pytest.mark.parametrize(
    ("branches", "fragment"),
    [
        ([{"name": "default", "when": None}], "is reserved for the implicit outlet"),
        ([{"name": "failed", "when": None}], "is reserved for the implicit outlet"),
        (
            [{"name": "a b", "when": None}, {"name": "a b", "when": None}],
            "invalid name",
        ),
        (
            [{"name": "yes", "when": None}, {"name": "yes", "when": None}],
            "duplicated branch name: yes",
        ),
    ],
)
def test_condition_step_rejects_bad_branch_names(
    branches: list[dict], fragment: str
) -> None:
    steps = [agent_step("entry", prompt="x"), condition_step("gate", branches=branches)]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert fragment in str(error.value)


def _gate_with(predicate: dict) -> list[dict]:
    """入口 → 条件闸门（一个具名分支 + 兜底），具名分支用给定谓词。"""

    return [
        agent_step("entry", prompt="x"),
        condition_step(
            "gate",
            depends_on=["entry"],
            branches=[{"name": "yes", "when": predicate}, {"name": "no", "when": None}],
        ),
    ]


def test_condition_predicate_cannot_read_a_later_step() -> None:
    """谓词与提示词同一条规则：引用只能是上游，否则保存期的靠后步骤会被提前读。"""

    steps = _gate_with(
        {
            "op": "not_empty",
            "left": output_ref("later"),
            "right": None,
            "children": None,
        }
    )
    steps.append(agent_step("later", depends_on=["gate@yes"], prompt="x"))

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "which is not an upstream step" in str(error.value)


def test_condition_predicate_cannot_read_a_parallel_branch() -> None:
    """同层并行分支互不可读：谓词里读它会让执行顺序变成隐藏依赖。"""

    steps = [
        agent_step("entry", prompt="x"),
        agent_step("left", depends_on=["entry"], prompt="左"),
        agent_step("right", depends_on=["entry"], prompt="右"),
        condition_step(
            "gate",
            depends_on=["left"],
            branches=[
                {
                    "name": "yes",
                    "when": {
                        "op": "not_empty",
                        "left": output_ref("right"),
                        "right": None,
                        "children": None,
                    },
                },
                {"name": "no", "when": None},
            ],
        ),
    ]

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert "which is not an upstream step" in str(error.value)


@pytest.mark.parametrize(
    ("predicate", "fragment"),
    [
        (
            {
                "op": "roughly",
                "left": output_ref("entry"),
                "right": "x",
                "children": None,
            },
            "has an unknown predicate op: roughly",
        ),
        (
            {"op": "equals", "left": None, "right": "x", "children": None},
            "requires a left operand",
        ),
        (
            {"op": "equals", "left": "entry.output", "right": "x", "children": None},
            "left must be exactly one reference",
        ),
        (
            {"op": "equals", "left": "{{entry.raw}}", "right": "x", "children": None},
            "predicate path must be 'output'",
        ),
        (
            {
                "op": "equals",
                "left": output_ref("entry"),
                "right": None,
                "children": None,
            },
            "requires a non-empty right operand",
        ),
        (
            {
                "op": "not_empty",
                "left": output_ref("entry"),
                "right": "x",
                "children": None,
            },
            "does not take a right operand",
        ),
        (
            {
                "op": "equals",
                "left": output_ref("entry"),
                "right": "x",
                "children": [{"op": "not_empty", "left": output_ref("entry")}],
            },
            "is a comparison and cannot declare children",
        ),
        (
            {"op": "all", "left": output_ref("entry"), "children": []},
            "is a combinator and cannot declare left/right",
        ),
        (
            {"op": "all", "children": []},
            "requires a non-empty children list",
        ),
        (
            {
                "op": "not",
                "children": [
                    {"op": "not_empty", "left": output_ref("entry")},
                    {"op": "not_empty", "left": output_ref("entry")},
                ],
            },
            "predicate 'not' takes exactly one child, got 2",
        ),
        (
            {
                "op": "matches",
                "left": output_ref("entry"),
                "right": "(unclosed",
                "children": None,
            },
            "has an invalid regular expression",
        ),
        (
            {
                "op": "matches",
                "left": output_ref("entry"),
                "right": "a" * (MAX_REGEX_LENGTH + 1),
                "children": None,
            },
            f"pattern exceeds MAX_REGEX_LENGTH {MAX_REGEX_LENGTH}",
        ),
    ],
)
def test_condition_predicate_rejects_bad_shapes(predicate: dict, fragment: str) -> None:
    steps = _gate_with(predicate)

    with pytest.raises(BadRequestException) as error:
        validate_steps(steps, max_steps=50)

    assert fragment in str(error.value)


def _nested_predicate(depth: int) -> dict:
    node: dict = {"op": "not_empty", "left": output_ref("entry"), "children": None}
    for _ in range(depth):
        node = {"op": "all", "children": [node]}
    return node


def test_condition_predicate_accepts_nesting_at_the_limit() -> None:
    assert (
        validate_steps(
            _gate_with(_nested_predicate(MAX_PREDICATE_DEPTH - 1)), max_steps=50
        )
        is None
    )


def test_condition_predicate_rejects_nesting_beyond_the_limit() -> None:
    """all/any 可以互套，不设上限就是一个递归炸弹。"""

    with pytest.raises(BadRequestException) as error:
        validate_steps(_gate_with(_nested_predicate(MAX_PREDICATE_DEPTH)), max_steps=50)

    assert f"nesting exceeds MAX_PREDICATE_DEPTH {MAX_PREDICATE_DEPTH}" in str(
        error.value
    )


def test_condition_predicate_rejects_too_many_children() -> None:
    children = [
        {"op": "not_empty", "left": output_ref("entry"), "children": None}
        for _ in range(MAX_PREDICATE_CHILDREN + 1)
    ]

    with pytest.raises(BadRequestException) as error:
        validate_steps(_gate_with({"op": "any", "children": children}), max_steps=50)

    assert f"exceeds MAX_PREDICATE_CHILDREN {MAX_PREDICATE_CHILDREN}" in str(
        error.value
    )


def test_edge_consistency_compares_handles_too() -> None:
    """边集必须与 depends_on 的 ``(source, handle, target)`` 三元组一致。

    只比 ``(source, target)`` 会漏掉「把 yes 分支的边接到 no 出口上」——那正好是
    条件分支最危险的一种抄错。
    """

    definition = compile_definition(_branching_steps())
    for edge in definition["edges"]:
        if edge["edge_id"] == "gate:yes->on_yes":
            edge["source_handle"] = "no"

    with pytest.raises(BadRequestException) as error:
        validate_definition(definition, max_steps=50)

    message = str(error.value)
    assert "edges do not match depends_on" in message
    assert "gate:yes->on_yes" in message
    assert "gate:no->on_yes" in message


def test_absent_children_is_normalized_away_on_save() -> None:
    """锁：省略 ``children`` 的请求不会把 ``children: None`` 落进定义快照。

    前端保存比较算子时不带 ``children`` 键，而后端 ``model_dump()`` 会把它补成
    ``None``。若原样落库，读侧就拿到「有这个键、值是 null」的谓词：前端按
    「有没有 children 键」区分组合算子与比较算子，于是把 null 当子条件列表用，
    渲染时 ``.map`` 直接抛错、保存校验还会误判成「比较算子带了子条件」。
    所以保存期必须把两种写法归一成同一种形状。
    """

    steps = _branching_steps()
    gate = next(step for step in steps if step["step_id"] == "gate")
    gate["branches"][0]["when"]["children"] = None

    validate_steps(steps, max_steps=50)
    saved = next(
        node for node in compile_definition(steps)["nodes"] if node["step_id"] == "gate"
    )
    assert "children" not in saved["branches"][0]["when"]

    # 组合算子的子条件同样要递归归一化，否则崩的是嵌套层的渲染。
    nested = _branching_steps()
    nested_gate = next(step for step in nested if step["step_id"] == "gate")
    nested_gate["branches"][0]["when"] = {
        "op": "all",
        "children": [
            {"op": "not_empty", "left": output_ref("entry"), "children": None}
        ],
    }

    validate_steps(nested, max_steps=50)
    nested_saved = next(
        node
        for node in compile_definition(nested)["nodes"]
        if node["step_id"] == "gate"
    )
    assert "children" not in nested_saved["branches"][0]["when"]["children"][0]
