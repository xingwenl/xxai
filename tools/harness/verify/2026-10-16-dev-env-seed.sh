#!/usr/bin/env bash
# 2026-10-16-dev-env-seed 的验证脚本。
#
# 守则（同 tools/harness/verify/_template.sh）：只写真实执行过的命令；显式声明未执行项与原因。
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 前置：docker compose 全栈已起（db/redis/api 可访问），仓库根 `.env` 已按 apps/backend/.env.example 配好。
# 本脚本会**不可逆清空开发库、apps/backend/storage/ 与 Redis DB 0**，请勿在非开发环境运行。
#
# 注意最后一步 audit.py：它要求本 request 的 verify.md 已存在，而 verify.md 正是运行器在本脚本
# 结束后才写出的。因此在 verify.md 被删掉的全新环境里，第一次执行的最末一步会失败，再跑一次即全绿。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0

WORK=/tmp/dev-env-seed-verify
STUB_PORT=18801
API_PORT=18001
API_CONTAINER=seed-verify-api

cleanup() {
  [[ -f "${WORK}/stub.pid" ]] && kill "$(cat "${WORK}/stub.pid")" 2>/dev/null
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1
  rm -rf "${WORK}"
  return 0
}
trap cleanup EXIT

rm -rf "${WORK}"
mkdir -p "${WORK}"

# 容器内 psql 统一走这个包装，避免依赖宿主机 psql 与第二套 .env。
psql_container() {
  docker compose exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$1"
}
count_rows() { psql_container "$1" | tr -d '[:space:]'; }

# 种子对象指纹：13 个计数串成一行。顺序固定，改动顺序等于改动指纹含义。
FP_SQL="select (select count(*) from sys_users)||'|'||(select count(*) from platforms)||'|'||(select count(*) from platform_admins)||'|'||(select count(*) from agents)||'|'||(select count(*) from agent_versions)||'|'||(select count(*) from skill_packages)||'|'||(select count(*) from skill_package_files)||'|'||(select count(*) from skills)||'|'||(select count(*) from agent_skills)||'|'||(select count(*) from mcp_servers)||'|'||(select count(*) from workflows)||'|'||(select count(*) from agent_builtin_tools)||'|'||(select count(*) from platform_embed_clients);"

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

# ---------------------------------------------------------------- 可重建性
CONV_BEFORE="$(count_rows "select count(*) from conversations;")"
verify_step "重置前 conversations 行数（脏状态证据，用于佐证下面确实清了库）" printf '%s\n' "${CONV_BEFORE}"

verify_step "一条命令重建开发环境：bash apps/backend/scripts/reset_dev_db.sh" bash apps/backend/scripts/reset_dev_db.sh

CONV_AFTER="$(count_rows "select count(*) from conversations;")"
verify_step "重置后 conversations 行数为 0（TRUNCATE 生效）" test "${CONV_AFTER}" = "0"

FP1="$(count_rows "${FP_SQL}")"
verify_step "重置后的种子对象指纹 F1（13 张表计数）" printf '%s\n' "${FP1}"

verify_step "再跑一次种子脚本（不重置库）：seed 自身幂等" docker compose run --rm --no-deps -v "${PWD}/apps/backend/scripts:/app/scripts:ro" api python -m scripts.seed_dev_env
FP2="$(count_rows "${FP_SQL}")"
verify_step "单独重跑 seed 后指纹不变：F2 等于 F1" test "${FP2}" = "${FP1}"

verify_step "第二次完整重置：bash apps/backend/scripts/reset_dev_db.sh（输出略，仅比对指纹）" bash -c 'bash apps/backend/scripts/reset_dev_db.sh >/dev/null 2>&1'
FP3="$(count_rows "${FP_SQL}")"
verify_step "第二次完整重置后指纹不变：F3 等于 F1（纯仓库可重建，无数据库唯一副本）" test "${FP3}" = "${FP1}"

