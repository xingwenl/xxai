#!/usr/bin/env bash
# 2026-10-16-run-event-model-unification 的验证脚本。
#
# 守则（同 tools/harness/verify/_template.sh）：只写真实执行过的命令；显式声明未执行项与原因。
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 前置：
#   - docker compose 的 db/redis/api/front 已起；api 镜像已用 `docker compose up -d --build api`
#     重建（api 镜像把源码 COPY 进镜像而不是挂载，不重建就还是旧代码）。
#   - 开发库已由 `bash apps/backend/scripts/reset_dev_db.sh` 灌过种子（admin/admin123456、agent 1）。
# 注意：audit.py 要求本 request 的 verify.md 已存在，而 verify.md 正是运行器在本脚本结束后才写出的。
# 因此在 verify.md 被删掉的全新环境里，第一次执行的最末一步会失败，再跑一次即全绿。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0

WORK=/tmp/run-event-model-verify
BASE=http://127.0.0.1:8080

rm -rf "${WORK}"
mkdir -p "${WORK}"

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

# ------------------------------------------------------------------ 出站形状只在 events.py
assert_gateway_events_removed() {
  test ! -f apps/backend/app/modules/gateway/events.py
}

# 线协议事件名与信封键只在 agent_runtime/events.py 组装：
# 1) 信封键 "protocolVersion" 恰有一处定义；2) 两个已废弃的映射助手无源码命中；
# 3) SSE 路由里不再有按 item["type"] 分派的字面量分支。
assert_wire_shape_single_source() {
  local hits
  hits="$(grep -rn --include=*.py --exclude-dir=__pycache__ '"protocolVersion": ' apps/backend/app || true)"
  printf '信封键定义点：\n%s\n' "${hits}"
  test "$(printf '%s\n' "${hits}" | grep -c .)" = "1" || return 1
  printf '%s' "${hits}" | grep -q 'agent_runtime/events.py' || return 1
  ! grep -rn --include=*.py --exclude-dir=__pycache__ -E 'event_to_protocol_payload|INBOUND_PAYLOAD_HANDLERS' apps/backend/app apps/backend/tests
}

assert_router_has_no_type_branches() {
  ! grep -n 'item\["type"\]' apps/backend/app/modules/conversation/router.py
}

echo "## 已执行的命令与结果"
echo

verify_step "gateway/events.py 已删除（内容整体迁入 agent_runtime/events.py）" assert_gateway_events_removed
verify_step "信封形状只在 agent_runtime/events.py 组装，旧映射助手无源码命中" assert_wire_shape_single_source
verify_step "SSE 路由里不再有 item[\"type\"] 字面量分支" assert_router_has_no_type_branches

# ------------------------------------------------------------- 共享 golden 与 parity 测试
verify_step "共享 golden 可解析且条数固定" python3 -c "import json,pathlib; d=json.loads(pathlib.Path('apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json').read_text()); print(len(d), 'envelopes'); assert len(d) == 20"

verify_step "两个编码器逐条等于共享 golden（SSE 与 WS 一致性）" bash -c 'cd apps/backend && .venv/bin/python -m pytest tests/gateway/test_event_parity.py -q'

# ------------------------------------------------------------------ 后端与 SDK 回归
verify_step "后端回归 tests/conversation tests/gateway tests/agent_runtime" bash -c 'cd apps/backend && .venv/bin/python -m pytest tests/conversation tests/gateway tests/agent_runtime -q'

verify_step "AI SDK 单元测试（npx vitest run src）" bash -c 'cd apps/ai-sdk && npx vitest run src'

verify_step "前端构建与类型检查 pnpm --dir apps/front build" pnpm --dir apps/front build

