#!/usr/bin/env bash
# 验证脚本：工具按组按需加载（2026-10-27-tool-groups-lazy-load）
#
# 目标：用真实序列化体积 + 真实测试输出，证明
#   1) 每请求绑定的工具 schema 从全量降到「常驻目录 + load_tool_group」；
#   2) 加载某组后只补该组，且重复加载幂等；
#   3) 未加载工具被直接调用时会自动全量加载并给出重试提示；
#   4) 目录文本与加载状态无关（恒定），跨轮重放只改绑定集合、不改提示词；
#   5) 首轮预取命中即加载，未声明分组的宿主工具常驻、声明分组的按组绑定。
#
# 脚本只读运行，不修改任何仓库文件。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$ROOT/apps/backend"
PY="$BACKEND/.venv/bin/python"
FAIL=0

echo "## 已执行的命令与结果"
echo

echo "### 1. 工具 schema 体积实测（$PY 直接序列化 bind_tools 形状）"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import json
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import (
    LOAD_TOOL_GROUP_NAME,
    build_tool_group_state,
)
from app.modules.builtin_tool.registry import list_builtin_tools

# 与 REST 入口一致：REST 排除 ask_user（历史行为），WS 保留。
FULL = [tool for tool in list_builtin_tools()]
REST = [tool for tool in FULL if tool.name != "ask_user"]


def schema_chars(tools):
    """按 langchain_adapter._bind_tools 的载荷形状统计字符数。"""

    payload = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {"type": "object"},
            },
        }
        for tool in tools
    ]
    return len(json.dumps(payload, ensure_ascii=False))


failures = []


def check(label, actual, limit):
    status = "PASS" if actual <= limit else "FAIL"
    if actual > limit:
        failures.append(label)
    print(f"{status}  {label}: {actual} 字符（阈值 ≤{limit}）")


baseline = schema_chars(FULL)
print(f"基线：全量绑定 {len(FULL)} 个工具 = {baseline} 字符")

for label, tools in (("WS 入口", FULL), ("REST 入口", REST)):
    state = build_tool_group_state(tools)
    assert state is not None, f"{label} 未启用分组"
    bound = state.bound_tools()
    bound = [tool for tool in bound if tool.name != LOAD_TOOL_GROUP_NAME]
    initial = schema_chars(bound)
    loader = state.loader_tool()
    total = initial + schema_chars([loader])
    limit = 1700 if label.startswith("WS") else 800
    check(f"{label} 初始绑定（常驻工具 + 目录工具）", total, limit)
    print(f"       常驻工具：{[tool.name for tool in bound] or '（无）'}")
    print(f"       可加载组：{state.pending_groups()}")

# 逐组加载后的体积：最大的一组决定「单组后」的验收线。
for group in build_tool_group_state(REST).pending_groups():
    state = build_tool_group_state(REST)
    state.activate(group)
    bound = state.bound_tools()
    loader = state.loader_tool()
    size = schema_chars(bound if loader is None else [*bound, loader])
    check(f"REST 加载 {group} 组之后", size, 6500)

# 幂等：重复加载同一组不产生新工具、不递增版本。
state = build_tool_group_state(REST)
state.activate("ops")
version = state.version
again = state.activate("ops")
if again or state.version != version:
    failures.append("重复加载不幂等")
    print("FAIL  重复加载 ops：二次返回非空或版本递增")
else:
    print("PASS  重复加载同一组：返回空、版本不变")

# 分组登记完整性：任何一个内置工具漏登记分组都会在启动期被拦下。
untagged = sorted(tool.name for tool in FULL if not tool.group)
if untagged:
    failures.append("存在未登记分组的工具")
    print(f"FAIL  未登记分组的工具：{untagged}")
else:
    print(f"PASS  内置工具全部登记分组（{len(FULL)}/{len(FULL)}）")

print()
print("工具目录（进系统提示词，约 %d 字符）：" % len(build_tool_group_state(FULL).catalog_text()))
print(build_tool_group_state(FULL).catalog_text())

if failures:
    print()
    print("体积/语义断言失败项：" + "、".join(failures))
    sys.exit(1)
PY
echo '```'
echo

echo "### 2. REST 与 WS 对同一批工具产出一致的初始绑定与目录文本"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import build_tool_group_state
from app.modules.builtin_tool.registry import list_builtin_tools

tools = list(list_builtin_tools())

# 两条入口的差异仅在工具来源（REST 内置 / WS 内置+宿主合并），工具集合相同时
# 必须给出逐字相同的目录文本与相同的初始绑定集合，否则提示词缓存与排障都不可控。
first = build_tool_group_state(tools)
second = build_tool_group_state(list(reversed(tools)))

