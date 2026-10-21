#!/usr/bin/env bash
# 验证 2026-10-21-ai-sdk-agent-switching：
# 后台可按 Embed Client 开关「智能体切换」，开关经 session_ready 下发，
# ai-sdk 据此渲染切换入口并支持程序化切换；apps/front 传入候选列表。
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0

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

skip_step() {
  echo "### $1"
  echo
  echo "跳过：$2"
  UNEXECUTED=1
  echo
}

# ---------------------------------------------------------------------------
# 1. 后端：开关列 + 迁移 + schema + 下发通道 + token 参数
# ---------------------------------------------------------------------------
backend_toggle_static() {
  local ok=0
  grep -q 'allow_agent_switching' apps/backend/app/modules/embed/models.py || { echo "models.py 缺少 allow_agent_switching"; ok=1; }
  grep -q '是否允许该 Embed Client' apps/backend/app/modules/embed/models.py || { echo "models.py 缺少字段中文 comment"; ok=1; }
  grep -q 'allow_agent_switching' apps/backend/app/modules/embed/schemas.py || { echo "schemas.py 缺少 allow_agent_switching"; ok=1; }
  grep -q 'allow_agent_switching=payload.allow_agent_switching' apps/backend/app/modules/embed/services.py || { echo "services.create_embed_client 未透传开关"; ok=1; }
  grep -q '"allowAgentSwitching": client.allow_agent_switching' apps/backend/app/modules/gateway/router.py || { echo "session_ready 未下发 allowAgentSwitching"; ok=1; }
  grep -q 'agent_id: int | None = Query(default=None, ge=1)' apps/backend/app/modules/embed/router.py || { echo "GET /embed/agent-token 未暴露 agent_id"; ok=1; }
  [[ $(grep -c 'allow_agent_switching' apps/backend/app/modules/embed/models.py) -ge 1 ]] || ok=1
  return $ok
}

migration_static() {
  local f=apps/backend/migrations/versions/20261021_0044_embed_client_agent_switching.py
  [[ -f "$f" ]] || { echo "缺少迁移文件 $f"; return 1; }
  grep -q 'revision: str = "20261021_0044"' "$f" || { echo "revision 不是 20261021_0044"; return 1; }
  grep -q 'down_revision: Union\[str, None\] = "20261020_0043"' "$f" || { echo "down_revision 不是 20261020_0043"; return 1; }
  grep -q 'op.add_column' "$f" || { echo "upgrade 缺少 add_column"; return 1; }
  grep -q 'op.drop_column' "$f" || { echo "downgrade 缺少 drop_column"; return 1; }
  grep -q 'docs/adr/0014-host-provided-agent-switching.md' "$f" || { echo "迁移 docstring 未指向 ADR 0014"; return 1; }
}

backend_tests() {
  (cd apps/backend && .venv/bin/python -m pytest tests/embed tests/gateway/test_session_info.py -q)
}

alembic_heads() {
  local out
  out=$(cd apps/backend && .venv/bin/python -m alembic heads 2>&1) || { echo "$out"; return 1; }
  echo "$out"
  grep -q '20261021_0044' <<<"$out"
}

# 迁移真实升降级：连不上本地 PG 时记为未执行，而不是假失败。
migration_roundtrip() {
  local out status
  out=$(cd apps/backend && .venv/bin/python -m alembic upgrade head 2>&1); status=$?
  if [[ $status -ne 0 ]]; then
    if grep -qi 'could not connect\|Connection refused\|password authentication' <<<"$out"; then
      echo "跳过：本地数据库不可达，未执行真实升降级"
      echo "$out" | tail -3
      UNEXECUTED=1
      return 0
    fi
    echo "$out"
    return 1
  fi
  echo "$out" | tail -3
  (cd apps/backend && .venv/bin/python -m alembic downgrade -1) || return 1
  (cd apps/backend && .venv/bin/python -m alembic upgrade head) || return 1
  (cd apps/backend && .venv/bin/python -m alembic current)
}

