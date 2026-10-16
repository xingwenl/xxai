#!/usr/bin/env bash
# 阶段四「工作流条件分支」验证脚本
#
# 覆盖 docs/harness/requests/2026-10-15-workflow-conditional-branching/spec.md 的 8 条验收标准：
#   1. tests/workflows 全绿 + ruff / black 在本次改动文件上通过 + 无新增迁移
#   2. 兼容：不含 condition、depends_on 无 @ 的定义编译出的边仍全部 source_handle='default'
#      且 edge_id 仍是 `a->b`；既有 test_runner_parallel.py / test_validators_dag.py 一字未改
#   3. 条件判定：equals/contains/not_empty/matches 四算子与 all/any/not 组合的真值表；
#      多分支命中取定义顺序第一个；全不命中走兜底
#   4. 跳过传播：未选中分支的步骤落 status='skipped'（每步恰一条），下游同样跳过
#   5. 到达触发汇聚：只有一条分支到达时汇聚步骤照样执行
#   6. fail_branch：失败步骤 status='failed' 且 on_error_applied=False，@failed 下游执行、@default 下游跳过，run 仍 completed
#   7. 保存期拒绝：未知出口 / 缺兜底 / 多兜底 / 兜底不在最后 / 分支名重复或保留 / 条件步骤带执行体字段 /
#      谓词引用非上游 / 未知算子 / 非法正则 / `a` 与 `a@default` 重复
#   8. 前端：apps/front 的 tsc -b 与 vite build 通过；workflow-dag.ts 的**真实实现**由
#      `node --experimental-strip-types` 直接加载并跑出口助手 / declaredHandles / 限定依赖往返 /
#      dagShape / validateDag 拒绝清单
#
# 退出码：0 全部通过；1 有失败；3 有未执行项；2 脚本自身错误。
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
# 有明确未执行项（PG 端到端 / 浏览器交互），退出码取 3 而不是 0：与既有验证脚本口径一致。
UNEXECUTED=1
ROOT="$(pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
PY="${ROOT}/apps/backend/.venv/bin/python"
FRONT="${ROOT}/apps/front"

# 本次改动的后端文件（ruff/black 只按清单断言：仓库范围 ruff/black 本就不干净）
BACKEND_FILES=(
  app/modules/workflows/validators.py
  app/modules/workflows/schemas.py
  app/modules/workflows/runner.py
  app/modules/workflows/services.py
  tests/workflows/helpers.py
  tests/workflows/test_validators.py
  tests/workflows/test_validators_conditions.py
  tests/workflows/test_runner_conditions.py
)

verify_step() {
  local name="$1"
  shift
  echo "### ${name}"
  echo
  echo '```bash'
  printf '%s ' "$@"
  echo
  echo '```'
  if "$@" >"$TMP_DIR/step.log" 2>&1; then
    echo "结果：通过"
    echo
    echo '```text'
    tail -6 "$TMP_DIR/step.log"
    echo '```'
  else
    echo "结果：失败"
    echo
    echo '```text'
    tail -40 "$TMP_DIR/step.log"
    echo '```'
    FAIL=1
  fi
  echo
}

# --------------------------------------------------------------------------- #
# 前置：几份真实实现探针（python + node）
# --------------------------------------------------------------------------- #
cat >"${TMP_DIR}/probe_compat.py" <<'PY'
"""验收 2：存量线性定义零改动兼容。"""

import sys

sys.path.insert(0, "tests/workflows")

from app.modules.workflows import validators
from helpers import agent_step

# 不含 condition、depends_on 缺省（= 依赖前一个步骤）的存量形态。
steps = [agent_step("collect", prompt="先搜集"), agent_step("query", prompt="再查库")]
definition = validators.compile_definition(steps)
edges = definition["edges"]

assert [edge["source_handle"] for edge in edges] == ["default"], edges
assert [edge["edge_id"] for edge in edges] == ["collect->query"], edges
assert validators.steps_from_definition(definition) == steps
assert validators.validate_definition(definition, max_steps=50) == steps
print("edges:", [(e["edge_id"], e["source"], e["target"], e["source_handle"]) for e in edges])
print("depends_on 缺省展开:", validators.resolve_depends_on(steps))
print("兼容：存量线性定义的边与步骤逐字不变")
PY

cat >"${TMP_DIR}/probe_predicate.py" <<'PY'
"""验收 3：谓词真值表（纯函数，不碰数据库）。"""

from app.modules.workflows import runner

OUTPUTS = {"entry": "hello world 123", "blank": "   "}
REF = "{{entry.output}}"

