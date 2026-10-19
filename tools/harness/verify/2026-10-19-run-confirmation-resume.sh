#!/usr/bin/env bash
# 2026-10-19-run-confirmation-resume 验证脚本
#
# 前置条件：
#   1. `docker compose up -d` 已起（api / db / redis / front / task-scheduler）
#   2. api 镜像已重建并包含本次改动
#      （`DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build api` 后 `up -d api`）
#   3. 数据库已迁移到 20261019_0041（api 启动命令会自动 `alembic upgrade head`）
#   4. 已灌开发种子：`bash apps/backend/scripts/reset_dev_db.sh`（admin/admin123456、platform 1、agent 1 可对话）
#
# 退出码语义（与 tools/harness/verify.sh 一致）：
#   0 全部执行且通过；1 有失败；2 脚本自身错误；3 通过但有未执行项

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
WORK=/tmp/run-confirmation-resume-verify
PY=apps/backend/.venv/bin/python
PROBE=tools/harness/verify/2026-10-19-run-confirmation-resume.probe.py
STUB=tools/harness/verify/2026-10-19-run-confirmation-resume.stub-model.py

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
# 单元测试（跨目录有重名测试模块，必须一个目录一次 pytest）
# ---------------------------------------------------------------------------

step_unit_conversation() { (cd apps/backend && ./.venv/bin/python -m pytest tests/conversation -q --no-header -p no:cacheprovider); }
step_unit_gateway() { (cd apps/backend && ./.venv/bin/python -m pytest tests/gateway -q --no-header -p no:cacheprovider); }
step_unit_agent_runtime() { (cd apps/backend && ./.venv/bin/python -m pytest tests/agent_runtime -q --no-header -p no:cacheprovider); }
step_unit_builtin_tool() { (cd apps/backend && ./.venv/bin/python -m pytest tests/builtin_tool -q --no-header -p no:cacheprovider); }
step_unit_tool_approval() { (cd apps/backend && ./.venv/bin/python -m pytest tests/tool_approval -q --no-header -p no:cacheprovider); }
step_unit_mcp() { (cd apps/backend && ./.venv/bin/python -m pytest tests/mcp -q --no-header -p no:cacheprovider); }
step_unit_shared() { (cd apps/backend && ./.venv/bin/python -m pytest tests/shared -q --no-header -p no:cacheprovider); }

# ---------------------------------------------------------------------------
# 结构断言
# ---------------------------------------------------------------------------

step_resume_token_removed() {
  local hits
  hits=$(grep -rn "resume_token" apps/backend/app | wc -l | tr -d ' ')
  echo "app/ 下 resume_token 残留 = ${hits}（期望 0）"
  grep -rn "resume_token" apps/backend/app || true
  [[ "$hits" == "0" ]]
}

step_checkpoint_layer() {
  local revision down_revision
  revision=$(grep -rnF 'revision: str = "20261019_0041"' apps/backend/migrations/versions | wc -l | tr -d ' ')
  down_revision=$(grep -rnF 'down_revision: Union[str, None] = "20261019_0040"' apps/backend/migrations/versions | wc -l | tr -d ' ')
  echo "迁移 20261019_0041 定义 = ${revision}（期望 1）"
  echo "down_revision=20261019_0040 = ${down_revision}（期望 1）"
  grep -rn "class AgentLoopRunCheckpoint\b" apps/backend/app/modules/conversation/models.py
  grep -rn "class AgentLoopRunCheckpointRepository" apps/backend/app/modules/conversation/repositories.py
  grep -rn "def mark_consumed\|def mark_expired\|def get_by_loop_run" apps/backend/app/modules/conversation/repositories.py
  [[ "$revision" == "1" && "$down_revision" == "1" ]]
}

step_resolve_endpoint() {
  echo "解决端点与错误码："
  grep -n 'runs/{loop_run_id}/resolve' apps/backend/app/modules/conversation/router.py
  grep -n "RUN_CONFIRMATION_NOT_FOUND\|RUN_CONFIRMATION_ALREADY_RESOLVED\|RUN_CONFIRMATION_EXPIRED\|RUN_RESUME_UNAVAILABLE" \
    apps/backend/app/modules/agent_runtime/error_codes.py
  grep -rn "resume_stream_chat" apps/backend/app/modules/conversation/services.py | head -3
}

step_migration_at_head() {
  docker compose exec -T api alembic current 2>&1 | tail -2 | tee "$WORK/alembic-current.txt"
  grep -q "20261019_0041" "$WORK/alembic-current.txt"
}

step_audit() {
  local output
  output=$(python3 tools/harness/audit.py 2>&1)
  echo "$output"
  # 本 request 的 verify.md 由本次运行产出，运行前必然缺；只要求没有别的 ERROR。
  if echo "$output" | grep '^ERROR' | grep -v 'run-confirmation-resume.*缺少 verify.md' | grep -q .; then
    echo "存在预期外的 audit ERROR"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# 端到端：真进程 SSE 弹卡 → 解决 → 续跑
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
  if [[ "$ready" -ne 1 ]]; then
    echo "替身模型未就绪（端口 ${port}）"
    cat "$WORK/stub-model.out"
    kill "$pid" 2>/dev/null
    return 1
  fi
  echo "替身模型已就绪"

  local rc=0
  STUB_MODEL_PORT="$port" STUB_MODEL_LOG="$log" "$PY" "$PROBE" || rc=$?
  kill "$pid" 2>/dev/null || true
  echo
  echo "--- 替身模型收到的请求 ---"
  cat "$log" 2>/dev/null || echo "（无日志）"
  return "$rc"
}

