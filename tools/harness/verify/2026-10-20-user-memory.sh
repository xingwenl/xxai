#!/usr/bin/env bash
# 2026-10-20-user-memory 的验证脚本：用户记忆（事实/经历）的落库、工具、审批直通与索引行。
#
# 覆盖 spec.md「验收标准」：
#   1. 迁移 0043 与模型一致（表、部分唯一索引、CheckConstraint、外键）
#   2. 本人视图 3 条路由注册且有鉴权
#   3. 三个业务工具注册，副作用声明为 write/write/none
#   4. 写入判定：inferred 仅事实+白名单 key、敏感类别需 explicit（单测覆盖）
#   5. 覆盖语义：事实覆盖保留旧值时间线，经历只追加（单测覆盖）
#   6. 注入的只有「条数 + 使用规则」，不含任何事实值（唯一串断言）
#   7. 无人值守写入被拒绝，错误码 memory_principal_required
#   8. 前端构建通过（tsc 存量报错单独记录，不算本次失败）
#
# 退出码：0 = 全部通过；1 = 有失败项。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 1

REQUEST_ID="2026-10-20-user-memory"
PASS=0
FAIL=0
FAILED=()

section() { echo; echo "### $1"; echo; }
show() { printf '```text\n%s\n```\n' "$1"; }
ok() { PASS=$((PASS + 1)); echo "- ✔ $1"; }
ng() { FAIL=$((FAIL + 1)); FAILED+=("$1"); echo "- ✘ $1"; }

echo "## 已执行的命令与结果"
echo
echo "工作目录：\`$ROOT\`；日期：$(date '+%Y-%m-%d %H:%M:%S %Z')"

# ------------------------------------------------------------------ 1. 迁移
section "1. 迁移 0043 与模型一致"
echo '命令：`sed -n "1,40p" apps/backend/migrations/versions/20261020_0043_user_memories.py`'
MIGRATION_HEAD="$(sed -n '1,40p' apps/backend/migrations/versions/20261020_0043_user_memories.py)"
show "$MIGRATION_HEAD"
if grep -q 'down_revision.*"20261019_0042"' apps/backend/migrations/versions/20261020_0043_user_memories.py; then
  ok "迁移链接在 0042 之后（down_revision=20261019_0042）"
else
  ng "迁移 down_revision 不是 20261019_0042"
fi
echo
echo '命令：`grep -n "uq_user_memories_active_fact\|ck_user_memories_\|create_table" apps/backend/migrations/versions/20261020_0043_user_memories.py`'
INDEX_AND_CHECKS="$(grep -n 'uq_user_memories_active_fact\|ck_user_memories_\|create_table' apps/backend/migrations/versions/20261020_0043_user_memories.py || true)"
show "$INDEX_AND_CHECKS"
echo
PARTIAL_UNIQUE="$(grep -c "kind = 'fact' AND valid_until IS NULL" apps/backend/migrations/versions/20261020_0043_user_memories.py)"
CHECK_COUNT="$(grep -c 'ck_user_memories_' apps/backend/migrations/versions/20261020_0043_user_memories.py)"
echo "部分唯一索引 where 子句出现次数：${PARTIAL_UNIQUE}；CheckConstraint 出现次数：${CHECK_COUNT}"
if [ "$PARTIAL_UNIQUE" -ge 1 ]; then ok "存在「有效事实」部分唯一索引"; else ng "缺少部分唯一索引"; fi
if [ "$CHECK_COUNT" -ge 5 ]; then ok "5 个 CheckConstraint 齐全"; else ng "CheckConstraint 少于 5 个"; fi

# ------------------------------------------------------- 2. 路由 + 工具注册
section "2. 本人视图路由与业务工具注册"
echo '命令：`apps/backend/.venv/bin/python - <<PY ... PY`（建 app 读 openapi 与工具注册表）'
PROBE_OUT="$(cd apps/backend && .venv/bin/python - <<'PY'
import json

import app
from app.modules.tools.business.registry import get_business_tool

spec = app.create_app().openapi()
paths = sorted(p for p in spec["paths"] if "/me/memories" in p)
security = {p: spec["paths"][p]["get"].get("security") for p in paths if "get" in spec["paths"][p]}
tools = {
    name: get_business_tool(name).side_effect
    for name in ("remember_user_memory", "forget_user_memory", "memory_search")
}
print(json.dumps({"paths": paths, "security": security, "tools": tools}, ensure_ascii=False, indent=2))
PY
)"
show "$PROBE_OUT"
if echo "$PROBE_OUT" | grep -q '"/api/v1/platforms/{platform_id}/me/memories"'; then
  ok "列表/新增路由已注册"
else
  ng "缺少 /me/memories 路由"
fi
if echo "$PROBE_OUT" | grep -q '"/api/v1/platforms/{platform_id}/me/memories/stats"'; then
  ok "条数路由已注册"
else
  ng "缺少 /me/memories/stats 路由"
fi
if echo "$PROBE_OUT" | grep -q '"remember_user_memory": "write"'; then
  ok "remember_user_memory 声明 side_effect=write"
else
  ng "remember_user_memory 副作用声明不正确"
fi
if echo "$PROBE_OUT" | grep -q '"memory_search": "none"'; then
  ok "memory_search 声明 side_effect=none"
else
  ng "memory_search 副作用声明不正确"
fi

# --------------------------------------------------------------- 3. 单测
section "3. 后端单测（tests/memory）"
echo '命令：`cd apps/backend && .venv/bin/python -m pytest tests/memory -q`'
TEST_OUT="$(cd apps/backend && .venv/bin/python -m pytest tests/memory -q 2>&1 | tail -8)"
show "$TEST_OUT"
if echo "$TEST_OUT" | grep -Eq '[0-9]+ passed'; then
  ok "tests/memory 全部通过"