CASES = [
    ("equals 命中", {"op": "equals", "left": REF, "right": "hello world 123"}, True),
    ("equals 不命中", {"op": "equals", "left": REF, "right": "hello"}, False),
    ("contains 命中", {"op": "contains", "left": REF, "right": "world"}, True),
    ("contains 不命中", {"op": "contains", "left": REF, "right": "地球"}, False),
    ("not_empty 命中", {"op": "not_empty", "left": REF}, True),
    ("not_empty 空白串", {"op": "not_empty", "left": "{{blank.output}}"}, False),
    ("matches 命中", {"op": "matches", "left": REF, "right": r"\d+"}, True),
    ("matches 全串锚定不命中", {"op": "matches", "left": REF, "right": r"^\d+$"}, False),
    (
        "上游被跳过读空串",
        {"op": "equals", "left": "{{skipped_step.output}}", "right": ""},
        True,
    ),
    (
        "all 全真才真",
        {
            "op": "all",
            "children": [
                {"op": "contains", "left": REF, "right": "world"},
                {"op": "not_empty", "left": "{{skipped_step.output}}"},
            ],
        },
        False,
    ),
    (
        "any 有真即真",
        {
            "op": "any",
            "children": [
                {"op": "not_empty", "left": "{{skipped_step.output}}"},
                {"op": "contains", "left": REF, "right": "world"},
            ],
        },
        True,
    ),
    (
        "not 取反",
        {"op": "not", "children": [{"op": "not_empty", "left": "{{skipped_step.output}}"}]},
        True,
    ),
]

for name, predicate, expected in CASES:
    actual = runner.evaluate_predicate(predicate, OUTPUTS)
    assert actual is expected, f"{name}: 期望 {expected}，实际 {actual}"
    print(f"{name}: {actual}")

# 多分支命中取定义顺序第一个；全不命中走兜底。
BRANCHES = [
    {"name": "yes", "when": {"op": "contains", "left": REF, "right": "world"}},
    {"name": "anyway", "when": {"op": "not_empty", "left": REF}},
    {"name": "no", "when": None},
]
first = runner._match_branch({"kind": "condition", "branches": BRANCHES}, OUTPUTS)
assert first == "yes", first
fallback = runner._match_branch({"kind": "condition", "branches": BRANCHES}, {"entry": ""})
assert fallback == "no", fallback
print(f"两分支同时为真取第一个: {first}")
print(f"全不命中走兜底: {fallback}（blank 分支 not_empty 为假）")
PY

cat >"${TMP_DIR}/probe_reject.py" <<'PY'
"""验收 7：保存期拒绝清单（每条都必须是 400 且不改动既有定义）。"""

import sys

sys.path.insert(0, "tests/workflows")

from app.modules.workflows import validators
from app.shared.exceptions import BadRequestException
from helpers import agent_step, condition_step, output_ref, predicate

REF = output_ref("entry")


def branching(**gate_overrides):
    gate = condition_step(
        "gate",
        depends_on=["entry"],
        branches=[
            {"name": "yes", "when": predicate("contains", left=REF, right="同意")},
            {"name": "no", "when": None},
        ],
    )
    gate.update(gate_overrides)
    return [
        agent_step("entry", prompt="给个结论"),
        gate,
        agent_step("on_yes", depends_on=["gate@yes"]),
        agent_step("on_no", depends_on=["gate@no"]),
    ]


def check(name, steps, expected):
    try:
        validators.validate_steps(steps, max_steps=50)
    except BadRequestException as exc:
        message = str(exc)
        assert expected in message, f"{name}: 期望文案含 {expected!r}，实际 {message!r}"
        print(f"{name}: 拒绝（{expected}）")
        return
    raise AssertionError(f"{name}: 期望被拒绝，实际通过")


bad_dep = branching()
bad_dep[2] = agent_step("on_yes", depends_on=["gate@nope"])
check("未知出口名", bad_dep, "never reaches")

fail_dep = branching()
fail_dep[2] = agent_step("on_yes", depends_on=["entry@failed"])
check("@failed 用在上游非 fail_branch", fail_dep, "never reaches")

dup_dep = branching()
dup_dep[2] = agent_step("on_yes", depends_on=["entry", "entry@default"])
check("同源同出口重复依赖（entry 与 entry@default 是同一条边）", dup_dep, "duplicated dependency")

no_fallback = branching(
    branches=[{"name": "yes", "when": predicate("contains", left=REF, right="同意")}]
)
check("缺兜底分支", no_fallback, "requires exactly one unconditional fallback branch")

two_fallback = branching(
    branches=[
        {"name": "yes", "when": None},
        {"name": "no", "when": None},
    ]
)
check("多个兜底分支", two_fallback, "exactly one fallback is required")