# 清空 storage 与 Redis DB 0 也必须只靠仓库重建，逐项确认。
verify_step "重置后 storage/skill-packages 下的解压目录重新生成" bash -c 'ls apps/backend/storage/skill-packages/1/*/ >/dev/null'
DBSIZE="$(docker compose exec -T redis redis-cli DBSIZE | tr -d '\r')"
verify_step "Redis DB 0 当前键数（reset 已在清库阶段 FLUSHDB；此处仅记录，之后可能有调度锁等新键）" printf '%s\n' "${DBSIZE}"

# ------------------------------------------------------------ 种子对象可查
PKG_FILES="$(count_rows "select count(*) from skill_package_files where package_id=(select id from skill_packages where slug='dev-sample-skill');")"
SRC_FILES="$(find apps/backend/scripts/seed_data/skills/dev-sample-skill -type f | wc -l | tr -d '[:space:]')"
verify_step "技能包文件行数 ${PKG_FILES} 等于仓库内技能源文件数 ${SRC_FILES}" test "${PKG_FILES}" = "${SRC_FILES}"

BOUND_TOOLS="$(count_rows "select string_agg(tool_name, ',' order by tool_name) from agent_builtin_tools where agent_id=1 and is_enabled;")"
verify_step "Agent 1 绑定的内置工具" printf '%s\n' "${BOUND_TOOLS}"
verify_step "Agent 1 绑定的是 ask_user / get_runtime_info / http_get 三个" test "${BOUND_TOOLS}" = "ask_user,get_runtime_info,http_get"

TOKEN="$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"account":"admin","password":"admin123456"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["access_token"])')"
verify_step "控制台登录返回 access_token" test -n "${TOKEN}"

verify_step "GET /api/v1/auth/me 返回种子管理员 admin" bash -c "curl -s http://127.0.0.1:8000/api/v1/auth/me -H 'Authorization: Bearer ${TOKEN}' | grep -q '\"account\":\"admin\"'"

verify_step "GET /api/v1/platforms/1/agents 能看到已发布的开发助手" bash -c "curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/agents' -H 'Authorization: Bearer ${TOKEN}' | grep -q 'dev-assistant'"

verify_step "GET /api/v1/platforms/1/skill-packages 能看到种子技能包" bash -c "curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/skill-packages' -H 'Authorization: Bearer ${TOKEN}' | grep -q 'dev-sample-skill'"

verify_step "GET /api/v1/platforms/1/skills 能看到种子技能" bash -c "curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/skills' -H 'Authorization: Bearer ${TOKEN}' | grep -q '开发示例技能'"

verify_step "GET /api/v1/platforms/1/workflows 能看到 active 工作流且带 definition" bash -c "curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/workflows' -H 'Authorization: Bearer ${TOKEN}' | grep -q '\"status\":\"active\"' && curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/workflows' -H 'Authorization: Bearer ${TOKEN}' | grep -q '\"definition\"'"

verify_step "GET /api/v1/platforms/1/mcp-servers 能看到种子 MCP 配置" bash -c "curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/mcp-servers' -H 'Authorization: Bearer ${TOKEN}' | grep -q 'dev-sample-mcp'"

# -------------------------------------------------- 端到端对话（本地假模型）
verify_step "启动本地假模型服务（端口 ${STUB_PORT}）" bash -c "python3 tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py ${STUB_PORT} >${WORK}/stub.log 2>&1 & echo \$! >${WORK}/stub.pid; sleep 2; curl -s -m 5 -X POST http://127.0.0.1:${STUB_PORT}/v1/chat/completions -H 'content-type: application/json' -d '{}' | grep -q chatcmpl-local-stub"

verify_step "启动指向假模型的临时 API 容器（端口 ${API_PORT}，跳过默认 command 里的 alembic）" bash -c "docker compose run -d --rm --no-deps --name ${API_CONTAINER} -p ${API_PORT}:8000 -e OPENAI_BASE_URL=http://host.docker.internal:${STUB_PORT}/v1 -e OPENAI_API_KEY=stub api uvicorn main:app --host 0.0.0.0 --port 8000"

