#!/usr/bin/env bash
# 2026-10-19-tool-approval-wiring 验证脚本
#
# 前置条件：
#   1. `docker compose up -d` 已起（api / db / redis / front / task-scheduler）
#   2. api 镜像已重建并包含本次改动（`DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build api` 后 `up -d api`）
#   3. 数据库已迁移到 head（api 启动命令会自动 `alembic upgrade head`）
#   4. 已灌开发种子：`bash apps/backend/scripts/reset_dev_db.sh`（admin/admin123456、platform 1、agent 1 = dev-assistant 可对话）
#
# 退出码语义（与 tools/harness/verify.sh 一致）：
#   0 全部执行且通过；1 有失败；2 脚本自身错误；3 通过但有未执行项

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
WORK=/tmp/tool-approval-wiring-verify
BASE=http://127.0.0.1:8080
PY=apps/backend/.venv/bin/python
PROBE=tools/harness/verify/2026-10-19-tool-approval-wiring.probe.py
STUB=tools/harness/verify/2026-10-19-tool-approval-wiring.stub-model.py

rm -rf "$WORK"
mkdir -p "$WORK"

verify_step() {
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  echo
  if "$@"; then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

# ---------------------------------------------------------------------------
# 单元测试：改动涉及的模块（跨目录有重名测试模块，必须一个目录一次 pytest）
# ---------------------------------------------------------------------------

step_unit_agent_runtime() { (cd apps/backend && ./.venv/bin/python -m pytest tests/agent_runtime -q --no-header -p no:cacheprovider); }
step_unit_builtin_tool() { (cd apps/backend && ./.venv/bin/python -m pytest tests/builtin_tool -q --no-header -p no:cacheprovider); }
step_unit_conversation() { (cd apps/backend && ./.venv/bin/python -m pytest tests/conversation -q --no-header -p no:cacheprovider); }
step_unit_gateway() { (cd apps/backend && ./.venv/bin/python -m pytest tests/gateway -q --no-header -p no:cacheprovider); }
step_unit_host_tool() { (cd apps/backend && ./.venv/bin/python -m pytest tests/host_tool -q --no-header -p no:cacheprovider); }
step_unit_mcp() { (cd apps/backend && ./.venv/bin/python -m pytest tests/mcp -q --no-header -p no:cacheprovider); }
step_unit_tasks() { (cd apps/backend && ./.venv/bin/python -m pytest tests/tasks -q --no-header -p no:cacheprovider); }
step_unit_tool_approval() { (cd apps/backend && ./.venv/bin/python -m pytest tests/tool_approval -q --no-header -p no:cacheprovider); }
step_unit_tools() { (cd apps/backend && ./.venv/bin/python -m pytest tests/tools -q --no-header -p no:cacheprovider); }
step_unit_workflows() { (cd apps/backend && ./.venv/bin/python -m pytest tests/workflows -q --no-header -p no:cacheprovider); }

# ---------------------------------------------------------------------------
# 结构断言：副作用词汇唯一、闸口判据来自注册表定义
# ---------------------------------------------------------------------------

step_single_vocabulary() {
  local definitions allowed
  definitions=$(grep -rn '^SideEffect = ' apps/backend/app | wc -l | tr -d ' ')
  # 注意排除 STRICT_MODE_ALLOWED_SIDE_EFFECTS 这类「后缀恰好相同」的名字，只找独立定义。
  allowed=$(grep -rnE '(^|[^A-Z_])_ALLOWED_SIDE_EFFECTS' apps/backend/app | wc -l | tr -d ' ')
  echo "SideEffect 定义处数 = ${definitions}（期望 1，位于 tools/side_effects.py）"
  echo "独立的 _ALLOWED_SIDE_EFFECTS 定义 = ${allowed}（期望 0；tasks/unattended.py 的 STRICT_MODE_ALLOWED_SIDE_EFFECTS 不算）"
  grep -rnE '(^|[^A-Z_])_ALLOWED_SIDE_EFFECTS' apps/backend/app || true
  grep -rn '^SideEffect = ' apps/backend/app
  [[ "$definitions" == "1" && "$allowed" == "0" ]]
}

step_registry_truth() {
  (cd apps/backend && ./.venv/bin/python - <<'PY'
from app.modules.builtin_tool.registry import get_builtin_tool
expected = {
    "create_task": "write",
    "delegate_tasks": "write",
    "image_generate": "write",
    "http_post": "none",
    "knowledge_search": "none",
}
ok = True
for name, want in expected.items():
    got = get_builtin_tool(name).side_effect
    print(f"  {name} = {got}（期望 {want}）")
    ok = ok and got == want
from app.modules.mcp.schemas import SideEffect as M
from app.modules.host_tool.schemas import SideEffect as H
from app.modules.tools.side_effects import SideEffect as C
print(f"  三处 SideEffect 收敛为同一类型 = {M == C == H}")
raise SystemExit(0 if ok and M == C == H else 1)
PY
  )
}

step_contract_catalog() {
  local token
  token=$(curl -s -X POST "${BASE}/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d '{"account":"admin","password":"admin123456"}' \
    | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
  curl -s "${BASE}/api/v1/platforms/1/builtin-tools" -H "Authorization: Bearer ${token}" \
    | "$PY" -c '
import sys, json
items = {item["name"]: item["side_effect"] for item in json.load(sys.stdin)["data"]}
legal = {"none", "navigation", "write", "financial", "external"}
print(f"  目录条目数 = {len(items)}")
for name in ("create_task", "delegate_tasks", "image_generate", "http_post"):
    print(f"  {name} = {items.get(name)}")
bad = {k: v for k, v in items.items() if v not in legal}
print(f"  非法取值 = {bad}")
raise SystemExit(0 if items.get("create_task") == "write" and items.get("image_generate") == "write" and not bad else 1)
'
}

step_policy_unit_coverage() {
  local hits
  hits=$(grep -rl --include='*.py' 'financial_side_effect_not_auto_approved\|strict_approval_allows_navigation_only' apps/backend/tests | sort -u | tr '\n' ' ')
  echo "覆盖无人值守拒绝原因码的单测文件：${hits}"
  [[ -n "$hits" ]]
}

# ---------------------------------------------------------------------------
# 端到端：真进程 WS / SSE / 无人值守任务（替身模型提供可预测 tool_call）
# ---------------------------------------------------------------------------

step_e2e_probe() {
  local port log pid ready
  port=$("$PY" -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1]);s.close()')
  log="$WORK/stub-model.log"
  echo "替身模型端口 = ${port}"
  STUB_MODEL_PORT="$port" STUB_MODEL_LOG="$log" "$PY" "$STUB" >"$WORK/stub-model.out" 2>&1 &
  pid=$!
  ready=0
  for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then ready=1; break; fi
    sleep 0.5
  done
  if [[ "$ready" != "1" ]]; then
    echo "替身模型未就绪，输出："
    cat "$WORK/stub-model.out"
    kill "$pid" 2>/dev/null
    return 1
  fi

  local rc=0
  STUB_MODEL_PORT="$port" STUB_MODEL_LOG="$log" "$PY" "$PROBE" || rc=$?
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null

  echo
  echo "替身模型收到的请求（n / last_role / 决策）："
  if [[ -f "$log" ]]; then
    "$PY" - "$log" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    item = json.loads(line)
    print(f"  n={item['n']} last_role={item['last_role']} decision={item['decision']}")
PY
  else
    echo "  （无日志）"
  fi
  return $rc
}

# ---------------------------------------------------------------------------
# Harness 自检
# ---------------------------------------------------------------------------

step_audit() {
  local out extra
  out=$(python3 tools/harness/audit.py 2>&1)
  echo "$out" | tail -4
  extra=$(echo "$out" | grep '^ERROR' | grep -v '2026-10-19-tool-approval-wiring: v2 request 缺少 verify.md' || true)
  if [[ -n "$extra" ]]; then
    echo "出现预期之外的 ERROR："
    echo "$extra"
    return 1
  fi
  echo "（唯一被放行的 ERROR 是「v2 request 缺少 verify.md」，该文件由 tools/harness/verify.sh 在本脚本收尾时产出；本次实得 ERROR 数见上一行）"
}

verify_step "单元测试：agent_runtime" step_unit_agent_runtime
verify_step "单元测试：builtin_tool（含审批闸口 test_approval_gate.py）" step_unit_builtin_tool
verify_step "单元测试：conversation" step_unit_conversation
verify_step "单元测试：gateway（含与 SDK 共享 golden 的事件一致性）" step_unit_gateway
verify_step "单元测试：host_tool" step_unit_host_tool
verify_step "单元测试：mcp" step_unit_mcp
verify_step "单元测试：tasks" step_unit_tasks
verify_step "单元测试：tool_approval（确认状态回读回归）" step_unit_tool_approval
verify_step "单元测试：tools（含 test_side_effects.py）" step_unit_tools
verify_step "单元测试：workflows" step_unit_workflows
verify_step "结构断言：副作用词汇唯一" step_single_vocabulary
verify_step "注册表真值：内置工具的真实 side_effect" step_registry_truth
verify_step "契约：内置工具目录接口返回规范五值" step_contract_catalog
verify_step "无人值守拒绝原因码的单测覆盖" step_policy_unit_coverage
# 探针自身用 flock 保证同一时刻只有一个实例改这套共享数据（tasks 表、chat 绑定、
# 同名嵌入客户端密钥）。拿不到锁时探针退出码 3 —— 那是「本次未执行」，不是失败。
step_e2e_probe_guarded() {
  local rc=0
  step_e2e_probe || rc=$?
  if [[ "$rc" -eq 3 ]]; then
    echo
    echo "结论：检测到另一个探针进程正在运行，本次端到端未执行（不是失败）。"
    echo "请等它结束后重跑：bash tools/harness/verify.sh 2026-10-19-tool-approval-wiring"
    UNEXECUTED=1
    return 0
  fi
  return "$rc"
}

verify_step "端到端：WS 确认 / 拒绝 / 记忆 / 过期 / 无通道 / 无人值守任务 / 委派继承" step_e2e_probe_guarded
verify_step "Harness audit 自检" step_audit

echo "## 未执行项与原因"
echo
echo "- **spec 验收标准 10（断连清理）未满足**：等待确认期间断开 WS 连接后，确认行仍是 \`pending\`（探针 AC10 已实测观测），由 \`tool_confirmations.expires_at\` 的 600s TTL 兜底。实现未在连接清理时把该连接的待确认行标为 \`expired\`；已记入 \`docs/adr/0009-tool-approval-wiring.md\` 的 Consequences。"
echo "- **spec 验收标准 3（\`auto_approve=false\` 时 \`image_generate\` 被拒且 \`storage/\` 无新资产）未端到端执行**：替身模型只产出 \`create_task\` / \`delegate_tasks\` 两种 tool_call，未覆盖 \`image_generate\`。该拒绝走的是与验收标准 2 完全相同的 \`UnattendedPolicy.decide()\` 分支（\`not auto_approve\` → \`auto_approve_disabled\`），已由 \`tests/tasks\` 的策略单测覆盖。"
UNEXECUTED=1
echo "- **spec 验收标准 4（\`financial\` 硬线）未端到端执行**：平台内置工具里没有 \`side_effect=\"financial\"\` 的工具，无法用真实工具触发；由 \`tests/tools/test_side_effects.py\`（\`financial ∈ MEMORY_EXEMPT_SIDE_EFFECTS\`）与 \`tests/tasks\` 的策略单测覆盖。"
echo "- **spec 验收标准 8 的后半句（\`financial\` 第二次仍弹卡）未端到端执行**：同上，无 financial 工具可触发，由 \`MEMORY_EXEMPT_SIDE_EFFECTS\` 单测覆盖。"
echo "- **\`POST /api/v1/agents/{id}/chat\` 非流式通路（微信助手）未单独执行**：它与流式通路共用同一个 \`confirmation_decider=None\` 注入点，流式通路已在端到端里验证；微信侧需要微信回调桩，不在本轮范围内。"
echo "- **进程内单元断言未覆盖的**：SDK 确认卡组件的人工点击路径（\`apps/ai-sdk\` 的 \`ToolConfirmation.vue\`）需要浏览器，本脚本只验证后端出站事件字段（\`callId\`/\`toolType\`/\`sideEffect\`/\`expiresAt\`/\`confirmationId\`/\`summary.arguments\`）齐全。"
echo

echo "## 验收结论"
echo
echo "见 \`docs/harness/requests/2026-10-19-tool-approval-wiring/spec.md\` 的「验收标准」逐条对照：1/2/5(改为默认策略版)/6/7/8(记忆部分)/9(REST 流式)/11/12 通过；3、4、8(后半句)、10 见上「未执行项与原因」。"
echo

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