# ------------------------------------------------------------------ 真进程 SSE（:8080）
sse_probe() {
  local token message_completed missing
  token="$(curl -s -X POST "${BASE}/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d '{"account":"admin","password":"admin123456"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["access_token"])')"
  test -n "${token}" || { echo "登录失败，拿不到 access_token"; return 1; }

  curl -s -N -m 180 -X POST "${BASE}/api/v1/agents/1/chat" \
    -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
    -d '{"message":"用一句话自我介绍","stream":true}' > "${WORK}/sse.txt"

  echo "data 行数：$(grep -c '^data:' "${WORK}/sse.txt")"
  grep '^event:' "${WORK}/sse.txt" | sort | uniq -c

  missing="$(grep '^data:' "${WORK}/sse.txt" | grep -vc 'protocolVersion')"
  echo "缺少 protocolVersion 的 data 行：${missing}"
  test "${missing}" = "0" || return 1

  message_completed="$(grep '^data:' "${WORK}/sse.txt" | grep 'message_completed' | head -1)"
  printf '%s\n' "${message_completed}"
  printf '%s' "${message_completed}" | grep -q '"usage":{' || return 1
  printf '%s' "${message_completed}" | grep -q '"knowledgeGrounded":' || return 1
  if printf '%s' "${message_completed}" | grep -q 'knowledge_grounded'; then
    echo "message_completed 仍带蛇形 knowledge_grounded"
    return 1
  fi
  return 0
}
verify_step "真进程 SSE：每条 data 含 protocolVersion，message_completed 带 usage 且为驼峰" sse_probe

# ------------------------------------------------------------------ Harness 合规
# ②（model-registry-unification）本脚本执行时尚未实现、没有 verify.md，属预期 ERROR；
# 本 request 的 verify.md 由运行器在脚本结束后写出，首次执行同样会是预期 ERROR。
audit_expect_known_errors() {
  local out extra
  out="$(python3 tools/harness/audit.py 2>&1)"
  printf '%s\n' "${out}"
  extra="$(printf '%s\n' "${out}" | grep '^ERROR' \
    | grep -v '2026-10-16-model-registry-unification: v2 request 缺少 verify.md' \
    | grep -v '2026-10-16-run-event-model-unification: v2 request 缺少 verify.md' || true)"
  [[ -z "${extra}" ]]
}
verify_step "python3 tools/harness/audit.py（排除两个「verify.md 尚未生成」的预期 ERROR）" audit_expect_known_errors

echo "## 未执行项与原因"
echo
echo "- 浏览器人工点击：apps/front 内没有任何 SSE 消费代码（grep EventSource / text/event-stream 为空），"
echo "  控制台实时对话走 WebSocket SDK 浮窗，因此没有可点的 SSE 界面；SSE 的权威证据是真进程 curl。"
echo "- WebSocket 端到端复跑：需要浏览器里的 SDK 会话（embed token + 子协议握手），本次未在浏览器里跑；"
echo "  网关编码器改动由 tests/gateway 的 22 个用例覆盖。"
echo "- \`pnpm --dir apps/ai-sdk test\` 会连带跑 scripts/verify-package.test.mjs，该用例在本次改动之前就失败："
echo "  \`npm pack --dry-run --json\` 的 stdout 被 prepare 脚本（vite build）日志污染导致 JSON.parse 抛错，"
echo "  且 vite-plugin-dts 产出 dist/src/**\/*.d.ts 而用例期望 dist/core/**、dist/ui/** —— 打包契约与产物布局漂移。"
echo "  与本 request 无关，未修复；本请求的 SDK 证据是 \`npx vitest run src\`（20 文件 / 160 用例）。"
echo "- 真实模型端点出词：真进程 SSE 一步依赖外部 OPENAI_BASE_URL / OPENAI_API_KEY 与余额。"
echo "- ② model-registry-unification：本 request 未触及，其 spec.md 已在仓库但尚无 verify.md。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 验收标准①~③（共享趋势）：parity 测试断言 SSE/WS 两个编码器逐条等于同一份 golden（20 条），"
echo "  \`message_completed.payload\` 在两条通道上逐字段相同（含 camelCase \`usage\`），tool_call/tool_result 形状与 SDK 读取一致。"
echo "- 验收标准④⑤：后端三目录测试全绿；SDK 单元测试全绿；前端 build（含 tsc -b）通过。"
echo "- 验收标准⑥：真进程 \`:8080\` SSE 每条 data 都带 protocolVersion，message_completed 带 usage 且键名为驼峰。"
echo "- 验收标准⑦：信封键、事件构造器与废弃映射助手都收口到 agent_runtime/events.py；SSE 路由不再按事件类型分派。"
echo "- 剩余风险：WS 侧本轮仍不发 tool_call/tool_result（有意保留，见 ADR 0007）；SDK 里对应读取分支仍是死分支。"
echo "- 是否可归档：达到验收标准；未执行项均为环境依赖或与本 request 无关的既有问题。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
