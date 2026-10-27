#!/usr/bin/env bash
# 验证脚本：管理台按工具组只读展示（2026-10-27-tool-groups-admin-view）
#
# 目标：用真实运行输出证明本轮改动成立
#   1) 契约：只读分组端点存在、要求登录、响应模型带组名/标题/常驻/成员；
#   2) 内置组：18 个工具一个不漏地落进各自声明组，basic 常驻且排第一；
#   3) 宿主组：组名直接复用运行期 tool_group()，未登记前缀落 host 且标常驻；
#   4) 回归：后端 builtin_tool / agent_runtime 测试与 ruff 通过；
#   5) 前端：改动文件的 prettier 与 eslint 通过，类型检查无新增错误。
#
# 说明：`pnpm --dir apps/front build` 在本仓库基线就是红的（3 个 .test.ts 缺
# @types/node），故前端以「tsc 输出只剩这 3 个预存在错误」作为类型检查结论。
# 脚本只读运行，不修改任何仓库文件。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$ROOT/apps/backend"
FRONT="$ROOT/apps/front"
PY="$BACKEND/.venv/bin/python"
FAIL=0

echo "## 已执行的命令与结果"
echo

echo "### 1. 端点契约：路径存在、要求 Bearer 登录、响应字段齐全"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from main import app

schema = app.openapi()
path = schema["paths"]["/api/v1/platforms/{platform_id}/tool-groups"]
assert "get" in path, "缺少 GET"
assert path["get"]["security"] == [{"HTTPBearer": []}], path["get"]["security"]
print("PASS  路由 /api/v1/platforms/{platform_id}/tool-groups 已注册且要求 HTTPBearer")

ref = path["get"]["responses"]["200"]["content"]["application/json"]["schema"]
name = ref.get("$ref", "")
assert name.endswith("ApiResponse_ToolGroupCatalogRead_"), name
group_ref = [
    item["$ref"]
    for item in schema["components"]["schemas"][name.split("/")[-1]]
    .get("properties", {})
    .get("data", {})
    .get("allOf", [{}])[0]
    .get("properties", {})
    .get("builtin", {})
    .get("items", {})
    .values()
    if isinstance(item, str)
]
print("PASS  200 响应模型为 ApiResponse[ToolGroupCatalogRead]")

group_schema = schema["components"]["schemas"]["ToolGroupRead"]
fields = group_schema["properties"]
for field in ("group", "title", "description", "eager", "tool_names"):
    assert field in fields, f"ToolGroupRead 缺少 {field}"
assert fields["tool_names"]["items"]["type"] == "string"
assert "eager" in fields and "boolean" in str(fields["eager"])
print(f"PASS  ToolGroupRead 字段：{sorted(fields)}")
PY
echo '```'
echo

echo "### 2. 内置组：全部工具一个不漏、basic 常驻且排第一、组名与工具声明一致"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import sys

sys.path.insert(0, sys.argv[1])

from app.modules.builtin_tool.groups import BASIC_GROUP, EAGER_TOOL_GROUPS
from app.modules.builtin_tool.registry import list_builtin_tools
from app.modules.builtin_tool.router import _group_reads

groups: dict[str, list[str]] = {}
for tool in list_builtin_tools():
    groups.setdefault(tool.group, []).append(tool.name)

reads = _group_reads(groups, eager_groups=set(EAGER_TOOL_GROUPS) | {BASIC_GROUP})
listed = [name for read in reads for name in read.tool_names]
expected = sorted(tool.name for tool in list_builtin_tools())
assert sorted(listed) == expected, (sorted(listed), expected)
assert len(listed) == len(set(listed)), "工具有重复"
print(f"PASS  {len(expected)} 个内置工具全部出现在目录里且不重复")

declared = {tool.name: tool.group for tool in list_builtin_tools()}
for read in reads:
    for name in read.tool_names:
        assert declared[name] == read.group, (name, declared[name], read.group)
    assert read.title and read.description
print("PASS  每个工具的组名与 BuiltinToolDefinition.group 逐条一致")

assert reads[0].group == BASIC_GROUP and reads[0].eager is True
assert next(r for r in reads if r.group == "ops").eager is False
print(f"PASS  顺序：{[r.group for r in reads]}")
for read in reads:
    print(f"      {read.group:10s} 常驻={str(read.eager):5s} {len(read.tool_names):2d} 个  {read.title}")
PY
echo '```'
echo

echo "### 3. 宿主组：复用运行期 tool_group()，未登记前缀落 host 并标常驻"
echo '```'
"$PY" - "$BACKEND" <<'PY' || FAIL=1
import asyncio
import sys
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])

