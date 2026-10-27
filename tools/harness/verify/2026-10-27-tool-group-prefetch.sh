#!/usr/bin/env bash
# 验证脚本：工具组首轮预取与宿主分组声明（2026-10-27-tool-group-prefetch）
#
# 目标：用真实运行输出证明本轮四项改动成立
#   1) 首轮预取：入口按关键词规则命中工具组，命中即加载、不设组数上限、不递增版本；
#   2) 目录恒定：加载组 / 预取前后目录文本逐字不变，`load_tool_group` 的 enum 只列未加载组；
#   3) 组常驻：`eager` 组与未声明分组的宿主工具首轮就绑定，声明分组的宿主工具按需加载；
#   4) 契约：ai-sdk 的 `ToolDefinition.group` / `registerToolGroups` 通过类型检查。
#
# 体积与跨轮重放的证据在 2026-10-27-tool-groups-lazy-load 的 verify.md 里，本脚本不重复。
# 脚本只读运行，不修改任何仓库文件。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$ROOT/apps/backend"
PY="$BACKEND/.venv/bin/python"
FAIL=0

echo "## 已执行的命令与结果"
echo

echo "### 1. 预取规则：命中即加载、单关键词不预取、不越界"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_prefetch import (
    MIN_PREFETCH_SCORE,
    PREFETCH_RULES,
    prefetch_tool_groups,
)

available = set(PREFETCH_RULES)
cases = [
    ("每天定时把上周的订单和库存下载成图片", available, {"ops", "content", "task"}),
    ("帮我查一下订单和库存", available, {"ops"}),
    ("订单呢", available, set()),
    ("", available, set()),
    ("订单和库存", {"memory"}, set()),
    ("用 PDF 和 http 下载附件", available, {"content"}),
]
for message, groups, expected in cases:
    actual = prefetch_tool_groups(message, groups)
    assert actual == expected, f"{message!r} 期望 {expected}，实际 {actual}"
    print(f"PASS  消息={message!r} → {sorted(actual)}")

# 关键词表自检：每组至少 MIN_PREFETCH_SCORE 个词，且无重复词。
for group, keywords in PREFETCH_RULES.items():
    assert len(keywords) >= MIN_PREFETCH_SCORE, f"{group} 关键词不足"
    assert len(set(keywords)) == len(keywords), f"{group} 关键词重复"
print(f"PASS  {len(PREFETCH_RULES)} 个组的关键词表自检通过（阈值 {MIN_PREFETCH_SCORE}）")
PY
echo '```'
echo

echo "### 2. 目录恒定 + 预取不改目录 + enum 只列未加载组"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import build_tool_group_state
from app.modules.builtin_tool.registry import list_builtin_tools

tools = list(list_builtin_tools())
state = build_tool_group_state(tools)
before = state.catalog_text()
version = state.version

loaded = state.prefetch("每天定时把上周的订单和库存下载成图片")
assert loaded == {"ops", "content", "task"}, loaded
assert state.version == version, "预取是首轮起点，不应触发重绑"
assert state.catalog_text() == before, "预取后目录文本变了"

state.activate("memory")
assert state.catalog_text() == before, "显式加载后目录文本变了"

enum = state.loader_tool().input_schema["properties"]["group"]["enum"]
assert "ops" not in enum and "memory" not in enum, "已加载组不应再出现在 enum 里"
assert "knowledge" in enum, "未加载组应留在 enum 里"
print("PASS  预取与显式加载都不改目录文本（系统提示词不失效）")
print("PASS  load_tool_group 的 enum 只列未加载组：" + "、".join(enum))
PY
echo '```'
echo

echo "### 3. 组常驻语义：eager 组与未声明分组的宿主工具首轮绑定"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import build_tool_group_state
from app.modules.builtin_tool.registry import list_builtin_tools

tools = list(list_builtin_tools())
undeclared = SimpleNamespace(
    name="debug_ping", description="调试", input_schema={"type": "object"}, kind="host"
)
declared = SimpleNamespace(
    name="note_create_note", description="记笔记", input_schema={"type": "object"}, kind="host"
)


def names(state):
    return {tool.name for tool in state.bound_tools()}


# 不带 group 的宿主工具：归 host 组，host 组常驻 → 照旧全部加载。
plain = build_tool_group_state(tools + [undeclared])
assert "debug_ping" in names(plain), "未声明分组的宿主工具必须常驻"
assert "host（页面，常驻）" in plain.catalog_text(), "宿主回落组应标常驻"