names_of = lambda state: [tool.name for tool in state.bound_tools()]
initial_names = names_of(first)
assert initial_names == names_of(second), "初始绑定集合不一致"
assert first.catalog_text() == second.catalog_text(), "目录文本不一致"
# 目录文本必须只由「组名 + 组内工具名」构成，不能夹带 schema。
assert '"parameters"' not in first.catalog_text()
print("PASS  工具顺序不同时，初始绑定与目录文本完全一致")
print("PASS  目录文本不含 JSON schema（只常驻组名与工具名）")
# 目录必须与加载状态无关：每次加载都改系统提示词 = 每次都多打一次前缀 miss。
before = first.catalog_text()
first.activate("ops")
assert first.catalog_text() == before, "加载后目录文本变了"
print("PASS  加载一组后目录文本逐字不变（系统提示词不失效）")
print("初始绑定：" + "、".join(initial_names))
PY
echo '```'
echo

echo "### 3. 跨轮重放加载态：第二轮开局即绑定上一轮加载过的组"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import (
    LOADED_GROUP_METADATA_KEY,
    build_tool_group_state,
)
from app.modules.builtin_tool.registry import list_builtin_tools

tools = list(list_builtin_tools())


def bound_names(state):
    return {tool.name for tool in state.bound_tools()}


# 第一轮：只绑常驻组，模型显式加载 ops。
first = build_tool_group_state(tools)
result = first.handle_loader_call({"group": "ops"})
loaded = result["metadata"][LOADED_GROUP_METADATA_KEY]
assert "order_query" in bound_names(first), "第一轮加载后应绑定 ops 工具"

# 第二轮：从历史记录重放（真实链路里这份集合由 agent_loop_steps.step_metadata
# 读回），开局就绑定 ops，不需要模型再加载一次，且不递增 version。
second = build_tool_group_state(tools, active_groups={loaded})
assert "order_query" in bound_names(second), "第二轮开局应已绑定 ops"
assert second.version == 0, "重放是起点态，不应触发重绑"
# 目录恒定：重放过的组照旧列出（只有 load_tool_group 的 enum 收窄）。
assert second.catalog_text() == build_tool_group_state(tools).catalog_text(), "目录文本随加载态变化"
assert "ops" in (second.catalog_text() or ""), "目录应恒定列出全部组"
assert "ops" not in [g for g in second.loader_tool().input_schema["properties"]["group"]["enum"]], "已加载组不应再出现在 enum 里"

# 不存在的组被忽略：工具集合变小（续跑/子运行）时不会凭空绑定。
third = build_tool_group_state(tools, active_groups={"ops", "ghost"})
assert bound_names(third) == bound_names(second), "未知组不应改变绑定集合"
print("PASS  加载结果携带 tool_group 元数据：" + str(result["metadata"]))
print("PASS  第二轮开局即绑定 ops，version=0，目录恒定、enum 只列未加载组")
print("PASS  未知组名被忽略")
PY
echo '```'
echo

echo "### 4. 首轮预取与宿主分组声明"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import build_tool_group_state
from app.modules.builtin_tool.registry import list_builtin_tools

tools = list(list_builtin_tools())


def bound_names(state):
    return {tool.name for tool in state.bound_tools()}


# 预取：命中两个以上关键词就把该组并进首轮绑定，不递增 version（起点态）。
state = build_tool_group_state(tools)
loaded = state.prefetch("每天定时把上周的订单和库存下载成图片")
assert loaded == {"ops", "content", "task"}, f"预取结果不符：{loaded}"
assert state.version == 0, "预取是首轮起点，不应触发重绑"
assert {"order_query", "image_read", "create_task"} <= bound_names(state)
assert state.prefetch("订单呢") == set(), "单个关键词不应预取"
print("PASS  预取命中即加载（无组数上限），version=0：" + "、".join(sorted(loaded)))

# 未声明分组的宿主工具：归 host 组、首轮就绑定，并在目录里标「常驻」。
undeclared = SimpleNamespace(
    name="debug_ping", description="调试", input_schema={"type": "object"}, kind="host"
)
declared = SimpleNamespace(
    name="note_create_note", description="记笔记", input_schema={"type": "object"}, kind="host"
)
with_host = build_tool_group_state(
    tools + [undeclared, declared],
    host_groups={"note_create_note": "notes"},
    host_group_meta={"notes": ("笔记", "用户自己的笔记")},
)
names = bound_names(with_host)
assert "debug_ping" in names, "未声明分组的宿主工具必须常驻"
assert "note_create_note" not in names, "声明分组的宿主工具默认按需加载"
catalog = with_host.catalog_text()
assert "host（页面，常驻）" in catalog, "宿主回落组应标常驻"
assert "notes（笔记）：用户自己的笔记" in catalog, "声明组应出现在目录里"
assert "notes" in with_host.loader_tool().input_schema["properties"]["group"]["enum"]
print("PASS  未声明分组的宿主工具常驻，声明分组的按需加载且可用 load_tool_group 加载")