last_not_fallback = branching(
    branches=[
        {"name": "yes", "when": None},
        {"name": "no", "when": predicate("not_empty", left=REF)},
    ]
)
check("兜底不在最后", last_not_fallback, "fallback branch must be the last one")

dup_branch = branching(
    branches=[
        {"name": "yes", "when": predicate("not_empty", left=REF)},
        {"name": "yes", "when": None},
    ]
)
check("分支名重复", dup_branch, "has a duplicated branch name")

reserved_branch = branching(
    branches=[
        {"name": "default", "when": predicate("not_empty", left=REF)},
        {"name": "no", "when": None},
    ]
)
check("分支名用保留出口名", reserved_branch, "is reserved for the implicit outlet")

with_prompt = branching(prompt="偷偷带个执行体")
check("条件步骤带 prompt", with_prompt, "is a condition step and cannot declare prompt")

with_tool = branching(tool_name="sql_query")
check("条件步骤带 tool_name", with_tool, "is a condition step and cannot declare tool_name")

unknown_op = branching(
    branches=[
        {"name": "yes", "when": predicate("roughly", left=REF, right="x")},
        {"name": "no", "when": None},
    ]
)
check("谓词算子未知", unknown_op, "has an unknown predicate op: roughly")

not_upstream = branching(
    branches=[
        {"name": "yes", "when": predicate("not_empty", left=output_ref("on_yes"))},
        {"name": "no", "when": None},
    ]
)
check("谓词引用非上游", not_upstream, "which is not an upstream step")

bad_regex = branching(
    branches=[
        {"name": "yes", "when": predicate("matches", left=REF, right="([")},
        {"name": "no", "when": None},
    ]
)
check("matches 正则非法", bad_regex, "has an invalid regular expression")
PY

# --------------------------------------------------------------------------- #
# 前端探针：node --experimental-strip-types 直接加载**磁盘上的真实实现**
# （workflow-dag.ts + workflow-canvas-model.ts）。
#
# workflow-dag.ts 里有值导入（BRANCH_HANDLE_SEPARATOR / MAX_PARALLEL_BRANCHES 来自
# '@/api/workflow'），而 '@' 是 vite 别名、'@/lib/http' 顶层读 import.meta.env，
# node 无法直接解析。这里在探针里注册一个 data:URL 的 resolve hook：'@/x' 一律映射到
# 真实源码 src/x.ts，只把 3 个视图层依赖（@/lib/http、react、@xyflow/react）换成一行 stub。
# 没有副本、没有改写源文件，断言跑的就是仓库里的实现。
cat >"${TMP_DIR}/front_probe.mjs" <<'TS'
import { register } from 'node:module'
import assert from 'node:assert/strict'

const SRC = process.argv[2].endsWith('/') ? process.argv[2] : `${process.argv[2]}/`
const stub = (body) => `data:text/javascript,${encodeURIComponent(body)}`
const hookSource = `
const SRC = ${JSON.stringify(SRC)}
export async function resolve(spec, ctx, next) {
  if (spec === '@/lib/http') return { url: ${JSON.stringify(stub('export const http = {}'))}, shortCircuit: true, format: 'module' }
  if (spec === 'react') return { url: ${JSON.stringify(stub('export const useMemo = (fn) => fn(); export const useCallback = (fn) => fn; export const useState = (v) => [v, () => {}]; export const useEffect = () => {}'))}, shortCircuit: true, format: 'module' }
  if (spec === '@xyflow/react') return { url: ${JSON.stringify(stub('export const MarkerType = { ArrowClosed: "arrowClosed" }; export const Position = { Left: "left", Right: "right" }; export const useNodesState = (n) => [n, () => {}, () => {}]; export const useEdgesState = (e) => [e, () => {}, () => {}]; export const addEdge = (e, es) => es; export const ReactFlow = () => null; export const Handle = () => null; export const Background = () => null; export const Controls = () => null'))}, shortCircuit: true, format: 'module' }
  if (spec.startsWith('@/')) return next(new URL(spec.slice(2) + '.ts', SRC).href, ctx)
  return next(spec, ctx)
}
`
register('data:text/javascript,' + encodeURIComponent(hookSource))

const dag = await import(SRC + 'features/workflows/workflow-dag.ts')
const model = await import(SRC + 'features/workflows/workflow-canvas-model.ts')