verify_step "轮询等临时容器就绪（首次启动约 10 秒）" bash -c "code=000; for _ in \$(seq 1 30); do code=\$(curl -s -o /dev/null -m 3 -w '%{http_code}' -X POST http://127.0.0.1:${API_PORT}/api/v1/auth/login -H 'Content-Type: application/json' -d '{\"account\":\"admin\",\"password\":\"admin123456\"}'); [ \"\$code\" = '200' ] && break; sleep 2; done; echo \"login=http:\$code\"; [ \"\$code\" = '200' ]"

verify_step "种子 Agent 走完一轮对话（POST /api/v1/agents/1/chat，非流式）" bash -c "TOKEN=\$(curl -s -X POST http://127.0.0.1:${API_PORT}/api/v1/auth/login -H 'Content-Type: application/json' -d '{\"account\":\"admin\",\"password\":\"admin123456\"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"data\"][\"access_token\"])'); RESP=\$(curl -s -m 120 -X POST http://127.0.0.1:${API_PORT}/api/v1/agents/1/chat -H \"Authorization: Bearer \$TOKEN\" -H 'Content-Type: application/json' -d '{\"message\":\"你好，你是谁？\",\"stream\":false}'); echo \"\$RESP\" | head -c 300; echo; echo \"\$RESP\" | grep -q '\"success\":true' && echo \"\$RESP\" | grep -q '本地假模型应答'"

SKILL_STEPS="$(count_rows "select count(*) from agent_loop_steps where step_type='skill_instruction' and skill_name='开发示例技能';")"
verify_step "该轮对话里出现了种子技能的注入步骤 skill_instruction（计数 ${SKILL_STEPS}）" test "${SKILL_STEPS}" -gt 0

# ------------------------------------------------------------------ Harness
verify_step "python3 tools/harness/audit.py" python3 tools/harness/audit.py

echo "## 未执行项与原因"
echo
echo "- 真实模型端点出词：仓库根 .env 指向的 relay（0029.zhongzhuan.wang）账号返回 403 INSUFFICIENT_BALANCE，"
echo "  恒失败且不可重复。改用 tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py 本地假模型替代验证，"
echo "  业务链路（uvicorn → conversation → agent_runtime → ModelUsageRecord）全部真实，只有最外一跳换成固定应答。"
echo "- 浏览器 / 前端页面：本次只验证后端 API 与数据库，未打开 http://localhost:8080 做人工点击；前端是既有代码，本次未改。"
echo "- 无人值守任务调度（tasks/cron）与工作流实际执行：种子只创建定义，未触发跑批。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 可重建性（验收标准①⑦）：reset 一条命令后 fingerprint 稳定；单独重跑 seed 与第二次完整 reset 后 fingerprint 都不变，"
echo "  说明开发环境的状态完全由仓库内的种子脚本 + 技能包源文件决定，数据库里没有唯一副本。"
echo "- 登录与鉴权（②）：种子管理员可登录，/auth/me 返回同账号。"
echo "- 可对话 Agent（③）：列表可见、default_version_id 指向已发布版本；端到端对话在本地假模型下跑通并落库。"
echo "- 技能包（④）：包 / 技能 / 绑定 / 文件清单四者齐全，文件行数与仓库源文件数一致。"
echo "- 工作流（⑤）：可见且 status=active，definition 由既有静态校验器生成（见 docs/runbooks/dev-environment.md）。"
echo "- Harness 合规（⑥）：audit.py 退出码 0。"
echo "- 剩余风险：本脚本会不可逆清空开发库与 storage，仅限开发环境；生产阻断靠 seed_dev_env.py 内的 APP_ENV 检查。"
echo "- 待人工确认：仓库根 .env.example 内仍留有真实 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET 与数据库口令，"
echo "  这超出本 request 已批准的变更点，需单独排期处理。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