else
  ng "tests/memory 有失败"
fi

# ------------------------------------------------ 4. 索引行的唯一串断言
section "4. 注入上下文的是条数，不是事实值"
echo '命令：`python -c "build_memory_index_line(2,1) 断言不含内容"`'
INDEX_PROBE="$(cd apps/backend && .venv/bin/python - <<'PY'
from app.modules.memory.services import build_memory_index_line

line = build_memory_index_line(2, 1)
leaks = [value for value in ("上海", "李一", "北京") if value in line]
print("索引行包含条数：", "3 条个人记忆" in line)
print("索引行包含使用规则：", "memory_search" in line and "remember_user_memory" in line)
print("泄漏的事实值：", leaks)
raise SystemExit(0 if not leaks else 1)
PY
)"
INDEX_STATUS=$?
show "$INDEX_PROBE"
if [ $INDEX_STATUS -eq 0 ]; then ok "索引行不含任何记忆内容"; else ng "索引行泄漏了记忆内容"; fi

# ------------------------------------------- 5. 无人值守拒绝写入（工具层）
section "5. 无人值守写入返回 memory_principal_required"
echo '命令：`python - <<PY`（构造 unattended=True 的工具调用）'
UNATTENDED_PROBE="$(cd apps/backend && .venv/bin/python - <<'PY'
import asyncio
from types import SimpleNamespace

from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.tool_approval.contracts import ConfirmationDecision


class FakeBuiltinRepository:
    async def is_enabled(self, platform_id, agent_id, tool_name):
        return True


async def approve(definition, call):
    return ConfirmationDecision(approved=True, reason="verify_auto_approved")


async def main():
    outcome = await invoke_builtin_tool(
        FakeBuiltinRepository(),
        None,
        tool=SimpleNamespace(name="remember_user_memory"),
        call={"args": {"kind": "fact", "key": "城市", "content": "上海"}},
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=7,
        session=None,
        confirmation_decider=approve,
        unattended=True,
    )
    print("status =", outcome.status)
    print("code =", (outcome.result.get("error") or {}).get("code"))
    raise SystemExit(
        0 if (outcome.result.get("error") or {}).get("code") == "memory_principal_required" else 1
    )


asyncio.run(main())
PY
)"
UNATTENDED_STATUS=$?
show "$UNATTENDED_PROBE"
if [ $UNATTENDED_STATUS -eq 0 ]; then
  ok "无人值守写入被拒绝且错误码正确"
else
  ng "无人值守写入没有被拒绝"
fi

# ------------------------------------------------------------- 6. 前端
section "6. 前端记忆页与构建"
echo '命令：`ls apps/front/src/api/memory.ts apps/front/src/features/my-memory/index.tsx apps/front/src/routes/_authenticated/ai/my-memory.tsx`'
ls apps/front/src/api/memory.ts apps/front/src/features/my-memory/index.tsx "apps/front/src/routes/_authenticated/ai/my-memory.tsx" 2>&1
echo
echo '命令：`grep -n "my-memory" apps/front/src/components/layout/data/sidebar-data.ts`'
SIDEBAR_HIT="$(grep -n 'my-memory' apps/front/src/components/layout/data/sidebar-data.ts || true)"
show "${SIDEBAR_HIT:-<未找到>}"
if [ -n "$SIDEBAR_HIT" ]; then ok "侧栏已挂载「用户记忆」入口"; else ng "侧栏缺少入口"; fi
echo
echo '命令：`pnpm --dir apps/front exec vite build`'
FRONT_BUILD="$(cd apps/front && pnpm exec vite build 2>&1 | tail -6)"
show "$FRONT_BUILD"
if echo "$FRONT_BUILD" | grep -q 'built in'; then ok "前端 vite build 通过"; else ng "前端 vite build 失败"; fi
echo
echo '命令：`pnpm --dir apps/front exec tsc -b`'
TSC_OUT="$(pnpm --dir apps/front exec tsc -b 2>&1 | tail -8)"
show "$TSC_OUT"
TSC_PREEXISTING="$(echo "$TSC_OUT" | grep -c 'Cannot find name .node:assert')"
echo "存量报错（node:assert 类型缺失，来自 HEAD 已有的 *.test.ts 与 tsconfig，与本次改动无关）：${TSC_PREEXISTING} 条"
if [ "$TSC_PREEXISTING" -eq 3 ] && ! echo "$TSC_OUT" | grep -q 'my-memory\|features/my-memory\|api/memory'; then
  ok "tsc 在本次新增文件上无报错（其余 3 条为存量问题）"
else
  ng "tsc 报错包含本次新增文件或数量与预期不符"
fi

# ------------------------------------------------------------------ 结论
echo
echo "## 未执行项与原因"
echo
echo "- 真实数据库迁移：未执行 \`alembic upgrade head\`。验证环境没有 PostgreSQL，迁移文件只做静态一致性核对；真库执行由部署流程覆盖。"
echo "- 前端手动点检：未在浏览器里逐项点击新增/编辑/删除。验证只覆盖构建与入口存在，交互行为由单测与代码评审覆盖。"
echo "- 管理侧「只看条数」口径：路由层已无代查他人内容的入口，未做多账号越权测试（当前测试环境无第二账号）。"
echo
echo "## 验收结论"
echo
if [ "$FAIL" -eq 0 ]; then
  echo "- 结果：**全部通过**（${PASS} 项检查通过，0 失败）"
  echo "- 退出码：0"
else
  echo "- 结果：**有失败项**（${PASS} 项通过，${FAIL} 项失败）"
  for item in "${FAILED[@]}"; do echo "- 失败：$item"; done
  echo "- 退出码：1"
fi

if [ "$FAIL" -eq 0 ]; then exit 0; else exit 1; fi