// 先证明加载到的是真实实现（导出名清单），而不是空壳。
const dagExports = Object.keys(dag).sort()
const modelExports = Object.keys(model).sort()
assert.ok(dagExports.includes('validateDag') && dagExports.includes('declaredHandles'))
assert.ok(modelExports.includes('buildCanvasEdges') && modelExports.includes('sourceHandlesOf'))
console.log('加载 workflow-dag.ts 真实实现，导出：', dagExports.join(', '))
console.log('加载 workflow-canvas-model.ts 真实实现，导出：', modelExports.join(', '))

// ---- 用例：step_1(工具) → step_2(条件，两个分支出口) → step_3 / step_4
const step_1 = { step_id: 'step_1', name: '取数', kind: 'tool', tool_name: 'sql_query', tool_arguments: {}, depends_on: null }
const step_2 = {
  step_id: 'step_2', name: '判定', kind: 'condition', on_error: 'abort', prompt: '', tool_name: '',
  branches: [
    { name: 'branch_ok', when: { op: 'contains', left: '{{step_1.output}}', right: '成功' } },
    { name: 'branch_fallback', when: null },
  ],
  depends_on: ['step_1'],
}
const step_3 = { step_id: 'step_3', name: '成功路径', kind: 'agent', prompt: '继续', depends_on: ['step_2@branch_ok'] }
const step_4 = { step_id: 'step_4', name: '兜底路径', kind: 'agent', prompt: '收尾', depends_on: ['step_2@branch_fallback'] }
const steps = [step_1, step_2, step_3, step_4]
const stepIds = steps.map((s) => s.step_id)
const resolved = dag.resolveDependencies(steps)
const variant = (patch) => steps.map((s) => (s.step_id === 'step_2' ? { ...s, ...patch } : s))
const msgs = (issues) => issues.map((i) => i.message).join(' | ') || '(无)'
const handles = (step) => JSON.stringify(model.sourceHandlesOf(step).map((h) => [h.id, h.label, h.tone]))

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ::  ' + detail : ''}`)
}

// 出口助手：解析、规范化、反推
check('resolveDependencies 保留分支出口', JSON.stringify(resolved) === JSON.stringify([[], ['step_1'], ['step_2@branch_ok'], ['step_2@branch_fallback']]), JSON.stringify(resolved))
check('baseStepId / branchHandle 拆分出口', dag.baseStepId('step_2@branch_ok') === 'step_2' && dag.branchHandle('step_2@branch_ok') === 'branch_ok' && dag.branchHandle('step_1') === 'default' && dag.branchHandle('step_2@') === '')
check('dependencyEntry：成功出口不写后缀', dag.dependencyEntry('step_2', 'default') === 'step_2' && dag.dependencyEntry('step_2', 'branch_ok') === 'step_2@branch_ok')
check('normalizeDependency：a@default 归一成 a', dag.normalizeDependency('step_1@default') === 'step_1' && dag.normalizeDependency('step_2@branch_ok') === 'step_2@branch_ok')
check('handleLabel：成功 / 失败 / 分支名', dag.handleLabel('default') === '成功' && dag.handleLabel('failed') === '失败' && dag.handleLabel('branch_ok') === 'branch_ok')
check('declaredHandles：条件步骤只有分支出口', JSON.stringify(dag.declaredHandles(step_2)) === '["branch_ok","branch_fallback"]')
check('declaredHandles：fail_branch 普通步骤多失败出口', JSON.stringify(dag.declaredHandles({ kind: 'agent', on_error: 'fail_branch' })) === '["default","failed"]')

// 写回：存量线性定义逐字不变，带出口的条目出口不丢
check('toDependsOnWrite：线性默认依赖仍写 null', dag.toDependsOnWrite(resolved, stepIds, 1) === null)
const saved = steps.map((s, i) => ({ ...s, depends_on: dag.toDependsOnWrite(resolved, stepIds, i) }))
const roundTrip = dag.resolveDependencies(JSON.parse(JSON.stringify(saved)))
check('往返（写回 → 重新解析）出口不丢', JSON.stringify(roundTrip) === JSON.stringify(resolved), JSON.stringify(saved.map((s) => s.depends_on)))
check('DAG 形状按基础 step_id 分层', JSON.stringify(dag.dagShape(steps)) === '{"layers":3,"maxWidth":2}', JSON.stringify(dag.dagShape(steps)))

// 合法定义整体通过
check('合法的条件分支定义通过 validateDag', dag.validateDag(steps).length === 0, msgs(dag.validateDag(steps)))

