"""工作流定义静态校验的用例（spec 验收第 2、5 条）。

``validators.py`` 是纯函数模块，不碰库、不调模型，所以这里的用例都只做数据比对。
核心语义：**引用只能指向排在它前面的步骤**，且这条规则必须在保存时判定——
等运行到一半才发现「第三步引用了第五步」，代价是一次已经发生的副作用。
"""

from __future__ import annotations

import pytest

from app.modules.workflows.validators import (
    MAX_STEP_NAME_LENGTH,
    MAX_STEP_RETRIES,
    MAX_VISIBLE_OUTPUT_BYTES,
    TRUNCATION_MARKER,
    compile_definition,
    is_truncated,
    steps_from_definition,
    truncate_output,
    validate_definition,
    validate_steps,
)
from app.shared.exceptions import BadRequestException
from helpers import agent_step, tool_step

NODE_KEYS = {
    "step_id",
    "name",
    "kind",
    "seq",
    "depends_on",
    "position",
    "agent_id",
    "prompt",
    "tool_name",
    "tool_arguments",
    "input_bindings",
    "on_error",
    "max_retries",
    "default_output",
    "timeout_seconds",
}


def test_compile_definition_round_trip_locks_node_and_edge_shape() -> None:
    """锁：compile_definition → steps_from_definition 往返一致；node 字段完整；
    边只连相邻步骤、edge_id 形如 ``a->b``、source_handle 恒为 ``default``。"""

    steps = [
        agent_step("collect"),
        tool_step("query", "orders.get_status"),
        agent_step("notify"),
    ]
    definition = compile_definition(steps)

    nodes = definition["nodes"]
    assert [node["step_id"] for node in nodes] == ["collect", "query", "notify"]
    assert [node["seq"] for node in nodes] == [0, 1, 2]
    # 每个 node 的键必须齐全：runner 直接按这些键取值，缺键就是运行时 KeyError。
    for node in nodes:
        assert set(node) == NODE_KEYS
    assert nodes[1]["kind"] == "tool" and nodes[1]["tool_name"] == "orders.get_status"

    assert definition["edges"] == [
        {
            "edge_id": "collect->query",
            "source": "collect",
            "target": "query",
            "source_handle": "default",
        },
        {
            "edge_id": "query->notify",
            "source": "query",
            "target": "notify",
            "source_handle": "default",
        },
    ]

    # 往返一致：定义是运行期唯一的执行依据，还原丢了字段就等于运行结果不可复现。
    assert steps_from_definition(definition) == steps


def test_compile_definition_fills_defaults_for_missing_keys() -> None:
    """锁：编译时对缺省字段兜底（tool_arguments/input_bindings 为 {}、on_error 为 abort）。"""

    definition = compile_definition(
        [
            {
                "step_id": "only",
                "name": "只有必填字段",
                "kind": "agent",
                "prompt": "干点活",
            }
        ]
    )
    node = definition["nodes"][0]
    assert node["agent_id"] is None
    assert node["tool_name"] is None
    assert node["tool_arguments"] == {}
    assert node["input_bindings"] == {}
    assert node["on_error"] == "abort"
    # 重试次数缺省为 0：缺键时 runner 会读成「不重试」，node 里补 0 让定义自解释。
    assert node["max_retries"] == 0
    assert node["default_output"] is None
    assert node["timeout_seconds"] is None
    assert definition["edges"] == []


def test_steps_from_definition_sorts_by_seq_not_list_order() -> None:
    """锁：还原按 ``seq`` 排序，而不是 JSON 里的数组顺序。

    ``definition`` 是 JSON 列，键顺序与数组顺序都不该被当作执行顺序。
    """

    definition = {
        "nodes": [
            {
                "step_id": "second",
                "name": "二",
                "kind": "agent",
                "prompt": "p",
                "seq": 1,
            },
            {
                "step_id": "first",
                "name": "一",
                "kind": "agent",
                "prompt": "p",
                "seq": 0,
            },
        ],
        "edges": [],
    }
    assert [step["step_id"] for step in steps_from_definition(definition)] == [
        "first",
        "second",
    ]