# 带 group 的宿主工具：默认异步加载，能被 load_tool_group 加载。
lazy = build_tool_group_state(
    tools + [declared],
    host_groups={"note_create_note": "notes"},
    host_group_meta={"notes": ("笔记", "用户自己的笔记")},
)
assert "note_create_note" not in names(lazy), "声明分组的宿主工具应默认按需加载"
assert "notes" in lazy.loader_tool().input_schema["properties"]["group"]["enum"]
assert "notes（笔记）：用户自己的笔记" in lazy.catalog_text()
lazy.activate("notes")
assert "note_create_note" in names(lazy), "加载后应绑定组内工具"

# 声明 eager 的组：首轮绑定、不待加载、目录标常驻。
eager = build_tool_group_state(
    tools + [declared],
    host_groups={"note_create_note": "notes"},
    host_group_meta={"notes": ("笔记", "用户自己的笔记")},
    eager_groups={"notes"},
)
assert "note_create_note" in names(eager), "eager 组应首轮绑定"
assert "notes" not in eager.pending_groups(), "eager 组不应待加载"
assert "notes（笔记，常驻）" in eager.catalog_text()
print("PASS  不带 group → host 组常驻；带 group → 默认按需；eager=True → 首轮绑定")
PY
echo '```'
echo

echo "### 4. 相关单元测试（分目录执行，规避测试模块同名收集冲突）"
echo '```'
cd "$BACKEND" || exit 1
for target in \
  tests/agent_runtime/test_tool_prefetch.py \
  tests/agent_runtime/test_tool_groups.py \
  tests/builtin_tool/test_groups.py \
  tests/host_tool/test_group_declarations.py \
  tests/conversation/test_repository_loaded_tool_groups.py; do
  echo "\$ pytest $target -q"
  "$PY" -m pytest "$target" -q 2>&1 | tail -2 || FAIL=1
done
echo
echo "--- 受影响包的回归"
for pkg in agent_runtime conversation gateway builtin_tool host_tool; do
  echo "\$ pytest tests/$pkg -q"
  "$PY" -m pytest "tests/$pkg" -q 2>&1 | tail -2 || FAIL=1
done
echo '```'
echo

echo "### 5. 静态检查（Python + ai-sdk 类型）"
echo '```'
cd "$BACKEND" || exit 1
"$PY" -m ruff check \
  app/modules/agent_runtime/tool_groups.py \
  app/modules/agent_runtime/tool_prefetch.py \
  app/modules/builtin_tool/groups.py \
  app/modules/builtin_tool/registry.py \
  app/modules/conversation/services.py \
  app/modules/gateway/runtime.py \
  app/modules/gateway/router.py \
  app/modules/host_tool/schemas.py \
  app/modules/host_tool/services.py \
  tests/agent_runtime/test_tool_prefetch.py \
  tests/agent_runtime/test_tool_groups.py \
  tests/builtin_tool/test_groups.py \
  tests/host_tool/test_group_declarations.py 2>&1 | tail -3 || FAIL=1
cd "$ROOT/apps/ai-sdk" || exit 1
echo "\$ npx tsc --noEmit"
npx tsc --noEmit 2>&1 | tail -3 || FAIL=1
echo "（tsc 无输出即通过）"
echo '```'
echo

echo "## 未执行项与原因"
echo
echo "- 预取命中率与首 token 延迟收益：需要真实用户消息分布与供应商缓存/计费指标，本地只有规则单测（见 ADR 0011）。"
echo "- 真实模型下的「猜错后恢复」体验：需可用外部模型密钥与线上多轮流量，本地用单测覆盖 tool_not_loaded 兜底。"
echo "- 桌面宿主（ledger / note）真实调用 registerToolGroups：ai-sdk 侧只做到类型检查与实际页面链路之外的单元覆盖。"
echo "- 组元数据落库与管理台展示：本轮明确不做（用户 2026-10-27 决策）。"
echo
echo "## 验收结论"
echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "通过：预取规则、目录恒定与 enum 收窄、eager/宿主声明语义、相关单测与静态检查全部成功。"
else
  echo "未通过：脚本内有失败项，见上方输出。"
fi
exit "$FAIL"
