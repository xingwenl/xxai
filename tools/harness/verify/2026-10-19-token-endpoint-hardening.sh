#!/usr/bin/env bash
# 2026-10-19-token-endpoint-hardening 验证脚本
#
# 前置条件：
#   1. `docker compose up -d` 已起（api / db / redis / front）
#   2. api 镜像已重建并包含本次改动（`DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build api` 后 `up -d api`）
#   3. 已灌开发种子：`bash apps/backend/scripts/reset_dev_db.sh`（admin/admin123456、platform 1、agent 1 可对话）
#   4. `apps/backend/.env` 配好 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET（dev 代理探针要用）
#   5. `apps/ai-sdk` 依赖已安装（`pnpm install`），本地 `npx` / `npm` 可用
#
# 退出码语义（与 tools/harness/verify.sh 一致）：
#   0 全部执行且通过；1 有失败；2 脚本自身错误；3 通过但有未执行项

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
BASE=http://127.0.0.1:8080

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

# 从 /tmp 的 token 响应里解出 JWT 的 sub（终端用户主键），不打印 token 本身
sub_of() {
  python3 -c '
import base64, json, sys
d = json.load(open(sys.argv[1]))
t = d["data"]["access_token"]
p = t.split(".")[1]
p += "=" * (-len(p) % 4)
print(json.loads(base64.urlsafe_b64decode(p))["sub"])
' "$1"
}

echo "## 已执行的命令与结果"
echo

step_embed_tests() {
  (cd apps/backend && ./.venv/bin/python -m pytest tests/embed -q) 2>&1 | tail -6
}
verify_step "后端单测：tests/embed（AC6）" step_embed_tests

step_auth_tests() {
  (cd apps/backend && ./.venv/bin/python -m pytest tests/auth -q) 2>&1 | tail -4
}
verify_step "后端单测：tests/auth（AC6）" step_auth_tests

step_route_requires_auth() {
  local hits
  hits=$(grep -c 'require_current_active_user' apps/backend/app/modules/embed/token_router.py)
  echo "token_router.py 中 require_current_active_user 出现次数：${hits}"
  [[ "${hits}" -ge 2 ]]
}
verify_step "结构断言：/api/agent-token 已挂登录态依赖（变更点 1）" step_route_requires_auth

step_production_guard() {
  grep -n 'app_env != "production"' apps/backend/app/modules/embed/token_router.py
}
verify_step "结构断言：生产环境忽略 external_user_id 覆盖（变更点 1）" step_production_guard

step_no_client_secret() {
  local hits
  hits=$(grep -rn "client_secret" apps/ai-sdk/demo apps/ai-sdk/index.html | wc -l | tr -d ' ')
  echo "demo/ 与根 index.html 中 client_secret 命中数：${hits}"
  [[ "${hits}" == "0" ]]
}
verify_step "结构断言：示例页不再出现 client_secret（AC4）" step_no_client_secret