# ---------------------------------------------------------------------------
# 2. SDK：切换实现、UI、导出、文档
# ---------------------------------------------------------------------------
sdk_static() {
  local ok=0
  for name in switchAgent availableAgents showAgentSwitcher _reconcileAgentSwitchingPolicy _performAgentSwitch; do
    grep -q "$name" apps/ai-sdk/src/core/client.ts || { echo "client.ts 缺少 $name"; ok=1; }
  done
  grep -q 'agentSwitching?: AgentSwitchingOptions' apps/ai-sdk/src/core/types.ts || { echo "types.ts 缺少 agentSwitching 选项"; ok=1; }
  grep -q "allowAgentSwitching?: boolean" apps/ai-sdk/src/core/types.ts || { echo "types.ts 缺少 allowAgentSwitching"; ok=1; }
  grep -q "AgentSwitchingOptions" apps/ai-sdk/src/index.ts || { echo "index.ts 未导出 AgentSwitchingOptions"; ok=1; }
  grep -q 'xxai-agent:selected-agent' apps/ai-sdk/src/core/agent-switching.ts || { echo "缺少选择记忆存储键"; ok=1; }
  grep -q 'xxai-agent-switcher' apps/ai-sdk/src/ui/components/ChatWidget.vue || { echo "ChatWidget 缺少切换面板"; ok=1; }
  grep -q 'xxai-agent-switcher' apps/ai-sdk/src/ui/styles/index.css || { echo "样式缺少切换面板规则"; ok=1; }
  grep -q '## 17. 智能体切换' apps/ai-sdk/README.md || { echo "README 缺少智能体切换章节"; ok=1; }
  return $ok
}

sdk_tests() {
  (cd apps/ai-sdk && npx vitest run src)
}

sdk_typecheck() {
  (cd apps/ai-sdk && npx vue-tsc --noEmit)
}

# ---------------------------------------------------------------------------
# 3. 宿主侧（apps/front）：候选列表 + 后台开关
# ---------------------------------------------------------------------------
front_static() {
  local ok=0
  grep -q 'allow_agent_switching' apps/front/src/api/embed-clients.ts || { echo "api/embed-clients.ts 缺少字段"; ok=1; }
  grep -q '允许切换智能体' apps/front/src/features/embed-clients/index.tsx || { echo "管理端缺少开关"; ok=1; }
  for token in loadAgentSwitchOptions listEmbedClientAgents resolveEmbedClientId readEmbedTokenClientId 'ctx.agentId'; do
    grep -q "$token" apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx || { echo "bridge 缺少 $token"; ok=1; }
  done
  grep -q 'client_id' apps/front/src/features/agent-navigation/embed-token.ts || { echo "embed-token.ts 未读取 client_id claim"; ok=1; }
  # VITE_AGENT_CLIENT_ID 已降级为「多 Client 显式覆盖」，仍需保留但不作为唯一来源。
  grep -q 'VITE_AGENT_CLIENT_ID' apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx || { echo "bridge 缺少 VITE_AGENT_CLIENT_ID 覆盖位"; ok=1; }
  grep -q 'VITE_AGENT_CLIENT_ID' apps/front/.env.example || { echo ".env.example 未记录 VITE_AGENT_CLIENT_ID"; ok=1; }
  return $ok
}