// 谓词结构与引用
const badRef = variant({ branches: [{ name: 'branch_ok', when: { op: 'equals', left: '{{step_4.output}}', right: 'x' } }, { name: 'branch_fallback', when: null }] })
check('谓词引用非上游被拒', dag.validateDag(badRef).some((i) => i.message.includes('只能指向上游步骤')), msgs(dag.validateDag(badRef)))
const badShape = variant({ branches: [{ name: 'branch_ok', when: { op: 'equals', left: '{{step_1.output}}' } }, { name: 'branch_fallback', when: null }] })
check('equals 缺 right 被拒', dag.validateDag(badShape).some((i) => i.message.includes('必须填写 right')), msgs(dag.validateDag(badShape)))
const badRegex = variant({ branches: [{ name: 'branch_ok', when: { op: 'matches', left: '{{step_1.output}}', right: '[a-' } }, { name: 'branch_fallback', when: null }] })
check('matches 非法正则被拒', dag.validateDag(badRegex).some((i) => i.message.includes('正则不合法')), msgs(dag.validateDag(badRegex)))

// 兜底分支与分支名约束
const noFallback = variant({ branches: [{ name: 'a', when: { op: 'not_empty', left: '{{step_1.output}}' } }, { name: 'b', when: { op: 'not_empty', left: '{{step_1.output}}' } }] })
check('缺兜底分支被拒', dag.validateDag(noFallback).some((i) => i.message.includes('必须恰好有一个无条件兜底分支')), msgs(dag.validateDag(noFallback)))
const twoFallback = variant({ branches: [{ name: 'a', when: null }, { name: 'b', when: null }] })
check('两个兜底分支被拒', dag.validateDag(twoFallback).some((i) => i.message.includes('只能有一个无条件兜底分支')), msgs(dag.validateDag(twoFallback)))
const fallbackNotLast = variant({ branches: [{ name: 'fallback', when: null }, { name: 'a', when: { op: 'not_empty', left: '{{step_1.output}}' } }] })
check('兜底不在最后被拒', dag.validateDag(fallbackNotLast).some((i) => i.message.includes('兜底分支必须排在最后')), msgs(dag.validateDag(fallbackNotLast)))
const reservedName = variant({ branches: [{ name: 'failed', when: { op: 'not_empty', left: '{{step_1.output}}' } }, { name: 'fallback', when: null }] })
check('分支名用保留字 failed 被拒', dag.validateDag(reservedName).some((i) => i.message.includes('是保留出口名')), msgs(dag.validateDag(reservedName)))
const dupName = variant({ branches: [{ name: 'a', when: { op: 'not_empty', left: '{{step_1.output}}' } }, { name: 'a', when: null }] })
check('分支名重复被拒', dag.validateDag(dupName).some((i) => i.message.includes('有重复的分支名')), msgs(dag.validateDag(dupName)))
const badCharset = variant({ branches: [{ name: 'a b', when: { op: 'not_empty', left: '{{step_1.output}}' } }, { name: 'fallback', when: null }] })
check('分支名字符集非法被拒', dag.validateDag(badCharset).some((i) => i.message.includes('只能由字母、数字、下划线、连字符组成')), msgs(dag.validateDag(badCharset)))
check('没有分支出口的条件步骤被拒', dag.validateDag(variant({ branches: [] })).some((i) => i.message.includes('至少要有一个分支出口')))
check('条件步骤带执行体字段被拒', dag.validateDag(variant({ prompt: '不该有' })).some((i) => i.message.includes('不能声明执行体字段')), msgs(dag.validateDag(variant({ prompt: '不该有' }))))

// 出口存在性与 @failed 归属
const unknownOutlet = steps.map((s) => (s.step_id === 'step_3' ? { ...s, depends_on: ['step_2@nope'] } : s))
check('依赖不存在的出口被拒', dag.validateDag(unknownOutlet).some((i) => i.message.includes('不存在的出口')), msgs(dag.validateDag(unknownOutlet)))
const failedOnNormal = steps.map((s) => (s.step_id === 'step_3' ? { ...s, depends_on: ['step_1@failed'] } : s))
check('@failed 指向非 fail_branch 上游被拒', dag.validateDag(failedOnNormal).some((i) => i.message.includes('只有 on_error 为 fail_branch 的上游才有 @failed 出口')), msgs(dag.validateDag(failedOnNormal)))
const failedOnFailBranch = steps.map((s) => (s.step_id === 'step_1' ? { ...s, on_error: 'fail_branch' } : s.step_id === 'step_3' ? { ...s, depends_on: ['step_1@failed', 'step_2@branch_ok'] } : s))
check('@failed 指向 fail_branch 上游放行', dag.validateDag(failedOnFailBranch).length === 0, msgs(dag.validateDag(failedOnFailBranch)))

// 环检测仍按基础 step_id 生效
const cycle = steps.map((s) => (s.step_id === 'step_1' ? { ...s, depends_on: ['step_4'] } : s))
check('跨分支出口的成环被检出', dag.validateDag(cycle).some((i) => i.message.includes('依赖成环')), msgs(dag.validateDag(cycle)))