@pytest.mark.parametrize(
    ("steps", "max_steps", "expected"),
    [
        ([], 50, "workflow requires at least one step"),
        (
            [agent_step("a"), agent_step("b")],
            1,
            "workflow step count 2 exceeds max_steps 1",
        ),
        ([agent_step("bad id")], 50, "invalid step_id"),
        ([agent_step("dup"), agent_step("dup")], 50, "duplicated step_id: dup"),
        ([agent_step("a", name="   ")], 50, "requires a name"),
        (
            [agent_step("a", name="x" * (MAX_STEP_NAME_LENGTH + 1))],
            50,
            "name exceeds 200 characters",
        ),
        ([agent_step("a", kind="llm")], 50, "has an unknown kind: llm"),
        ([agent_step("a", prompt="   ")], 50, "is an agent step and requires a prompt"),
        (
            [agent_step("a", tool_name="orders.get")],
            50,
            "is an agent step and cannot declare a tool",
        ),
        (
            [agent_step("a", input_bindings={"x": ["b", "output"]})],
            50,
            "is an agent step and cannot declare input_bindings",
        ),
        ([tool_step("a", "")], 50, "is a tool step and requires a tool_name"),
        (
            [tool_step("a", "orders.get", prompt="帮我查")],
            50,
            "is a tool step and cannot declare a prompt",
        ),
        ([agent_step("a", on_error="explode")], 50, "has an unknown on_error: explode"),
        (
            [agent_step("a", on_error="continue_with_default")],
            50,
            "uses on_error=continue_with_default and requires default_output",
        ),
        (
            [agent_step("a", on_error="continue_with_default", default_output="   ")],
            50,
            "uses on_error=continue_with_default and requires default_output",
        ),
        (
            [agent_step("a", max_retries=MAX_STEP_RETRIES + 1)],
            50,
            "max_retries must be between 0 and 5",
        ),
        (
            [agent_step("a", max_retries=-1)],
            50,
            "max_retries must be between 0 and 5",
        ),
        (
            [agent_step("a", max_retries="2")],
            50,
            "has a non-integer max_retries",
        ),
        (
            # bool 是 int 的子类：不显式排除的话 True 会被当成 1 次重试悄悄放行。
            [agent_step("a", max_retries=True)],
            50,
            "has a non-integer max_retries",
        ),
    ],
)
def test_validate_steps_rejects_invalid_shapes(steps, max_steps, expected) -> None:
    """锁：步骤形状的每一条保存期拒绝规则（含 step_id 重复与 max_steps）。"""

    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=max_steps)
    assert expected in str(excinfo.value)


def test_validate_steps_accepts_a_fully_valid_list() -> None:
    """锁：一组合法步骤（agent + tool + 兜底策略）不被误杀。"""

    steps = [
        agent_step("collect", prompt="总结工单"),
        tool_step(
            "query",
            "orders.get_status",
            input_bindings={"order": ["collect", "output"]},
        ),
        agent_step(
            "notify",
            prompt="根据 {{query.output}} 通知用户",
            on_error="continue_with_default",
            default_output="通知失败",
        ),
    ]
    assert validate_steps(steps, max_steps=50) is None


def test_validate_steps_accepts_max_retries_at_the_boundary() -> None:
    """锁（Q6 每步重试）：0 与上限都合法，编译与还原都要留住这个值。"""

    assert validate_steps([agent_step("a", max_retries=0)], max_steps=50) is None
    assert (
        validate_steps([agent_step("a", max_retries=MAX_STEP_RETRIES)], max_steps=50)
        is None
    )

    definition = compile_definition([agent_step("a", max_retries=2)])
    assert definition["nodes"][0]["max_retries"] == 2
    assert steps_from_definition(definition)[0]["max_retries"] == 2


def test_validate_steps_accepts_fail_branch_enum_without_implementing_it() -> None:
    """锁：``fail_branch`` 在枚举里占位，保存期放行；v1 只有 runner 侧行为差异。

    这是「代码实际行为」而不是文档承诺：``ON_ERROR_STRATEGIES`` 含三档，
    ``IMPLEMENTED_ON_ERROR_STRATEGIES`` 只有两档，validate_steps 用的是前者。
    """

    steps = [agent_step("a", on_error="fail_branch")]
    assert validate_steps(steps, max_steps=50) is None