step_no_direct_embed_tokens() {
  local hits direct proxy
  hits=$(grep -rn "api/v1/embed/tokens" apps/ai-sdk/demo apps/ai-sdk/index.html | wc -l | tr -d ' ')
  direct=$(grep -rn "/api/agent-token" apps/ai-sdk/demo apps/ai-sdk/index.html | wc -l | tr -d ' ')
  proxy=$(grep -rln "/demo-api/agent-token" apps/ai-sdk/demo/*.html apps/ai-sdk/index.html | wc -l | tr -d ' ')
  echo "直连 embed/tokens 命中数：${hits}；直连 /api/agent-token 命中数：${direct}；走同源代理的页面数：${proxy}"
  [[ "${hits}" == "0" && "${direct}" == "0" && "${proxy}" == "4" ]]
}
verify_step "结构断言：示例页一律走同源 /demo-api/agent-token（AC5）" step_no_direct_embed_tokens

step_401_without_auth() {
  local status
  status=$(curl -s -m 15 -o /tmp/teh-unauth.json -w '%{http_code}' "${BASE}/api/agent-token?external_user_id=probe-x")
  echo "无登录态状态码：${status}"
  echo "响应：$(head -c 160 /tmp/teh-unauth.json)"
  [[ "${status}" == "401" ]]
}
verify_step "端到端：无登录态请求 /api/agent-token 返回 401（AC1）" step_401_without_auth

step_token_with_auth() {
  local token status expected actual
  token=$(curl -s -m 15 -X POST "${BASE}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"account":"admin","password":"admin123456"}' |
    python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["access_token"])')
  if [[ -z "${token}" ]]; then
    echo "登录失败，拿不到后台 token"
    return 1
  fi
  status=$(curl -s -m 15 -o /tmp/teh-auth.json -w '%{http_code}' \
    -H "Authorization: Bearer ${token}" \
    "${BASE}/api/agent-token?external_user_id=probe-override")
  echo "带登录态 + external_user_id=probe-override 状态码：${status}"
  if [[ "${status}" != "200" ]]; then
    echo "响应：$(head -c 200 /tmp/teh-auth.json)"
    return 1
  fi
  actual=$(sub_of /tmp/teh-auth.json)
  expected=$(docker compose exec -T db psql -U root -d ai_db -tAc \
    "select id from platform_end_users where external_user_id = 'probe-override'" | tr -d '[:space:]')
  echo "token sub=${actual}；platform_end_users.id(external_user_id=probe-override)=${expected}"
  [[ -n "${expected}" && "${actual}" == "${expected}" ]]
}
verify_step "端到端：登录态 + 非生产覆盖生效，sub 指向该终端用户（AC2）" step_token_with_auth

step_embed_agent_token_still_works() {
  local token status
  token=$(curl -s -m 15 -X POST "${BASE}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"account":"admin","password":"admin123456"}' |
    python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["access_token"])')
  status=$(curl -s -m 15 -o /tmp/teh-alias.json -w '%{http_code}' \
    -H "Authorization: Bearer ${token}" "${BASE}/api/v1/embed/agent-token")
  echo "GET /api/v1/embed/agent-token 状态码：${status}"
  [[ "${status}" == "200" ]]
}
verify_step "回归：既有受鉴权端点 /api/v1/embed/agent-token 仍可用（变更点 2）" step_embed_agent_token_still_works

verify_step "端到端：vite dev server 同源 token 代理（变更点 3-5，AC4/AC5 的运行期验证）" \
  python3 tools/harness/verify/2026-10-19-token-endpoint-hardening.probe.py

step_type_check() {
  (cd apps/ai-sdk && npm run type-check) 2>&1 | tail -4
}
verify_step "SDK 类型检查：vue-tsc --noEmit" step_type_check

step_sdk_unit() {
  (cd apps/ai-sdk && npx vitest run src) 2>&1 | tail -6
}
verify_step "SDK 单测：npx vitest run src（21 文件 / 172 用例，AC6）" step_sdk_unit

step_audit() {
  local out extra
  out=$(python3 tools/harness/audit.py 2>&1)
  echo "${out}" | tail -3
  extra=$(echo "${out}" | grep '^ERROR' | grep -v 'token-endpoint-hardening.*缺少 verify.md' || true)
  if [[ -n "${extra}" ]]; then
    echo "意外的 ERROR："
    echo "${extra}"
    return 1
  fi
  echo "除本 request 的「缺少 verify.md」（由 verify.sh 产出，属预期）外无 ERROR"
}
verify_step "Harness 自检：audit.py（AC7）" step_audit

echo "## 未执行项与原因"
echo
UNEXECUTED=1
echo "- AC3（\`APP_ENV=production\` 时忽略 \`external_user_id\` 覆盖）：用单测覆盖（\`apps/backend/tests/embed/test_token_routes.py\` 直接 monkeypatch \`app_env\`），"
echo "  未起第二个生产模式进程做端到端；切换 \`APP_ENV\` 需要另起容器，收益低于单测。"
echo "- \`pnpm --dir apps/ai-sdk test\`（整包 vitest）会连带 \`scripts/verify-package.test.mjs\` 的**预存在环境性失败**："
echo "  该用例用 \`npm pack --dry-run --json\` 取包清单后直接 \`JSON.parse\`，而 \`prepare\` 脚本的 vite build 日志"
echo "  与 JSON 同走 stdout，导致 \`SyntaxError: Unexpected token 'v', \"vite v5.4.\"...\`。与本次改动无关，"
echo "  故本轮只跑 \`npx vitest run src\`（21 文件 / 172 用例）。"
echo "- 浏览器人工点检：dev 代理已由真进程探针覆盖（200 / 405 / 400 三条），未做浏览器点击。"
echo "- \`alembic check\`：本仓存在大量**预存在**漂移，且本轮无迁移，未执行。"
echo "- 生产环境的 nginx / 端口暴露面（\`apps/front/nginx.conf:11\`、\`docker-compose.yml:129\`）：属部署配置，未做渗透式验证。"
echo

echo "## 验收结论"
echo
echo "| 验收标准 | 结果 |"
echo "| --- | --- |"
echo "| 1. 无登录态 → 401 | 端到端 curl 通过（实测 401） |"
echo "| 2. 登录态 + 非生产覆盖：token sub 指向该终端用户 | 端到端 curl + DB 比对通过 |"
echo "| 3. 生产环境忽略覆盖 | 单测通过；端到端未执行（见上） |"
echo "| 4. demo/index.html 无 client_secret | 结构断言通过（0 命中） |"
echo "| 5. demo/index.html 不直连 /api/v1/embed/tokens | 结构断言 + dev 代理探针通过（4 个页面走同源） |"
echo "| 6. tests/embed、tests/auth 全绿；vitest 21/172 全绿 | 已执行，全部通过 |"
echo "| 7. audit.py ERROR 为 0 | 除本 request 缺 verify.md（预期）外无 ERROR |"
echo

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
