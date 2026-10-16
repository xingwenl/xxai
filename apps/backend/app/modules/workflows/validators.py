"""工作流定义的静态校验与输出截断规则。

这些校验必须在**保存时**做完，而不是等运行到一半才炸：工作流的前序步骤
可能已经产生真实副作用（调过工具、发过消息），此时才发现「第三步引用了
第五步」，代价是一次已发生的副作用加一条失败的运行记录。

因此本模块只做纯数据比对，不碰数据库、不调用模型：

- 定义是一张 **DAG**：每个步骤用 ``depends_on`` 声明它依赖哪些步骤，边由
  依赖编译出来。缺省 ``depends_on`` 表示「依赖序列中的前一个步骤」，因此
  改造前保存的线性定义无需迁移；显式 ``[]`` 表示起点（并行分支的第二条靠
  它声明）。
- 依赖条目可以带**出口后缀** ``"<step_id>@<handle>"``：不带后缀等价于
  ``@default``（成功出口）。``kind="condition"`` 的条件步骤没有 ``default``
  出口，只有自己的具名分支出口；声明了 ``on_error="fail_branch"`` 的步骤额外
  多一个 ``failed`` 出口。这一步能到达哪些出口由 ``declared_handles`` 定义，
  依赖与边都只能引用其中真实存在的出口——指向一个永远不会到达的出口，等于
  让下游静默变成长眠步骤。
- 条件步骤不调模型、不调工具：它声明一组具名分支，**必须恰好有一个**无条件
  兜底分支且排在最后；分支判定是对上游输出的纯数据谓词（``op`` =
  ``equals`` / ``contains`` / ``not_empty`` / ``matches``，可用 ``all`` /
  ``any`` / ``not`` 组合）。
- 引用（``input_bindings`` 的数组选择器、提示词里的 ``{{step.path}}``、谓词
  的 ``left``）只能指向**上游（直接或间接依赖）**的 ``step_id``，且路径只允许
  ``output``。并行分支之间互不可见——这正是「分支不可互读变量」的落点。
- 依赖无环、不指向不存在的步骤、不自引用、不重复；单层并行宽度有上限。
- ``step_id`` 唯一且格式稳定（它会成为历史运行记录的一部分，不能是自增行号）；
- 步骤数不超过 ``max_steps``；
- 边两端的 ``step_id`` 必须存在、出口必须是源步骤真的会到达的出口，且边集
  必须与 ``depends_on`` 推导出的 ``(source, handle, target)`` 三元组集合一致
  （``compile_definition`` 生成边，这里做防御性复核，防止定义被写坏）。

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

# 前序步骤目前唯一能取到的输出路径：该步的「模型可见输出」。
# 结构化绑定与模板引用都只认这一个值——运行期没有别的东西可解析，
# 与其等到渲染时才报「引用不到」，不如保存时就拒绝。
OUTPUT_PATH = "output"

STEP_KINDS = ("agent", "tool", "condition")
ON_ERROR_STRATEGIES = ("abort", "continue_with_default", "fail_branch")

# 依赖条目里的出口后缀分隔符：``"a@branch"`` 表示「依赖 a 的 branch 出口」，
# 不带后缀等价于 ``"a@default"``。
HANDLE_SEPARATOR = "@"
# 隐式出口：步骤成功时到达的出口。条件步骤没有这个出口。
DEFAULT_HANDLE = "default"
# 隐式出口：``on_error="fail_branch"`` 的步骤失败时到达的出口。
FAILED_HANDLE = "failed"
# 分支名不允许占用这两个隐式出口名，否则画布上无法区分「分支」与「成功/失败」。
RESERVED_HANDLES = (DEFAULT_HANDLE, FAILED_HANDLE)

# 单个条件步骤的分支数上限：与单层并行宽度同量级，分支名是要画在画布上的。
MAX_CONDITION_BRANCHES = 8
# 组合谓词的子节点上限：纯数据结构的深度/宽度不该由客户端任意放大。
MAX_PREDICATE_CHILDREN = 16
# 谓词嵌套层数上限：``all``/``any`` 是可以互相套的，不设界就等于让客户端
# 提交一棵任意深的树，保存期校验与运行期求值都会跟着退化成递归炸弹。
MAX_PREDICATE_DEPTH = 4
# 比较类谓词的算子，与 ``all`` / ``any`` / ``not`` 三个组合算子互斥。
PREDICATE_OPS = ("equals", "contains", "not_empty", "matches")
PREDICATE_LOGICAL_OPS = ("all", "any", "not")
# ``matches`` 用的正则长度上限：保存期会 re.compile 预编译，长正则本身既是
# 拒绝服务面，也是「用户其实想干别的」的信号。
MAX_REGEX_LENGTH = 200

# 谓词左操作数的书写形式示例，只用于错误文案，让用户一次就能看懂该写什么。
REFERENCE_EXAMPLE = "{{step_id." + OUTPUT_PATH + "}}"

# 单步额外重试次数上限：重试会重复消耗模型调用与工具副作用，宁少勿多。
MAX_STEP_RETRIES = 5

# Agent 步骤的最小长度约束：空指令会让这一步毫无意义地消耗一次模型调用。
MAX_STEP_NAME_LENGTH = 200

# 单层并行的最大宽度（同一拓扑层里互不依赖、可同时执行的步骤数）。
# 取值对齐本机 Pi 的 `MAX_PARALLEL_TASKS = 8`：并行扇出的代价是同时打模型
# 网关与工具，必须在**定义**层就设一个上界；运行期另有一道更小的并发闸。
MAX_PARALLEL_BRANCHES = 8


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


def split_dependency(entry: str) -> tuple[str, str | None]:
    """把一条依赖条目拆成 ``(step_id, handle)``；没有后缀时 handle 为 ``None``。

    ``None`` 与 ``"default"`` 在前缀处等价，之所以区分保留：``None`` 代表
    「用户没写出口」这个事实，把它原样存回定义才能让存量线性定义逐字不变。
    """

    step_id, separator, handle = entry.partition(HANDLE_SEPARATOR)
    if not separator:
        return step_id, None
    return step_id, handle


def normalize_handle(handle: str | None) -> str:
    """把可选的出口后缀折算成具体出口名：缺省即成功出口。"""

    return handle or DEFAULT_HANDLE


def base_step_id(entry: str) -> str:
    """取一条依赖条目的基础 ``step_id``（剥掉 ``@handle`` 后缀）。

    拓扑分层、环检测、上游范围都按基础 ``step_id`` 计算：出口只决定「这条边
    何时到达」，不改变「谁是上游」。混在一起会让同一对节点因为出口不同而被
    当成两条依赖，分层与祖先判定随之失真。
    """

    return split_dependency(entry)[0]


def edge_id_of(source: str, handle: str, target: str) -> str:
    """边的稳定标识：成功出口沿用改造前的 ``a->b`` 写法，具名出口才带后缀。"""

    normalized = normalize_handle(handle)
    if normalized == DEFAULT_HANDLE:
        return f"{source}->{target}"
    return f"{source}:{normalized}->{target}"


def branch_names(step: dict[str, Any]) -> list[str]:
    """条件步骤声明的分支名（不含隐含语义），其它步骤返回空列表。"""

    if step.get("kind") != "condition":
        return []
    branches = step.get("branches")
    if not isinstance(branches, list):
        return []
    return [
        str(branch.get("name"))
        for branch in branches
        if isinstance(branch, dict) and branch.get("name")
    ]


def declared_handles(step: dict[str, Any]) -> set[str]:
    """一个步骤**真的会到达**的出口集合。

    这是「依赖只能指向真实出口」的唯一判据：条件步骤只有具名分支，
    普通步骤恒有 ``default``，声明了 ``fail_branch`` 的多一个 ``failed``。
    """

    if step.get("kind") == "condition":
        return set(branch_names(step))
    handles = {DEFAULT_HANDLE}
    if (step.get("on_error") or "abort") == "fail_branch":
        handles.add(FAILED_HANDLE)
    return handles


def resolve_depends_on(steps: list[dict[str, Any]]) -> list[list[str]]:
    """把每个步骤的 ``depends_on`` 解析成显式列表。

    约定（这是「存量线性定义零改动兼容」的全部内容）：

    - ``depends_on`` 缺省（``None`` 或键不存在）→ 依赖**序列中的前一个步骤**，
      首步没有依赖。改造前保存的定义就是这种形状。
    - ``depends_on == []`` → 显式声明「不依赖任何步骤」，即一个起点。并行分支
      的第二条及以后必须写它，否则会被当成线性后继。

    元素是**依赖条目原文**（可能带 ``@handle`` 后缀），不是纯 step_id：出口
    信息是执行语义的一部分，在这里剥掉就等于丢掉了「走哪条分支」。
    返回的列表与 ``steps`` 一一对应；元素顺序即步骤声明依赖的顺序。
    """

    resolved: list[list[str]] = []
    for index, step in enumerate(steps):
        declared = step.get("depends_on")
        if declared is None:
            # 缺省 = 串行继任者。首步没有前驱。
            previous = steps[index - 1]["step_id"] if index else None
            resolved.append([previous] if previous is not None else [])
            continue
        if not isinstance(declared, list):
            raise BadRequestException(
                f"step '{step.get('step_id')}' depends_on must be a list of step_id"
            )
        resolved.append(list(declared))
    return resolved


def compile_definition(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """把有序步骤列表编译成 ``{nodes, edges}`` 定义。

    边由 ``depends_on`` 生成，出口取自依赖条目里的 ``@handle`` 后缀（缺省
    ``default``）。``depends_on`` 原样存进 node（缺省仍是 ``None``），这样定义
    能自解释依赖，而线性定义又不需要额外迁移。
    ``branches`` 只在条件步骤上出现：线性/并行定义编译出的 node 键集因此与
    改造前逐字相同，存量定义的快照不会因为这次改造而变形。
    """

    nodes: list[dict[str, Any]] = []
    for seq, step in enumerate(steps):
        node = {
            "step_id": step["step_id"],
            "name": step["name"],
            "kind": step["kind"],
            "seq": seq,
            "depends_on": step.get("depends_on"),
            "position": step.get("position"),
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
        if step.get("branches") is not None:
            node["branches"] = step["branches"]
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    for step, dependencies in zip(steps, resolve_depends_on(steps)):
        for entry in dependencies:
            source, handle = split_dependency(str(entry))
            handle = normalize_handle(handle)
            # 成功出口的 edge_id 保持改造前的写法：它是定义里可读的稳定标识。
            # 具名出口才带上出口名，否则同一对节点的两条分支边会撞 id。
            edge_id = edge_id_of(source, handle, str(step["step_id"]))
            edges.append(
                {
                    "edge_id": edge_id,
                    "source": source,
                    "target": step["step_id"],
                    "source_handle": handle,
                }
            )
    return {"nodes": nodes, "edges": edges}


def steps_from_definition(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从 ``{nodes, edges}`` 定义还原出按拓扑序位次排列的步骤列表。"""

    nodes = list((definition or {}).get("nodes") or [])
    nodes.sort(key=lambda node: int(node.get("seq") or 0))
    steps: list[dict[str, Any]] = []
    for node in nodes:
        step = {
            "step_id": node.get("step_id"),
            "name": node.get("name"),
            "kind": node.get("kind"),
            "depends_on": node.get("depends_on"),
            "position": node.get("position"),
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
        # 与 compile_definition 对称：没有 branches 键的 node 还原出没有该键的
        # step，往返因此逐字一致（存量定义的快照不因改造而失真）。
        if "branches" in node:
            step["branches"] = node.get("branches")
        steps.append(step)
    return steps


def execution_layers(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按依赖把步骤分成**可并发的层**，供运行期调度。

    同一层内的步骤互不依赖，可以同时执行；层与层之间必须串行。分层口径是
    「尽早开始」：一个步骤出现在它的所有依赖都已完成的**第一**层。因此层的
    宽度直接等于该轮的最大并发度（``MAX_PARALLEL_BRANCHES`` 校验的就是它）。

    调用方必须先用 ``validate_steps`` 校验过；这里只做防御性检查。
    """

    by_id = {step["step_id"]: step for step in steps}
    return [
        [by_id[step_id] for step_id in layer]
        for layer in _dependency_layers(steps, resolve_depends_on(steps))
    ]


def validate_steps(steps: list[dict[str, Any]], *, max_steps: int) -> None:
    """校验步骤列表；不合法时抛 ``BadRequestException``。

    与改造前的差别：``steps`` 的数组顺序不再等于执行顺序，执行顺序由
    ``depends_on`` 决定。因此「引用只能指向前面的步骤」升级为
    「引用只能是上游（直接或间接依赖）的步骤」，需要先建图再判定。
    """

    if not steps:
        raise BadRequestException("workflow requires at least one step")
    if len(steps) > max_steps:
        raise BadRequestException(
            f"workflow step count {len(steps)} exceeds max_steps {max_steps}"
        )

    seen: set[str] = set()
    for index, step in enumerate(steps):
        _validate_step_shape(step, index=index, seen=seen)
        seen.add(step["step_id"])

    dependencies = resolve_depends_on(steps)
    _validate_depends_on(steps, dependencies)

    # 先分层：环检测与「单层宽度」都在这条路径上，且下游的祖先判定依赖它是 DAG。
    layers = _dependency_layers(steps, dependencies)
    widest = max(len(layer) for layer in layers)
    if widest > MAX_PARALLEL_BRANCHES:
        raise BadRequestException(
            f"workflow has {widest} steps that can run in parallel, "
            f"which exceeds MAX_PARALLEL_BRANCHES {MAX_PARALLEL_BRANCHES}"
        )

    ancestors = _ancestor_map(steps, dependencies)
    for step in steps:
        step_id = step["step_id"]
        label = f"step '{step_id}'"
        _validate_input_bindings(step, upstream=ancestors[step_id], label=label)
        _validate_template_references(step, upstream=ancestors[step_id], label=label)
        if step["kind"] == "condition":
            # 分支谓词只能读上游输出，因此引用校验和输入绑定走同一条路：
            # 先把图建出来（分层已顺带判环），再逐个比对祖先集合。
            _validate_condition_branches(step, upstream=ancestors[step_id], label=label)


def validate_definition(
    definition: dict[str, Any] | None, *, max_steps: int
) -> list[dict[str, Any]]:
    """校验一份 ``{nodes, edges}`` 定义，返回还原后的步骤列表。

    运行前的边界检查走这里：定义在数据库里可能已被更早的 bug 写坏，
    不能假设它一定通过过保存时校验。
    """

    steps = steps_from_definition(definition)
    validate_steps(steps, max_steps=max_steps)
    _validate_edges(steps, definition=definition)
    _validate_edge_consistency(steps, definition=definition)
    return steps


def _validate_step_shape(step: dict[str, Any], *, index: int, seen: set[str]) -> None:
    """校验单个步骤自身的字段（与依赖、引用无关的那部分）。"""

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
    if kind != "condition" and step.get("branches"):
        # 只有条件步骤有分支出口。普通步骤自产多个出口会让「下游该等谁」
        # 无从判断，因此这里直接拒绝，而不是静默忽略。
        raise BadRequestException(
            f"{label} is not a condition step and cannot declare branches"
        )
    if kind == "agent":
        prompt = step.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise BadRequestException(f"{label} is an agent step and requires a prompt")
        if step.get("tool_name"):
            raise BadRequestException(
                f"{label} is an agent step and cannot declare a tool"
            )
        if step.get("input_bindings"):
            # Agent 步骤从提示词里取数（``{{step.output}}``），工具步骤才用
            # input_bindings 拼参数。两种传值方式各自对应一种步骤，混用会被
            # 运行时静默忽略——那比直接拒绝更难查，所以在这里拦住。
            raise BadRequestException(
                f"{label} is an agent step and cannot declare input_bindings; "
                "reference previous steps in the prompt instead"
            )
    elif kind == "tool":
        tool_name = step.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise BadRequestException(
                f"{label} is a tool step and requires a tool_name"
            )
        if step.get("prompt"):
            raise BadRequestException(
                f"{label} is a tool step and cannot declare a prompt"
            )
    else:
        _validate_condition_step_shape(step, label=label)

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
    if (
        on_error == "continue_with_default"
        and not (step.get("default_output") or "").strip()
    ):
        # 没有兜底值却声明「失败也继续」，运行时只会有两条出路：
        # 拿空字符串污染后续步骤，或者偷偷改成中止。两者都是隐性行为。
        raise BadRequestException(
            f"{label} uses on_error=continue_with_default and requires default_output"
        )

    position = step.get("position")
    if position is not None and not _is_position(position):
        raise BadRequestException(
            f"{label} position must be an object with numeric x and y"
        )


def _validate_condition_step_shape(step: dict[str, Any], *, label: str) -> None:
    """校验条件步骤自身的形状（分支结构与「不带执行体」的约束）。

    条件步骤不调模型、不调工具、不连会话，因此任何执行体字段都是误配；
    本函数只管**与上游无关**的那部分，谓词里的引用在
    ``_validate_condition_branches`` 里连同祖先集合一起校验。
    """

    for field, description in (
        ("prompt", "prompt"),
        ("tool_name", "tool_name"),
        ("agent_id", "agent_id"),
    ):
        if step.get(field):
            raise BadRequestException(
                f"{label} is a condition step and cannot declare {description}"
            )
    if step.get("input_bindings"):
        raise BadRequestException(
            f"{label} is a condition step and cannot declare input_bindings; "
            "read upstream steps in the branch predicates instead"
        )
    if step.get("tool_arguments"):
        raise BadRequestException(
            f"{label} is a condition step and cannot declare tool_arguments"
        )
    on_error = step.get("on_error") or "abort"
    if on_error != "abort":
        # 条件步骤没有执行体，也就没有可兜底的失败面；声明别的策略只会让读者
        # 以为「这一步可能失败」。
        raise BadRequestException(
            f"{label} is a condition step and can only use on_error=abort"
        )
    if step.get("default_output"):
        raise BadRequestException(
            f"{label} is a condition step and cannot declare default_output"
        )
    if step.get("max_retries"):
        # 没有执行体就没有可重试的失败面，声明重试次数只会误导读者。
        raise BadRequestException(
            f"{label} is a condition step and cannot declare max_retries"
        )
    if step.get("timeout_seconds"):
        raise BadRequestException(
            f"{label} is a condition step and cannot declare timeout_seconds"
        )

    branches = step.get("branches")
    if not isinstance(branches, list) or not branches:
        raise BadRequestException(
            f"{label} is a condition step and requires at least one branch"
        )
    if len(branches) > MAX_CONDITION_BRANCHES:
        raise BadRequestException(
            f"{label} has {len(branches)} branches, "
            f"which exceeds MAX_CONDITION_BRANCHES {MAX_CONDITION_BRANCHES}"
        )

    names: list[str] = []
    fallback_index: int | None = None
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            raise BadRequestException(f"{label} branch #{index + 1} must be an object")
        name = branch.get("name")
        if not isinstance(name, str) or not STEP_ID_PATTERN.match(name):
            raise BadRequestException(
                f"{label} branch #{index + 1} has an invalid name: "
                "must match [A-Za-z0-9_-]{1,64}"
            )
        if name in RESERVED_HANDLES:
            raise BadRequestException(
                f"{label} branch name '{name}' is reserved for the implicit outlet"
            )
        if name in names:
            raise BadRequestException(f"{label} has a duplicated branch name: {name}")
        names.append(name)
        if branch.get("when") is None:
            if fallback_index is not None:
                raise BadRequestException(
                    f"{label} has more than one unconditional branch; "
                    "exactly one fallback is required"
                )
            fallback_index = index

    if fallback_index is None:
        # 没有兜底出口意味着「所有条件都不成立」时这一步无路可走，下游会被
        # 静默跳过——那是最难排查的一类工作流 bug，因此在保存期就要求写全。
        raise BadRequestException(
            f"{label} requires exactly one unconditional fallback branch"
        )
    if fallback_index != len(branches) - 1:
        raise BadRequestException(
            f"{label} fallback branch must be the last one; "
            f"'{names[fallback_index]}' is at #{fallback_index + 1}"
        )


def _validate_condition_branches(
    step: dict[str, Any], *, upstream: set[str], label: str
) -> None:
    """逐个校验条件步骤的分支谓词；祖先集合一起传入用于引用范围判定。"""

    for branch in step.get("branches") or []:
        when = branch.get("when")
        if when is None:
            # 无条件兜底分支没有谓词可校验。
            continue
        _validate_predicate(
            when,
            upstream=upstream,
            label=f"{label} branch '{branch.get('name')}'",
            depth=1,
        )


def _validate_predicate(
    predicate: Any, *, upstream: set[str], label: str, depth: int
) -> None:
    """校验一份结构化谓词：算子在白名单内、形状对、引用只指向上游。

    谓词是**纯数据**，保存期就把形状和正则验掉，运行期求值才不会遇到
    「读到一半才发现算子不存在」这种只能算运行失败的情况。
    """

    if not isinstance(predicate, dict):
        raise BadRequestException(f"{label} predicate must be an object")

    # 「没写 children」与「children 是 null」必须落成同一种形状：请求体里省略这个键时
    # pydantic 的 model_dump 会补出一个 None，若原样落库，读侧就会看到「有这个键、
    # 值是 null」，把 null 当子条件列表用会直接崩。保存期归一化掉，
    # 编译出的快照里比较算子永远不带 children 键。
    if predicate.get("children") is None:
        predicate.pop("children", None)

    op = predicate.get("op")
    if op in PREDICATE_LOGICAL_OPS:
        if predicate.get("left") is not None or predicate.get("right") is not None:
            raise BadRequestException(
                f"{label} predicate '{op}' is a combinator and cannot declare left/right"
            )
        children = predicate.get("children")
        if not isinstance(children, list) or not children:
            raise BadRequestException(
                f"{label} predicate '{op}' requires a non-empty children list"
            )
        if len(children) > MAX_PREDICATE_CHILDREN:
            raise BadRequestException(
                f"{label} predicate '{op}' has {len(children)} children, "
                f"which exceeds MAX_PREDICATE_CHILDREN {MAX_PREDICATE_CHILDREN}"
            )
        if op == "not" and len(children) != 1:
            # 多子节点的 ``not`` 会变成「一个都不成立」这种读不懂的语义，只收一个。
            raise BadRequestException(
                f"{label} predicate 'not' takes exactly one child, got {len(children)}"
            )
        if depth >= MAX_PREDICATE_DEPTH:
            raise BadRequestException(
                f"{label} predicate nesting exceeds MAX_PREDICATE_DEPTH "
                f"{MAX_PREDICATE_DEPTH}"
            )
        for child in children:
            _validate_predicate(child, upstream=upstream, label=label, depth=depth + 1)
        return

    if op not in PREDICATE_OPS:
        raise BadRequestException(f"{label} has an unknown predicate op: {op}")
    if predicate.get("children") is not None:
        # 比较算子不是组合算子：混用会让「到底以哪个为准」没有唯一答案。
        raise BadRequestException(
            f"{label} predicate '{op}' is a comparison and cannot declare children"
        )

    left = predicate.get("left")
    if not isinstance(left, str) or not left.strip():
        raise BadRequestException(
            f"{label} predicate '{op}' requires a left operand like "
            f"'{REFERENCE_EXAMPLE}'"
        )
    match = TEMPLATE_REFERENCE_PATTERN.fullmatch(left.strip())
    if match is None:
        raise BadRequestException(
            f"{label} predicate '{op}' left must be exactly one reference like "
            f"'{REFERENCE_EXAMPLE}', got '{left}'"
        )
    source_id, path = match.groups()
    if source_id not in upstream:
        # 与模板引用校验同一措辞：两处说的是同一件事，文案统一才好排查。
        raise BadRequestException(
            f"{label} predicate references '{source_id}', "
            "which is not an upstream step"
        )
    if path != OUTPUT_PATH:
        raise BadRequestException(
            f"{label} predicate path must be '{OUTPUT_PATH}', got '{path}'"
        )

    right = predicate.get("right")
    if op == "not_empty":
        if right is not None:
            raise BadRequestException(
                f"{label} predicate 'not_empty' does not take a right operand"
            )
        return
    if not isinstance(right, str) or not right:
        raise BadRequestException(
            f"{label} predicate '{op}' requires a non-empty right operand"
        )
    if op == "matches":
        if len(right) > MAX_REGEX_LENGTH:
            raise BadRequestException(
                f"{label} predicate 'matches' pattern exceeds "
                f"MAX_REGEX_LENGTH {MAX_REGEX_LENGTH}"
            )
        try:
            re.compile(right)
        except re.error as exc:
            raise BadRequestException(
                f"{label} predicate 'matches' has an invalid regular expression: {exc}"
            ) from exc


def _is_position(value: Any) -> bool:
    """画布坐标：``{"x": number, "y": number}``，只影响前端布局。"""

    if not isinstance(value, dict):
        return False
    for key in ("x", "y"):
        item = value.get(key)
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            return False
    return True


def _validate_depends_on(
    steps: list[dict[str, Any]], dependencies: list[list[Any]]
) -> None:
    """校验依赖结构：存在、不自引用、不重复、出口真实存在。

    环检测不在这里，而在 ``_dependency_layers``（分层与判环是同一件事）。
    """

    by_id = {step["step_id"]: step for step in steps}
    for step, declared in zip(steps, dependencies):
        step_id = step["step_id"]
        label = f"step '{step_id}'"
        seen_dependencies: set[tuple[str, str]] = set()
        for entry in declared:
            if not isinstance(entry, str) or not entry.strip():
                raise BadRequestException(f"{label} has an empty depends_on entry")
            source, handle = split_dependency(entry.strip())
            if not source:
                raise BadRequestException(
                    f"{label} has a depends_on entry without a step_id: {entry}"
                )
            if handle == "":
                raise BadRequestException(
                    f"{label} has an empty handle in depends_on: {entry}"
                )
            if source == step_id:
                raise BadRequestException(f"{label} cannot depend on itself")
            source_step = by_id.get(source)
            if source_step is None:
                raise BadRequestException(
                    f"{label} depends_on references an unknown step: {source}"
                )
            normalized = normalize_handle(handle)
            # 重复按 ``(source, 出口)`` 判定而不是条目原文：``a`` 与 ``a@default``
            # 是同一条边，放过去就会编译出两条 edge_id 相同的边。
            if (source, normalized) in seen_dependencies:
                raise BadRequestException(
                    f"{label} has a duplicated dependency: {entry}"
                )
            seen_dependencies.add((source, normalized))

            available = declared_handles(source_step)
            if normalized not in available:
                raise BadRequestException(
                    f"{label} depends_on '{entry}' uses an outlet that step "
                    f"'{source}' never reaches; available: {sorted(available)}"
                )


def _dependency_layers(
    steps: list[dict[str, Any]], dependencies: list[list[Any]]
) -> list[list[str]]:
    """Kahn 分层：返回每层可并发执行的 step_id，并在有环时抛错。"""

    order = [step["step_id"] for step in steps]
    # 分层只关心「谁等谁」：出口后缀在这里剥掉，否则 ``a@branch`` 会被当成一个
    # 不存在的步骤，让整层永远 ready 不了（表现为假的环）。
    pending: dict[str, set[str]] = {
        step_id: {base_step_id(str(item)) for item in declared}
        for step_id, declared in zip(order, dependencies)
    }
    layers: list[list[str]] = []
    done: set[str] = set()
    while pending:
        ready = [
            step_id
            for step_id in order
            if step_id in pending and pending[step_id] <= done
        ]
        if not ready:
            # 走到这里说明剩下的步骤互相等待：不是环，就是依赖了不存在的
            # step_id（后者已被 _validate_depends_on 拦下，这里只兜底）。
            blocked = "、".join(sorted(pending))
            raise BadRequestException(
                f"workflow definition has a dependency cycle among steps: {blocked}"
            )
        layers.append(ready)
        for step_id in ready:
            pending.pop(step_id)
        done.update(ready)
    return layers


def _ancestor_map(
    steps: list[dict[str, Any]], dependencies: list[list[Any]]
) -> dict[str, set[str]]:
    """算出每个步骤的全部上游（直接 + 间接依赖），用于引用校验。"""

    parents: dict[str, list[str]] = {
        step["step_id"]: [base_step_id(str(item)) for item in declared]
        for step, declared in zip(steps, dependencies)
    }
    cache: dict[str, set[str]] = {}

    def collect(step_id: str, visiting: frozenset[str]) -> set[str]:
        if step_id in cache:
            return cache[step_id]
        result: set[str] = set()
        for parent in parents.get(step_id, []):
            if parent in visiting:
                # 环已被 _dependency_layers 拦下；这里只是防止校验顺序变化后递归爆栈。
                continue
            result.add(parent)
            result |= collect(parent, visiting | {parent})
        cache[step_id] = result
        return result

    return {step_id: collect(step_id, frozenset({step_id})) for step_id in parents}


def _validate_input_bindings(
    step: dict[str, Any], *, upstream: set[str], label: str
) -> None:
    """输入绑定必须是「[上游 step_id, 输出路径]」形式的数组选择器。"""

    bindings = step.get("input_bindings") or {}
    if not isinstance(bindings, dict):
        raise BadRequestException(
            f"{label} has invalid input_bindings: must be an object"
        )
    for name, selector in bindings.items():
        if not isinstance(name, str) or not name.strip():
            raise BadRequestException(f"{label} has an empty input binding name")
        # 数组选择器而不是字符串模板：这里做的是纯数据比对，
        # 校验「只能引用上游步骤」不需要写解析器。
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
        if path.strip() != OUTPUT_PATH:
            raise BadRequestException(
                f"{label} input binding '{name}' path must be '{OUTPUT_PATH}', "
                f"got '{path}'"
            )
        if source_id not in upstream:
            raise BadRequestException(
                f"{label} input binding '{name}' references '{source_id}', "
                "which is not an upstream step"
            )


def _validate_template_references(
    step: dict[str, Any], *, upstream: set[str], label: str
) -> None:
    """提示词/参数模板里的 ``{{step_id.path}}`` 也只能指向上游步骤。

    保存时就拦住，而不是等渲染时把一个未替换的占位符发给模型；
    路径同样只允许 ``output``，否则渲染那一步必然失败。
    """

    for text in _template_texts(step):
        for source_id, path in TEMPLATE_REFERENCE_PATTERN.findall(text):
            if source_id not in upstream:
                raise BadRequestException(
                    f"{label} template references '{source_id}', "
                    "which is not an upstream step"
                )
            if path != OUTPUT_PATH:
                raise BadRequestException(
                    f"{label} template path must be '{OUTPUT_PATH}', got '{path}'"
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


def _validate_edges(
    steps: list[dict[str, Any]], *, definition: dict[str, Any] | None
) -> None:
    """复核边两端都指向存在的步骤，且出口是源步骤真的会到达的出口。"""

    if definition is None:
        return
    by_id = {str(step["step_id"]): step for step in steps}
    for edge in definition.get("edges") or []:
        source = edge.get("source")
        target = edge.get("target")
        if source not in by_id or target not in by_id:
            raise BadRequestException(
                f"edge {edge.get('edge_id')} references an unknown step: {source}->{target}"
            )
        handle = normalize_handle(edge.get("source_handle"))
        available = declared_handles(by_id[str(source)])
        if handle not in available:
            # 指向一个永远不会到达的出口，等于让下游静默变成长眠步骤。
            raise BadRequestException(
                f"edge {edge.get('edge_id')} uses an outlet that step '{source}' "
                f"never reaches: {handle}; available: {sorted(available)}"
            )


def _validate_edge_consistency(
    steps: list[dict[str, Any]], *, definition: dict[str, Any] | None
) -> None:
    """边集必须与 ``depends_on`` 推导出的 ``(source, handle, target)`` 集合一致。

    运行期只读 steps（由 nodes 还原），不读 edges。若不校验一致性，一份
    edges 与 depends_on 互相矛盾的定义会「看起来有图、跑起来按另一个图」，
    这比直接拒绝难查得多。出口必须一起比对：只比 ``(source, target)`` 的话，
    「依赖 a@yes」与「依赖 a@no」在快照里长得一模一样。
    """

    derived: set[tuple[str, str, str]] = set()
    for step, dependencies in zip(steps, resolve_depends_on(steps)):
        for entry in dependencies:
            source, handle = split_dependency(str(entry))
            derived.add((source, normalize_handle(handle), str(step["step_id"])))
    stored = {
        (
            str(edge.get("source")),
            normalize_handle(edge.get("source_handle")),
            str(edge.get("target")),
        )
        for edge in ((definition or {}).get("edges") or [])
    }
    if stored != derived:
        # 成功出口沿用 ``a->b`` 的可读写法，具名出口才带后缀。
        missing = sorted(edge_id_of(*edge) for edge in derived - stored)
        extra = sorted(edge_id_of(*edge) for edge in stored - derived)
        raise BadRequestException(
            "workflow definition edges do not match depends_on: "
            f"missing={missing or '[]'} extra={extra or '[]'}"
        )