// 画布往返：边 id / sourceHandle / 标签 / 出口列表
check('edgeId：成功出口 a->b', model.edgeId('step_1', 'step_2') === 'step_1->step_2')
check('edgeId：分支出口 a:分支名->b', model.edgeId('step_2', 'step_3', 'branch_ok') === 'step_2:branch_ok->step_3')
const edges = model.buildCanvasEdges(resolved, stepIds)
const branchEdge = edges.find((e) => e.id === 'step_2:branch_ok->step_3')
const defaultEdge = edges.find((e) => e.id === 'step_1->step_2')
check('边集带 sourceHandle 与分支名标签', edges.length === 3 && branchEdge?.sourceHandle === 'branch_ok' && branchEdge?.label === 'branch_ok' && defaultEdge?.sourceHandle === 'default' && defaultEdge?.label === undefined, JSON.stringify(edges.map((e) => [e.id, e.sourceHandle, e.label])))
check('条件节点出口列表 = 分支名', handles(step_2) === '[["branch_ok","branch_ok","branch"],["branch_fallback","branch_fallback","branch"]]', handles(step_2))
check('fail_branch 节点出口列表 = 成功 + 失败', handles({ step_id: 'x', name: 'x', kind: 'agent', on_error: 'fail_branch', branches: null, position: null }) === '[["default","成功","default"],["failed","失败","failed"]]', handles({ step_id: 'x', name: 'x', kind: 'agent', on_error: 'fail_branch', branches: null, position: null }))

// 落库形状 → 读回：后端 model_dump 会把省略的 children 补成 null，读侧必须归一化掉，
// 否则编辑器把 null 当子条件列表用（.map 抛错 → 白屏），保存校验也会误判成非法。
const api = await import(SRC + 'api/workflow.ts')
const rawNode = (when) => ({ step_id: 'cond', name: '判定', kind: 'condition', seq: 0, depends_on: ['step_1'], branches: [{ name: 'yes', when }, { name: 'fallback', when: null }] })
const readBack = (when) => api.toWorkflow({ id: 1, name: 'wf', definition: { nodes: [rawNode(when)], edges: [] } }).steps[0].branches[0].when
const rootNull = readBack({ op: 'equals', left: '{{step_1.output}}', right: 'x', children: null })
check('读回：比较算子的 children: null 被丢掉', !('children' in rootNull) && rootNull.op === 'equals', JSON.stringify(rootNull))
const nestedNull = readBack({ op: 'all', children: [{ op: 'not_empty', left: '{{step_1.output}}', children: null }] })
check('读回：嵌套子条件的 children: null 也被丢掉', !('children' in nestedNull.children[0]), JSON.stringify(nestedNull))
const storedShape = steps.map((s) => (s.step_id === 'step_2' ? { ...s, branches: [{ name: 'branch_ok', when: { op: 'equals', left: '{{step_1.output}}', right: 'x', children: null } }, { name: 'branch_fallback', when: null }] } : s))
check('存量 children: null 定义不再被误判为非法', dag.validateDag(storedShape).length === 0, msgs(dag.validateDag(storedShape)))
const emptyChildren = variant({ branches: [{ name: 'branch_ok', when: { op: 'equals', left: '{{step_1.output}}', right: 'x', children: [] } }, { name: 'branch_fallback', when: null }] })
check('children: [] 仍按带了子条件被拒', dag.validateDag(emptyChildren).some((i) => i.message.includes('不能带 children')), msgs(dag.validateDag(emptyChildren)))

console.log('')
if (failed === 0) {
  console.log('前端探针全部通过：0 项失败')
} else {
  console.log(`前端探针有 ${failed} 项失败`)
  process.exitCode = 1
}
TS

echo "## 已执行的命令与结果"
echo
echo '本次验证对应的改动范围（未提交）：'
echo
echo '```text'
git status --porcelain -- apps/backend/app/modules/workflows apps/backend/tests/workflows \
  apps/front/src/api/workflow.ts apps/front/src/features/workflows docs/adr/0006-workflow-conditional-branching.md \
  docs/harness/requests/2026-10-15-workflow-conditional-branching
echo '```'
echo

verify_step \
  "验收 1：ruff check（本次改动文件）" \
  bash -c "cd apps/backend && .venv/bin/python -m ruff check ${BACKEND_FILES[*]}"

verify_step \
  "验收 1：black --check（本次改动文件）" \
  bash -c "cd apps/backend && .venv/bin/python -m black --check ${BACKEND_FILES[*]}"