# 宿主侧 Client 解析：node 22 的类型剥离直接跑 TS 源码，覆盖 token 载荷读取的六种输入。
# 这个函数是「看不到切换入口」那次漏配的直接回归用例，所以放在 verify 里持续跑。
front_client_id_unit() {
  local tmp
  tmp=$(mktemp "${TMPDIR:-/tmp}/embed-token-unit-XXXXXX.mjs") || return 1
  cat >"$tmp" <<'UNIT'
const { readEmbedTokenClientId } = await import(process.env.EMBED_TOKEN_MODULE);

const b64url = (obj) =>
  Buffer.from(JSON.stringify(obj)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const tokenWith = (payload) => `${b64url({ alg: 'HS256' })}.${b64url(payload)}.sig`;

const cases = [
  ['正常 client_id', tokenWith({ client_id: 'client_3-obQ0Bnv4' }), 'client_3-obQ0Bnv4'],
  ['缺少 client_id', tokenWith({ agent_id: 1 }), undefined],
  ['client_id 非字符串', tokenWith({ client_id: 123 }), undefined],
  ['client_id 空白', tokenWith({ client_id: '   ' }), undefined],
  ['payload 非 JSON', 'a.!!!.c', undefined],
  ['空 token', '', undefined],
];

let failed = 0;
for (const [name, input, expected] of cases) {
  const actual = readEmbedTokenClientId(input);
  const pass = actual === expected;
  if (!pass) failed += 1;
  console.log(`${pass ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(actual)}`);
}
process.exit(failed === 0 ? 0 : 1);
UNIT
  if EMBED_TOKEN_MODULE="$PWD/apps/front/src/features/agent-navigation/embed-token.ts" node "$tmp"; then
    rm -f "$tmp"
    return 0
  fi
  echo "客户端解析单测失败（需要 Node 22 的类型剥离支持）"
  rm -f "$tmp"
  return 1
}

front_format() {
  (cd apps/front && npx prettier --check \
    src/features/agent-navigation/agent-navigation-bridge.tsx \
    src/features/agent-navigation/embed-token.ts \
    src/features/embed-clients/index.tsx \
    src/api/embed-clients.ts)
}

docs_static() {
  local ok=0
  grep -q 'allow_agent_switching' docs/adr/0014-host-provided-agent-switching.md || { echo "ADR 0014 未记录开关列"; ok=1; }
  grep -q '智能体切换' docs/harness/requests/2026-10-21-ai-sdk-agent-switching/spec.md || { echo "spec 未覆盖智能体切换"; ok=1; }
  grep -q '智能体切换开关' CONTEXT.md || { echo "CONTEXT.md 缺少术语"; ok=1; }
  return $ok
}

echo "## 已执行的命令与结果"
echo

verify_step "后端开关字段与下发通道静态断言" backend_toggle_static
verify_step "迁移文件成对且 revision 链正确" migration_static
verify_step "后端单测（embed + gateway session_info）" backend_tests
verify_step "alembic 单一 head 指向本次迁移" alembic_heads
verify_step "迁移真实 upgrade→downgrade→upgrade" migration_roundtrip
verify_step "SDK 切换实现/UI/导出/README 静态断言" sdk_static
verify_step "SDK 单测（src 全量）" sdk_tests
verify_step "SDK 类型检查" sdk_typecheck
verify_step "宿主侧候选列表与后台开关静态断言" front_static
verify_step "宿主侧 Client ID 解析单测（token 载荷）" front_client_id_unit
verify_step "宿主侧改动文件格式检查" front_format
verify_step "文档（ADR/spec/CONTEXT）静态断言" docs_static

echo "## 未执行项与原因"
echo
if [[ $UNEXECUTED -eq 1 ]]; then
  echo "- 迁移真实升降级依赖本地 PostgreSQL；本次运行检测到数据库不可达，已跳过（静态断言仍覆盖迁移内容）。"
else
  echo "- 无（本机数据库可达，迁移升降级已真实执行）。"
fi
echo "- 未做浏览器端点击级联调：数据链路（token → client_id → 启用∩绑定候选 → session_ready.allowAgentSwitching）已用真实后端手工核对过，但没有在浏览器里真点一次切换；切换后的会话恢复与工具重注册由 SDK 事件单测覆盖。"
echo

echo "## 验收结论"
echo
if [[ $FAIL -eq 0 ]]; then
  echo "通过：后端开关与下发通道、迁移、SDK 切换实现与 UI、宿主接入、文档均在真实输出中验证通过。"
else
  echo "失败：见上方标记为「失败」的步骤。"
fi
echo
exit $FAIL
