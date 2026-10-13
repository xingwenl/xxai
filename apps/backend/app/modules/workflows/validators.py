"""工作流定义的静态校验与输出截断规则。

这些校验必须在**保存时**做完，而不是等运行到一半才炸：工作流的前序步骤
可能已经产生真实副作用（调过工具、发过消息），此时才发现「第三步引用了
第五步」，代价是一次已发生的副作用加一条失败的运行记录。

因此本模块只做纯数据比对，不碰数据库、不调用模型：

- 引用（``input_bindings`` 的 ``value_selector``、提示词里的 ``{{step.path}}``）
  只能指向**排在它前面**的 ``step_id``；
- ``step_id`` 唯一且格式稳定（它会成为历史运行记录的一部分，不能是自增行号）；
- 步骤数不超过 ``max_steps``；
- 边两端的 ``step_id`` 必须存在（边由 ``compile_definition`` 生成，这里做防御性复核）。

依赖数据库的校验（Agent 是否属于本平台、工具是否可用且副作用可自动批准）
在 ``services.py`` 里，与本模块的分工是「纯数据 vs 需要查询」。
"""

from __future__ import annotations

import re
from typing import Any

from app.shared.exceptions import BadRequestException

# 步骤输出双通道的截断上限：与 Pi 的 `PER_TASK_OUTPUT_CAP` 取同一量级。
# 只截断「给模型看」的那一路，完整输出留在 raw_output 里供审计。
MAX_VISIBLE_OUTPUT_BYTES = 50 * 1024

# 截断标记：追加在 model_visible_output 末尾，既可被人看见，也让
# ``is_truncated`` 能用一次后缀比对判断，不必额外加一列。
TRUNCATION_MARKER = "\n\n[输出已截断：以上为可展示部分，完整输出见运行记录详情]"

# 提示词里的引用写法：{{step_id.path}}。只在**渲染层**保留这种写法，
# 结构化输入绑定一律用数组选择器，以便静态校验。
TEMPLATE_REFERENCE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)\.([^{}\s]+?)\s*\}\}")

# step_id 会成为运行记录的一部分，因此限定为可读、可入 URL、可当 JSON key 的字符集。
STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

STEP_KINDS = ("agent", "tool")
ON_ERROR_STRATEGIES = ("abort", "continue_with_default", "fail_branch")
# v1 落地的失败策略；fail_branch 依赖边上的 source_handle，枚举值先占住、行为后加。
IMPLEMENTED_ON_ERROR_STRATEGIES = ("abort", "continue_with_default")

# 单步额外重试次数上限：重试会重复消耗模型调用与工具副作用，宁少勿多。
MAX_STEP_RETRIES = 5

# Agent 步骤的最小长度约束：空指令会让这一步毫无意义地消耗一次模型调用。
MAX_STEP_NAME_LENGTH = 200


def truncate_output(text: str, *, limit: int = MAX_VISIBLE_OUTPUT_BYTES) -> str:
    """把输出截断到上限并打标；未超限时原样返回。"""

    if len(text.encode("utf-8")) <= limit:
        return text
    # 按字节截断后可能切坏多字节字符，用 ignore 丢弃残缺字节。
    clipped = text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
    return clipped + TRUNCATION_MARKER


def is_truncated(text: str | None) -> bool:
    """判断一段模型可见输出是否被截断过（靠固定的尾部标记）。"""

    return bool(text) and text.endswith(TRUNCATION_MARKER)