# 声明 eager 的组首轮就绑定，且不进 enum。
eager_state = build_tool_group_state(
    tools + [declared],
    host_groups={"note_create_note": "notes"},
    host_group_meta={"notes": ("笔记", "用户自己的笔记")},
    eager_groups={"notes"},
)
assert "note_create_note" in bound_names(eager_state), "eager 组应首轮绑定"
assert "notes" not in eager_state.pending_groups(), "eager 组不应待加载"
assert "notes（笔记，常驻）" in eager_state.catalog_text()
print("PASS  eager 组首轮绑定、不待加载，目录标常驻")
PY
echo '```'
echo

echo "### 5. 分组/加载/兜底/重绑/预取的单元与链路测试"
echo '```'
cd "$BACKEND" || exit 1
"$PY" -m pytest tests/agent_runtime/test_tool_groups.py tests/agent_runtime/test_tool_prefetch.py -q 2>&1 | tail -5 || FAIL=1
"$PY" -m pytest tests/builtin_tool/test_groups.py tests/host_tool/test_group_declarations.py -q 2>&1 | tail -5 || FAIL=1
"$PY" -m pytest tests/conversation/test_repository_loaded_tool_groups.py -q 2>&1 | tail -5 || FAIL=1
echo
echo "--- 受影响包的回归（分批执行，规避测试模块同名收集冲突）"
for pkg in agent_runtime conversation gateway builtin_tool host_tool skill_runner workflows; do
  echo "\$ pytest tests/$pkg -q"
  "$PY" -m pytest "tests/$pkg" -q 2>&1 | tail -2 || FAIL=1
done
echo '```'
echo

echo "### 6. 静态检查"
echo '```'
cd "$BACKEND" || exit 1
"$PY" -m ruff check \
  app/modules/agent_runtime/tool_groups.py \
  app/modules/agent_runtime/tool_prefetch.py \
  app/modules/agent_runtime/composition.py \
  app/modules/agent_runtime/langchain_adapter.py \
  app/modules/agent_runtime/runtime.py \
  app/modules/builtin_tool/groups.py \
  app/modules/builtin_tool/registry.py \
  app/modules/conversation/runtime.py \
  app/modules/conversation/repositories.py \
  app/modules/conversation/services.py \
  app/modules/gateway/runtime.py \
  app/modules/gateway/router.py \
  app/modules/host_tool/schemas.py \
  app/modules/host_tool/services.py \
  tests/agent_runtime/test_tool_groups.py \
  tests/agent_runtime/test_tool_prefetch.py \
  tests/builtin_tool/test_groups.py \
  tests/host_tool/test_group_declarations.py \
  tests/gateway/test_chat_flow.py \
  tests/conversation/test_repository_loaded_tool_groups.py \
  tests/conversation/test_runtime.py 2>&1 | tail -5 || FAIL=1
echo '```'
echo

echo "## 未执行项与原因"
echo
echo "- 真实供应商调用下的工具选择准确率：需要可用的外部模型密钥与线上流量，本地无法复现。"
echo "- 前缀缓存命中率与首 token 延迟：需要供应商侧计费/缓存指标，仓库内无采集口径（见 ADR 0011）。"
echo "- 桌面宿主（ledger / note）真实页面注册链路：需要在桌面宿主进程内运行，本地只覆盖了同名形状的替身对象。"
echo "- 多轮对话中途加载组后的完整前端事件回放：已有消息落库口径未改，本轮未构造端到端回放用例。"
echo "- 预取命中率与由此省下的首 token 延迟：需要真实用户消息分布与供应商缓存指标，本地只有规则单测。"
echo "- 桌面宿主（ledger / note）真实声明 group / registerToolGroups：ai-sdk 侧只做了类型检查，未在真实页面跑通。"
echo
echo "## 验收结论"
echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "通过：体积断言、目录恒定、跨轮重放语义、幂等/兜底语义、首轮预取与宿主分组声明、受影响包单测与 ruff 全部成功。"
else
  echo "未通过：脚本内有失败项，见上方输出。"
fi
exit "$FAIL"