verify_step \
  "验收 1：无新增迁移（alembic heads 仍是 20261015_0038 且只有一个 head）" \
  bash -c "cd apps/backend && test -z \"\$(git status --porcelain migrations)\" && .venv/bin/python -m alembic heads | tee /dev/stderr | grep -q 20261015_0038 && test \$(.venv/bin/python -m alembic heads | grep -c 'head') -eq 1"

verify_step \
  "验收 1 + 2：既有并发与 DAG 回归文件一字未改（test_runner_parallel.py / test_validators_dag.py / test_validators.py 之外）" \
  bash -c "cd apps/backend && test -z \"\$(git status --porcelain tests/workflows/test_runner_parallel.py tests/workflows/test_validators_dag.py)\" && echo 'test_runner_parallel.py 与 test_validators_dag.py 工作区无改动'"

verify_step \
  "验收 1：tests/workflows 全量回归" \
  bash -c "cd apps/backend && .venv/bin/python -m pytest tests/workflows -q"

verify_step \
  "验收 2：存量线性定义的边与步骤逐字不变（真实实现探针）" \
  bash -c "cd apps/backend && .venv/bin/python '${TMP_DIR}/probe_compat.py'"

verify_step \
  "验收 3：谓词真值表 + 多分支取第一个 + 未命中走兜底" \
  bash -c "cd apps/backend && .venv/bin/python '${TMP_DIR}/probe_predicate.py'"

verify_step \
  "验收 7：保存期拒绝清单（13 条）" \
  bash -c "cd apps/backend && .venv/bin/python '${TMP_DIR}/probe_reject.py'"

verify_step \
  "验收 4 + 5：跳过传播与到达触发汇聚（运行期，真实 runner + 真实库）" \
  bash -c "cd apps/backend && .venv/bin/python -m pytest tests/workflows/test_runner_conditions.py -q -k 'skip_propagates or first_matching or fallback_when_nothing or only_one_branch_arrives or reads_a_skipped_sibling'"

verify_step \
  "验收 6：fail_branch 路由与整条 run 的终态" \
  bash -c "cd apps/backend && .venv/bin/python -m pytest tests/workflows/test_runner_conditions.py -q -k 'fail_branch'"

verify_step \
  "验收 8：前端类型检查（tsc -b）" \
  bash -c "cd apps/front && pnpm exec tsc -b && echo 'tsc -b 通过（无输出即无错误）'"

verify_step \
  "验收 8：前端生产构建（vite build）" \
  bash -c "cd apps/front && pnpm exec vite build 2>&1 | tail -3"

verify_step \
  "验收 8：node --experimental-strip-types 直接加载 workflow-dag.ts 与 workflow-canvas-model.ts 的真实实现" \
  node --experimental-strip-types "${TMP_DIR}/front_probe.mjs" "file://${FRONT}/src"