def compile_definition(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """把有序步骤列表编译成 ``{nodes, edges}`` 定义。

    边只连接相邻步骤（步骤恒为线性），且一律带 ``source_handle: "default"``：
    这个字段是给日后的条件分支占位的，v1 不产生别的取值。
    """

    nodes: list[dict[str, Any]] = []
    for seq, step in enumerate(steps):
        nodes.append(
            {
                "step_id": step["step_id"],
                "name": step["name"],
                "kind": step["kind"],
                "seq": seq,
                "agent_id": step.get("agent_id"),
                "prompt": step.get("prompt"),
                "tool_name": step.get("tool_name"),
                "tool_arguments": step.get("tool_arguments") or {},
                "input_bindings": step.get("input_bindings") or {},
                "on_error": step.get("on_error") or "abort",
                "max_retries": int(step.get("max_retries") or 0),
                "default_output": step.get("default_output"),
                "timeout_seconds": step.get("timeout_seconds"),
            }
        )

    edges = [
        {
            "edge_id": f"{nodes[index]['step_id']}->{nodes[index + 1]['step_id']}",
            "source": nodes[index]["step_id"],
            "target": nodes[index + 1]["step_id"],
            "source_handle": "default",
        }
        for index in range(len(nodes) - 1)
    ]
    return {"nodes": nodes, "edges": edges}


def steps_from_definition(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从 ``{nodes, edges}`` 定义还原出按执行顺序排列的步骤列表。"""

    nodes = list((definition or {}).get("nodes") or [])
    nodes.sort(key=lambda node: int(node.get("seq") or 0))
    return [
        {
            "step_id": node.get("step_id"),
            "name": node.get("name"),
            "kind": node.get("kind"),
            "agent_id": node.get("agent_id"),
            "prompt": node.get("prompt"),
            "tool_name": node.get("tool_name"),
            "tool_arguments": node.get("tool_arguments") or {},
            "input_bindings": node.get("input_bindings") or {},
            "on_error": node.get("on_error") or "abort",
            "max_retries": int(node.get("max_retries") or 0),
            "default_output": node.get("default_output"),
            "timeout_seconds": node.get("timeout_seconds"),
        }
        for node in nodes
    ]


def validate_steps(steps: list[dict[str, Any]], *, max_steps: int) -> None:
    """校验步骤列表；不合法时抛 ``BadRequestException``。

    ``steps`` 的顺序就是执行顺序，因此「引用只能指向前面」这条规则可以
    只靠一次顺序遍历判定，不需要建图。
    """

    if not steps:
        raise BadRequestException("workflow requires at least one step")
    if len(steps) > max_steps:
        raise BadRequestException(
            f"workflow step count {len(steps)} exceeds max_steps {max_steps}"
        )

    seen: set[str] = set()
    for index, step in enumerate(steps):
        step_id = step.get("step_id")
        label = f"step #{index + 1}"
        if not isinstance(step_id, str) or not STEP_ID_PATTERN.match(step_id):
            raise BadRequestException(
                f"{label} has an invalid step_id: must match [A-Za-z0-9_-]{{1,64}}"
            )
        if step_id in seen:
            raise BadRequestException(f"duplicated step_id: {step_id}")
        label = f"step '{step_id}'"

        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BadRequestException(f"{label} requires a name")
        if len(name) > MAX_STEP_NAME_LENGTH:
            raise BadRequestException(
                f"{label} name exceeds {MAX_STEP_NAME_LENGTH} characters"
            )

        kind = step.get("kind")
        if kind not in STEP_KINDS:
            raise BadRequestException(f"{label} has an unknown kind: {kind}")
        if kind == "agent":
            prompt = step.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise BadRequestException(f"{label} is an agent step and requires a prompt")
            if step.get("tool_name"):
                raise BadRequestException(f"{label} is an agent step and cannot declare a tool")
            if step.get("input_bindings"):
                # Agent 步骤从提示词里取数（``{{step.output}}``），工具步骤才用
                # input_bindings 拼参数。两种传值方式各自对应一种步骤，混用会被
                # 运行时静默忽略——那比直接拒绝更难查，所以在这里拦住。
                raise BadRequestException(
                    f"{label} is an agent step and cannot declare input_bindings; "
                    "reference previous steps in the prompt instead"
                )
        else:
            tool_name = step.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise BadRequestException(f"{label} is a tool step and requires a tool_name")
            if step.get("prompt"):
                raise BadRequestException(f"{label} is a tool step and cannot declare a prompt")

        on_error = step.get("on_error") or "abort"
        if on_error not in ON_ERROR_STRATEGIES:
            raise BadRequestException(f"{label} has an unknown on_error: {on_error}")
        max_retries = step.get("max_retries")
        if max_retries is not None:
            # 定义快照来自数据库，绕过了 pydantic 的范围约束，运行时必须自己再验一遍。
            if not isinstance(max_retries, int) or isinstance(max_retries, bool):
                raise BadRequestException(f"{label} has a non-integer max_retries")
            if not 0 <= max_retries <= MAX_STEP_RETRIES:
                raise BadRequestException(
                    f"{label} max_retries must be between 0 and {MAX_STEP_RETRIES}"
                )
        if on_error == "continue_with_default" and not (
            step.get("default_output") or ""
        ).strip():
            # 没有兜底值却声明「失败也继续」，运行时只会有两条出路：
            # 拿空字符串污染后续步骤，或者偷偷改成中止。两者都是隐性行为。
            raise BadRequestException(
                f"{label} uses on_error=continue_with_default and requires default_output"
            )

        _validate_input_bindings(step, seen=seen, label=label)
        _validate_template_references(step, seen=seen, label=label)
        seen.add(step_id)

    _validate_edges(seen, definition=None)


def validate_definition(
    definition: dict[str, Any] | None, *, max_steps: int
) -> list[dict[str, Any]]:
    """校验一份 ``{nodes, edges}`` 定义，返回还原后的步骤列表。

    运行前的边界检查走这里：定义在数据库里可能已被更早的 bug 写坏，
    不能假设它一定通过过保存时校验。
    """

    steps = steps_from_definition(definition)
    validate_steps(steps, max_steps=max_steps)
    _validate_edges({step["step_id"] for step in steps}, definition=definition)
    return steps


def _validate_input_bindings(
    step: dict[str, Any], *, seen: set[str], label: str
) -> None:
    """输入绑定必须是「[前序 step_id, 输出路径]」形式的数组选择器。"""

    bindings = step.get("input_bindings") or {}
    if not isinstance(bindings, dict):
        raise BadRequestException(f"{label} has invalid input_bindings: must be an object")
    for name, selector in bindings.items():
        if not isinstance(name, str) or not name.strip():
            raise BadRequestException(f"{label} has an empty input binding name")
        # 数组选择器而不是字符串模板：这里做的是纯数据比对，
        # 校验「只能引用前面的步骤」不需要写解析器。
        if not isinstance(selector, list) or len(selector) != 2:
            raise BadRequestException(
                f"{label} input binding '{name}' must be [step_id, path]"
            )
        source_id, path = selector
        if not isinstance(source_id, str) or not source_id:
            raise BadRequestException(
                f"{label} input binding '{name}' has an empty step_id"
            )
        if not isinstance(path, str) or not path.strip():
            raise BadRequestException(
                f"{label} input binding '{name}' has an empty output path"
            )
        if source_id not in seen:
            raise BadRequestException(
                f"{label} input binding '{name}' references '{source_id}', "
                "which is not an earlier step"
            )


def _validate_template_references(
    step: dict[str, Any], *, seen: set[str], label: str
) -> None:
    """提示词/参数模板里的 ``{{step_id.path}}`` 也只能指向前序步骤。

    保存时就拦住，而不是等渲染时把一个未替换的占位符发给模型。
    """

    for text in _template_texts(step):
        for source_id, _path in TEMPLATE_REFERENCE_PATTERN.findall(text):
            if source_id not in seen:
                raise BadRequestException(
                    f"{label} template references '{source_id}', "
                    "which is not an earlier step"
                )


def _template_texts(step: dict[str, Any]) -> list[str]:
    """收集一份步骤里所有可能出现模板引用的字符串值。"""

    texts: list[str] = []
    prompt = step.get("prompt")
    if isinstance(prompt, str):
        texts.append(prompt)
    default_output = step.get("default_output")
    if isinstance(default_output, str):
        texts.append(default_output)
    texts.extend(_collect_strings(step.get("tool_arguments")))
    return texts


def _collect_strings(value: Any) -> list[str]:
    """递归收集任意 JSON 结构里的字符串叶子。"""

    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for item in value.values():
            collected.extend(_collect_strings(item))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_collect_strings(item))
        return collected
    return []


def _validate_edges(step_ids: set[str], *, definition: dict[str, Any] | None) -> None:
    """复核边两端都指向存在的步骤，且边的出口值只有 ``default``。"""

    if definition is None:
        return
    for edge in definition.get("edges") or []:
        source = edge.get("source")
        target = edge.get("target")
        if source not in step_ids or target not in step_ids:
            raise BadRequestException(
                f"edge {edge.get('edge_id')} references an unknown step: {source}->{target}"
            )
        handle = edge.get("source_handle") or "default"
        if handle != "default":
            # v1 不实现分支，出现别的出口说明定义被写坏了。
            raise BadRequestException(f"edge {edge.get('edge_id')} has unsupported source_handle: {handle}")