def test_validate_steps_rejects_binding_to_a_later_step() -> None:
    """锁（验收 2）：``input_bindings`` 选择器指向**非上游**的步骤必须被拒。

    改造后执行顺序不再等于数组顺序，判定口径从「排在前面」升级为「是上游
    （直接或间接依赖）」：同层并行分支之间互不可见，正是靠这条拦住的。
    """

    steps = [
        tool_step(
            "first", "orders.get_status", input_bindings={"order": ["second", "output"]}
        ),
        tool_step("second", "orders.get_status"),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert (
        "input binding 'order' references 'second', which is not an upstream step"
        in str(excinfo.value)
    )


def test_validate_steps_rejects_binding_to_itself() -> None:
    """锁：自引用也属于「不是上游步骤」。"""

    steps = [
        tool_step("only", "orders.get_status", input_bindings={"x": ["only", "output"]})
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert "which is not an upstream step" in str(excinfo.value)


def test_validate_steps_accepts_binding_to_an_earlier_step() -> None:
    """锁（验收 2 反向）：指向更早步骤的选择器通过。"""

    steps = [
        agent_step("first"),
        tool_step(
            "second", "orders.get_status", input_bindings={"x": ["first", "output"]}
        ),
    ]
    assert validate_steps(steps, max_steps=50) is None


def test_validate_steps_rejects_template_reference_to_a_later_step() -> None:
    """锁（验收 2）：提示词里 ``{{step.output}}`` 引用非上游步骤必须被拒。"""

    steps = [
        agent_step("first", prompt="请使用 {{second.output}}"),
        agent_step("second"),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert "template references 'second', which is not an upstream step" in str(
        excinfo.value
    )


def test_validate_steps_accepts_template_reference_to_an_earlier_step() -> None:
    """锁（验收 2 反向）：引用前面步骤的提示词模板通过。"""

    steps = [
        agent_step("first"),
        agent_step("second", prompt="请使用 {{ first.output }} 继续"),
    ]
    assert validate_steps(steps, max_steps=50) is None


def test_validate_steps_rejects_template_reference_inside_tool_arguments() -> None:
    """锁：模板引用校验覆盖 tool_arguments 里的递归字符串叶子。"""

    steps = [
        agent_step("first"),
        tool_step(
            "second",
            "orders.get_status",
            tool_arguments={"note": ["{{third.output}}"]},
        ),
        tool_step("third", "orders.get_status"),
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_steps(steps, max_steps=50)
    assert "template references 'third'" in str(excinfo.value)


def test_validate_steps_rejects_unknown_output_path_at_save_time() -> None:
    """锁：保存期就拒绝 ``output`` 之外的输出路径（模板引用与结构化绑定都算）。

    运行期只发布一个输出名（``validators.OUTPUT_PATH``），多写别的路径在渲染时
    必然失败。与其让用户等到跑起来才炸、把一条失败的运行记录留在库里，
    不如保存时直接拒绝——这条口径与 runner 的渲染检查是同一件事的两道闸。
    """

    template_case = [
        agent_step("first"),
        agent_step("second", prompt="{{first.other}}"),
    ]
    with pytest.raises(BadRequestException) as template_excinfo:
        validate_steps(template_case, max_steps=50)
    assert "template path must be 'output', got 'other'" in str(template_excinfo.value)

    selector_case = [
        agent_step("first"),
        tool_step(
            "second", "orders.get_status", input_bindings={"x": ["first", "other"]}
        ),
    ]
    with pytest.raises(BadRequestException) as selector_excinfo:
        validate_steps(selector_case, max_steps=50)
    assert "input binding 'x' path must be 'output', got 'other'" in str(
        selector_excinfo.value
    )


def test_validate_steps_accepts_the_output_path() -> None:
    """锁：唯一合法的 ``output`` 路径在模板引用与结构化绑定里都能保存。"""

    steps = [
        agent_step("first"),
        agent_step("second", prompt="基于 {{first.output}} 写摘要"),
        tool_step(
            "third", "orders.get_status", input_bindings={"x": ["first", "output"]}
        ),
    ]
    assert validate_steps(steps, max_steps=50) is None


def test_validate_steps_rejects_malformed_selectors() -> None:
    """锁：选择器不是 ``[step_id, path]`` 两元数组时被拒（不是二元/元素非串）。"""

    bad_cases = [
        {"x": "first.output"},
        {"x": ["first"]},
        {"x": ["first", "output", "extra"]},
        {"x": ["", "output"]},
        {"x": ["first", "  "]},
    ]
    for bindings in bad_cases:
        steps = [
            agent_step("first"),
            tool_step("second", "orders.get_status", input_bindings=bindings),
        ]
        with pytest.raises(BadRequestException):
            validate_steps(steps, max_steps=50)


def test_truncate_output_returns_short_text_unchanged() -> None:
    """锁（验收 5）：未超上限原样返回，且不被判为已截断。"""

    text = "一段很短的输出"
    assert truncate_output(text) == text
    assert truncate_output("") == ""
    assert is_truncated(text) is False
    assert is_truncated("") is False
    assert is_truncated(None) is False


def test_truncate_output_boundary_is_50kb_measured_in_bytes() -> None:
    """锁（验收 5）：上限是 50KB **字节**，正好等于上限不截断，多 1 字节才截断。"""

    exact = "a" * MAX_VISIBLE_OUTPUT_BYTES
    assert truncate_output(exact) == exact
    assert is_truncated(exact) is False

    over = truncate_output("a" * (MAX_VISIBLE_OUTPUT_BYTES + 1))
    assert is_truncated(over) is True
    # 截断后的可见部分恰好是上限字节，标记追加在它之后（因此总长会超过上限）。
    assert over == exact + TRUNCATION_MARKER
    assert len(over.encode("utf-8")) == MAX_VISIBLE_OUTPUT_BYTES + len(
        TRUNCATION_MARKER.encode("utf-8")
    )


def test_truncate_output_appends_marker_and_is_truncated_agrees() -> None:
    """锁（验收 5）：截断结果以 ``TRUNCATION_MARKER`` 结尾，``is_truncated`` 与之判定一致。"""

    limit = 64
    text = "b" * (limit * 3)
    result = truncate_output(text, limit=limit)

    assert result.endswith(TRUNCATION_MARKER)
    assert result == "b" * limit + TRUNCATION_MARKER
    assert is_truncated(result) is True
    assert not result.startswith(TRUNCATION_MARKER)


def test_truncate_output_drops_a_broken_multibyte_tail() -> None:
    """锁：按字节截断切坏多字节字符时丢弃残缺字节，不产生替换字符。"""

    limit = 8  # "中" 占 3 字节：前 8 字节 = 两个完整字 + 2 个残缺字节
    result = truncate_output("中" * 10, limit=limit)

    assert result == "中中" + TRUNCATION_MARKER
    assert "\ufffd" not in result
    assert len(result.encode("utf-8")) <= limit + len(TRUNCATION_MARKER.encode("utf-8"))


def test_validate_definition_rejects_edge_to_an_unknown_step() -> None:
    """锁（验收 2）：边指向不存在的 step_id 被拒（运行前的防御性复核）。"""

    definition = compile_definition([agent_step("real")])
    definition["edges"] = [
        {
            "edge_id": "real->ghost",
            "source": "real",
            "target": "ghost",
            "source_handle": "default",
        }
    ]
    with pytest.raises(BadRequestException) as excinfo:
        validate_definition(definition, max_steps=50)
    assert "references an unknown step" in str(excinfo.value)


def test_validate_definition_rejects_non_default_source_handle() -> None:
    """锁：``source_handle`` 非 default 被拒（v1 不实现分支，出现别的出口说明定义被写坏）。"""

    definition = compile_definition([agent_step("first"), agent_step("second")])
    definition["edges"][0]["source_handle"] = "on_failure"
    with pytest.raises(BadRequestException) as excinfo:
        validate_definition(definition, max_steps=50)
    assert "has unsupported source_handle: on_failure" in str(excinfo.value)


def test_validate_definition_accepts_a_compiled_definition() -> None:
    """锁：compile_definition 的产物一定能通过 validate_definition（自洽）。"""

    steps = [agent_step("first"), tool_step("second", "orders.get_status")]
    definition = compile_definition(steps)
    assert validate_definition(definition, max_steps=50) == steps


def test_validate_definition_rejects_empty_or_missing_definition() -> None:
    """锁：空定义（nodes 为空）在运行前被拒，而不是被当成「零步骤顺利跑完」。"""

    with pytest.raises(BadRequestException) as excinfo:
        validate_definition({}, max_steps=50)
    assert "requires at least one step" in str(excinfo.value)

    with pytest.raises(BadRequestException):
        validate_definition(None, max_steps=50)