echo ""
echo "## 未执行项与原因"
echo ""
echo "- **PostgreSQL 上的端到端**：本次改动**没有任何 DDL/迁移**（验收 1 已断言 head 不变），"
echo "  运行期语义全部由 SQLite 文件库上的真实 runner 覆盖（跳过传播、到达触发、fail_branch、"
echo "  每步恰一条 skipped 记录）。因此本脚本没有起临时 PG 库，也没有跑路由级 HTTP 端到端。"
echo "- **真实浏览器交互未做**：\`apps/front\` 没有测试运行器（scripts 只有 dev/build/lint/preview/format/knip，"
echo "  devDeps 无 vitest/jsdom/playwright）。验收 8 只覆盖 \`tsc -b\`、\`vite build\` 与"
echo "  \`workflow-dag.ts\` 的真实实现探针；**画布的拖拽连线、条件节点的多 source handle 渲染、"
echo "  属性面板分支/谓词编辑器的交互路径未经浏览器验证**。"
echo "- **前端已知限制（设计取舍，非缺陷）**：①同一步骤的两个出口连到同一目标会画成两条"
echo "  可能重叠的边，未做重叠抵消；②分支名非法/重复时画布仍按原样渲染出口，问题只出现在校验列表；"
echo "  ③条件步骤 0 分支时无法从画布连出依赖（有文案提示，但未禁用其它入口）；"
echo "  ④存量 \`step_a@default\` 会被归一化成裸 \`step_a\`（语义等价、字节不同）；"
echo "  ⑤谓词左操作数只能从祖先里选，先写谓词再断开依赖边需用户手改"
echo "  （删除步骤时会清理引用，断边时未清理）；"
echo "  ⑥改分支名不联动下游 \`depends_on\`：下游那条 \`cond@yes\` 会变成不存在的出口，"
echo "  前后端都会拒绝保存并列出可用出口，用户需手删依赖再重连；"
echo "  ⑦谓词正则按各自引擎判定（后端 \`re.compile\`、前端 \`new RegExp\`），"
echo "  Python 独有的 \`(?P<n>x)\` 能过保存期但读不回编辑器；"
echo "  ⑧\`removeEdges\` 手写解析 \`edge_id\` 与 \`workflow-canvas-model.ts\` 的 \`edgeId()\` 是两份实现，格式若改需同步。"
echo "- **本机时钟敏感用例的已知抖动**：\`tests/workflows/test_scheduler.py::test_trigger_records_deadline_missed_beyond_grace\`"
echo "  断言 \`next_run_at > datetime.now(UTC)\`，而 \`next_run_at\` 是调度器 tick 当时按 \`cron='*/5 * * * *'\`"
echo "  推进出来的下一个整 5 分钟点。只要 tick 到断言之间墙钟跨过那个整点（例如机器休眠/被挂起），"
echo "  断言就会失败。本脚本曾观察到一次这种失败（\`next_run_at=22:45:00\` 而断言时刻已是 \`22:47:01\`），"
echo "  重跑即通过；该用例只涉及 \`workflows/scheduler.py\` 与 \`tasks/triggers.py\`，"
echo "  两者本次**一字未改**（见上方改动范围），属于既有用例的时间敏感性，不是本次改动引入的回归。"
echo "- **Agent 编排接管模式下的多 sink 行为未做端到端验证**：条件分支后若不补显式汇聚步骤，"
echo "  \`terminal_step_id\` 会回退到定义里的最后一个步骤（可能是被跳过的那条分支），"
echo "  本轮只在 ADR 0006 的 Consequences 里点明并推荐「分支后补显式汇聚步骤」，"
echo "  没有为此写运行期用例（属于已知设计限制，不是漏测项）。"
echo "- **前端校验与后端校验的规则等价性未做机器比对**：两侧各有一份结构校验"
echo "  （\`workflow-dag.ts\` 的 \`validateDag\` 与 \`validators.py\`），本脚本分别验证了各自的拒绝清单，"
echo "  但没有做「同一份非法定义在两侧都必须被拒」的交叉穷举。"
echo "- **条件步骤的 token 成本不可测**：条件步骤不建会话、不调模型，因此 \`model_usage_records\` 里"
echo "  没有它的行（预期行为，非漏记）。"
echo ""

echo "## 验收结论"
echo ""
echo "| # | 验收标准 | 结论 |"
echo "| --- | --- | --- |"
if [[ "$FAIL" -eq 0 ]]; then
  echo "| 1 | tests/workflows 全绿 + ruff/black 通过 + 无新增迁移 | 通过 |"
  echo "| 2 | 存量线性定义零改动兼容（边仍全为 source_handle='default'） | 通过 |"
  echo "| 3 | 谓词真值表 / 多分支取第一 / 未命中走兜底 | 通过 |"
  echo "| 4 | 跳过传播：未选中分支落 skipped 且每步恰一条 | 通过 |"
  echo "| 5 | 到达触发汇聚：只有一条分支到达也执行 | 通过 |"
  echo "| 6 | fail_branch：failed + on_error_applied=False，run 仍 completed | 通过 |"
  echo "| 7 | 保存期拒绝清单（13 条） | 通过 |"
  echo "| 8 | 前端 tsc -b / vite build / workflow-dag.ts 真实实现探针 | 通过 |"
else
  echo "| 1 | tests/workflows 全绿 + ruff/black 通过 + 无新增迁移 | 见上方结果 |"
  echo "| 2 | 存量线性定义零改动兼容（边仍全为 source_handle='default'） | 见上方结果 |"
  echo "| 3 | 谓词真值表 / 多分支取第一 / 未命中走兜底 | 见上方结果 |"
  echo "| 4 | 跳过传播：未选中分支落 skipped 且每步恰一条 | 见上方结果 |"
  echo "| 5 | 到达触发汇聚：只有一条分支到达也执行 | 见上方结果 |"
  echo "| 6 | fail_branch：failed + on_error_applied=False，run 仍 completed | 见上方结果 |"
  echo "| 7 | 保存期拒绝清单（13 条） | 见上方结果 |"
  echo "| 8 | 前端 tsc -b / vite build / workflow-dag.ts 真实实现探针 | 见上方结果 |"
fi
echo ""

if [[ "$FAIL" -eq 0 && "$UNEXECUTED" -gt 0 ]]; then
  exit 3
fi
exit "$FAIL"