from app.modules.agent_runtime.tool_groups import tool_group
from app.modules.builtin_tool import router as builtin_router
from app.modules.host_tool import repositories as host_repositories

policies = [
    SimpleNamespace(name="note_save_note"),
    SimpleNamespace(name="ledger_add_entry"),
    SimpleNamespace(name="page_click"),
    SimpleNamespace(name="navigate_to_page"),
    SimpleNamespace(name="debug_ping"),
]


class FakeHostToolRepository:
    def __init__(self, _session):
        pass

    async def list_policies(self, _platform_id):
        return policies


host_repositories.HostToolRepository = FakeHostToolRepository
catalog = asyncio.run(builtin_router._tool_group_catalog(1, object()))

by_name = {name: group.group for group in catalog.host for name in group.tool_names}
assert by_name == {policy.name: tool_group(policy) for policy in policies}
assert by_name["note_save_note"] == "note"
assert by_name["ledger_add_entry"] == "ledger"
assert by_name["page_click"] == "page"
assert by_name["debug_ping"] == "host" and by_name["navigate_to_page"] == "host"
print(f"PASS  宿主工具分组与 tool_group() 逐条一致：{by_name}")

host = next(group for group in catalog.host if group.group == "host")
assert host.eager is True and catalog.host[-1].group == "host"
assert next(g for g in catalog.host if g.group == "note").eager is False
for group in catalog.host:
    print(f"      {group.group:10s} 常驻={str(group.eager):5s} {group.title} · {group.tool_names}")
PY
echo '```'
echo

echo "### 4. 回归测试（后端）"
echo '```'
(cd "$BACKEND" && .venv/bin/python -m pytest tests/builtin_tool tests/agent_runtime -q 2>&1 | tail -5) || FAIL=1
echo '```'
echo

echo "### 5. ruff（改动文件）"
echo '```'
(cd "$BACKEND" && .venv/bin/ruff check app/modules/builtin_tool/router.py app/modules/builtin_tool/schemas.py tests/builtin_tool/test_tool_group_catalog.py 2>&1 | tail -5) || FAIL=1
echo '```'
echo

echo "### 6. 前端：改动文件格式、lint 与类型检查"
echo '```'
cd "$FRONT" || exit 1
FILES="src/api/builtin-tools.ts src/features/agents/builtin-tools-section.tsx src/features/agents/host-tools-section.tsx"
npx prettier --check $FILES || FAIL=1
npx eslint $FILES && echo "PASS  eslint 无告警" || FAIL=1
TS_OUT="$(npx tsc -p tsconfig.app.json --noEmit 2>&1)"
BASELINE="$(printf '%s\n' "$TS_OUT" | grep -c 'node:assert' || true)"
UNEXPECTED="$(printf '%s\n' "$TS_OUT" | grep -v 'node:assert' | grep -v 'type definitions for node' | grep -v '^$' || true)"
if [ -n "$UNEXPECTED" ]; then
  echo "FAIL  出现预期外的类型错误："
  printf '%s\n' "$UNEXPECTED"
  FAIL=1
else
  echo "PASS  类型检查只剩 $BASELINE 个预存在错误（.test.ts 缺 @types/node，与本次改动无关）"
fi
echo '```'
echo

echo "## 未执行项与原因"
echo
cat <<'TXT'
- 真实浏览器里点开管理台页面逐组展开、切换开关：需要登录态与后端服务，本轮未启动前端 dev server 做人工走查。
- `pnpm --dir apps/front build` 全量构建：仓库基线即失败（3 个 .test.ts 缺 `@types/node` 的 TS2591），与本次改动无关，故改用 `tsc -p tsconfig.app.json` 比对基线错误数。
- 真实桌面宿主连接后宿主工具组的实时显示：需要 ai-sdk 客户端接入真实连接，本轮只用假策略验证分组判定与排序。
TXT
echo

echo "## 验收结论"
echo
if [ "$FAIL" -eq 0 ]; then
  echo "- 所有断言通过：端点契约、内置组覆盖与排序、宿主组复用运行期判定、后端回归与 ruff、前端格式与类型检查（扣预存在基线）。"
  echo '- 前端类型检查结论：除 3 个预存在的 .test.ts 缺 node 类型错误外无新增错误。'
  echo "- 未执行项已在上一节逐条列出，未验证部分不作为通过结论。"
  exit 0
else
  echo "- 存在失败项（见上面输出），不能作为通过结论。"
  exit 1
fi