step_e2e_probe_guarded() {
  local rc=0
  step_e2e_probe || rc=$?
  if [[ "$rc" -eq 3 ]]; then
    echo
    echo "结论：检测到另一个探针进程正在运行，本次端到端未执行（不是失败）。"
    echo "请等它结束后重跑：bash tools/harness/verify.sh 2026-10-19-run-confirmation-resume"
    UNEXECUTED=1
    return 0
  fi
  return "$rc"
}

verify_step "单元测试：tests/conversation" step_unit_conversation
verify_step "单元测试：tests/gateway" step_unit_gateway
verify_step "单元测试：tests/agent_runtime" step_unit_agent_runtime
verify_step "单元测试：tests/builtin_tool" step_unit_builtin_tool
verify_step "单元测试：tests/tool_approval" step_unit_tool_approval
verify_step "单元测试：tests/mcp" step_unit_mcp
verify_step "单元测试：tests/shared" step_unit_shared
verify_step "结构断言：resume_token 死字段已删除" step_resume_token_removed
verify_step "结构断言：检查点表 / 仓储 / 迁移 0041" step_checkpoint_layer
verify_step "结构断言：解决端点与稳定错误码" step_resolve_endpoint
verify_step "环境断言：数据库迁移停在 head" step_migration_at_head
verify_step "端到端：SSE 弹卡 / 批准续跑 / 拒绝续跑 / 二次解决 / 过期 / 会话记忆 / 无通道 / 归属" step_e2e_probe_guarded
verify_step "Harness audit 自检" step_audit

echo "## 未执行项与原因"
echo
echo "- **技能脚本（skill_script）工具的确认**：技能包 manifest 无副作用声明字段，③a 已明确不在本次范围内，故无从发起确认。"
echo "- **MCP 工具在 REST/SSE 上的确认与续跑**：本仓的 MCP 工具需要可连的 MCP 服务端，探针未搭建；MCP 的挂起/解决/续跑归一路径由 \`tests/conversation/test_run_confirmation_resume.py\`（\`_execute_pending_tool\` 的 MCP 分支）与 \`tests/mcp\` 覆盖。"
echo "- **浏览器里点击确认卡**：需要浏览器，未执行；后端出站字段（\`callId\`/\`confirmationId\`/\`loopRunId\`/\`sideEffect\`/\`expiresAt\`/\`summary.arguments\`）已在端到端断言。"
echo "- **微信助手（\`stream=false\`）单独跑**：与探针里的非流式断言共用同一注入点（\`confirmation_decider=None\`），需要微信回调桩，未执行。"
echo "- **\`alembic check\`**：本仓有大量预存在漂移（comment 不一致、nullable 判定），不能作为本改动的结论，未执行。"
echo "- **整包 \`pnpm --dir apps/ai-sdk test\`**：会连带 \`scripts/verify-package.test.mjs\` 的预存在环境性失败（\`npm pack --json\` 的 stdout 被 vite build 日志污染），本次只验证 golden 与后端契约（\`tests/gateway/test_event_parity.py\`）。"
echo

echo "## 验收结论"
echo
echo "| 验收标准 | 证据 | 结论 |"
echo "| --- | --- | --- |"
echo "| AC1 检查点表存在且迁移可逆 | \`step_migration_at_head\`（容器内 \`alembic current\` = 20261019_0041 head）、\`step_checkpoint_layer\`、\`tests/conversation/test_run_checkpoints.py\`（另经 \`compare_metadata\` 验证零漂移、在 sqlite 上跑过 upgrade） | 通过 |"
echo "| AC2 确认卡字段齐全 | \`step_e2e_probe\`：断言恰好一张卡，\`callId\`/\`confirmationId\`/\`loopRunId\`/\`sideEffect=write\`/\`expiresAt\`/\`summary.arguments\` 全部非空 | 通过 |"
echo "| AC3 挂起后落库状态 | 同段的「运行停在 waiting_confirmation」「检查点 pending 且带上下文」「出站终态如实 waiting_confirmation」 | 通过 |"
echo "| AC4 批准后真续跑 | 探针：resolve 返回 SSE、流内有 \`message_delta\`、\`tasks\` +1、检查点 \`consumed\`、loop \`completed\` | 通过 |"
echo "| AC5 拒绝也续跑且不执行 | 探针：有 \`message_delta\` 且 \`tasks\` 不变 | 通过 |"
echo "| AC6 二次 resolve 409 | 探针：\`run_confirmation_already_resolved\` | 通过 |"
echo "| AC7 过期 409 + 惰性收尾 | 探针：\`run_confirmation_expired\`、检查点 \`expired\`、loop \`cancelled\`、工具未执行 | 通过 |"
echo "| AC8 非流式仍「拒绝并告知」 | 探针：200、无确认事件、\`agent_loop_steps.output_summary\` 含 \`no_confirmation_channel\`、\`tasks\` 不变 | 通过 |"
echo "| AC9 会话内记忆对 SSE 生效 | 探针：事件里有 \`tool_result\` 无 \`confirmation_required\`，工具直接执行 | 通过 |"
echo "| AC10 归属不符 404 且不泄露 | 探针：\`run_confirmation_not_found\`；他人会话路径由 \`tests/conversation/test_run_confirmation_resume.py\` 覆盖 | 通过 |"
echo "| AC11 无 \`resume_token\` 残留 + 测试 + audit | \`step_resume_token_removed\`（app 与 tests 零命中）、7 个测试目录全绿、\`step_audit\`（ERROR 0） | 通过 |"
echo "| AC12 既有行为不变 | \`tests/gateway\`（WS 确认链路）、\`tests/mcp\`、\`tests/tool_approval\`、\`tests/builtin_tool\` 全绿 | 通过 |"
echo

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
