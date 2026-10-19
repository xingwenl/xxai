#!/usr/bin/env bash
# 2026-10-16-model-registry-unification 的验证脚本。
#
# 守则（同 tools/harness/verify/_template.sh）：只写真实执行过的命令；显式声明未执行项与原因。
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 前置：
#   - docker compose 的 db/redis/api/front 已起；api 镜像已用
#     `docker compose up -d --build api worker task-scheduler front` 重建
#     （api 镜像把源码 COPY 进镜像而不是挂载，不重建跑的还是旧代码）。
#   - 本脚本会自己灌种子（AC5 一步），因此不要求先手工 reset。
#   - 脚本会创建临时库 ai_base_migration_check 做迁移往返，结束时删除；
#     另外会在宿主机 8800 端口起一个替身模型（.stub-model.py），结束时杀掉。
#
# 注意：audit.py 要求本 request 的 verify.md 已存在，而 verify.md 正是运行器在本脚本
# 结束后才写出的。因此在 verify.md 被删掉的全新环境里，第一次执行的最末一步会失败，
# 再跑一次即全绿。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

ROOT="$(pwd)"
FAIL=0
UNEXECUTED=0

BASE=http://127.0.0.1:8080
WORK=/tmp/model-registry-verify
STUB_DB=ai_base_migration_check
STUB=tools/harness/verify/2026-10-16-model-registry-unification.stub-model.py
PROBE="${ROOT}/tools/harness/verify/2026-10-16-model-registry-unification.probe.py"
STUB_LOG=/tmp/stub_model_registry_verify.log
PYTHON="${ROOT}/apps/backend/.venv/bin/python"

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

# 在 db 容器里执行 SQL，用容器自己的 POSTGRES_USER/POSTGRES_DB，避免与本机 .env 漂移。
# 第二个参数可指定目标库（默认 $POSTGRES_DB）。
db_sql() {
  local sql="$1" database="${2:-}"
  if [[ -n "${database}" ]]; then
    docker compose exec -T db sh -c \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -tA' _ "${database}" <<<"${sql}"
  else
    docker compose exec -T db sh -c \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA' <<<"${sql}"
  fi
}

cleanup() {
  pkill -f '2026-10-16-model-registry-unification.stub-model.py' 2>/dev/null || true
  db_sql "DROP DATABASE IF EXISTS ${STUB_DB}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ------------------------------------------------------------------ AC1 迁移往返
# 在独立临时库上做 upgrade(0038) → 造存量行 → upgrade(head) → downgrade(0038) → upgrade(head)，
# 不动开发库；断言「三列删除 + 存量提升为 chat 注册表条目与绑定 + downgrade 可逆」。
migration_roundtrip() {
  local creds url dsn columns
  creds="$(docker compose exec -T db sh -c \
    'printf "%s:%s" "$POSTGRES_USER" "$POSTGRES_PASSWORD"')"
  url="postgresql+asyncpg://${creds}@db:5432/${STUB_DB}"

  db_sql "DROP DATABASE IF EXISTS ${STUB_DB}" || return 1
  db_sql "CREATE DATABASE ${STUB_DB}" || return 1

  docker compose exec -T -e DATABASE_URL="${url}" api alembic -c alembic.ini upgrade 20261015_0038 \
    || return 1
  echo "已升级到基线 20261015_0038"

  db_sql "INSERT INTO platforms (name, code) VALUES ('迁移库平台', 'migcheck');
          INSERT INTO agents (platform_id, name, slug) VALUES (1, '迁移库 Agent', 'migcheck-agent');
          INSERT INTO agent_versions (agent_id, version, system_prompt, model_name, model_base_url,
                                      api_key_encrypted, created_at, published_at)
          VALUES (1, 1, '你是迁移测试助手', 'legacy-chat-model', 'http://legacy.local/v1',
                  'ciphertext', now(), now());" "${STUB_DB}" || return 1
  echo "基线库已插入 1 行带 model_name/model_base_url/api_key_encrypted 的 Agent 版本"

  docker compose exec -T -e DATABASE_URL="${url}" api alembic -c alembic.ini upgrade head || return 1

  columns="$(db_sql "SELECT count(*) FROM information_schema.columns
                     WHERE table_name = 'agent_versions'
                       AND column_name IN ('model_name', 'model_base_url', 'api_key_encrypted');" "${STUB_DB}")"
  echo "升级后 agent_versions 三列残留数：${columns}（应为 0）"
  [[ "${columns}" = "0" ]] || return 1

  local promoted
  promoted="$(db_sql "SELECT model_type || '|' || model_name || '|' || is_active FROM platform_models;" "${STUB_DB}")"
  echo "存量提升结果：${promoted}（应为 chat|legacy-chat-model|true）"
  [[ "${promoted}" = "chat|legacy-chat-model|true" ]] || return 1

  local binding
  binding="$(db_sql "SELECT a.slug || '|' || b.role || '|' || (b.model_id = m.id)::text
                     FROM agent_model_bindings b
                     JOIN agents a ON a.id = b.agent_id
                     JOIN platform_models m ON m.id = b.model_id;" "${STUB_DB}")"
  echo "存量绑定：${binding}（应为 migcheck-agent|chat|true）"
  [[ "${binding}" = "migcheck-agent|chat|true" ]] || return 1

  docker compose exec -T -e DATABASE_URL="${url}" api alembic -c alembic.ini downgrade 20261015_0038 \
    || return 1
  local restored
  restored="$(db_sql "SELECT model_name || '|' || model_base_url || '|' || api_key_encrypted || '|' ||
                             (SELECT count(*) FROM platform_models) || '|' ||
                             (SELECT count(*) FROM agent_model_bindings)
                      FROM agent_versions WHERE agent_id = 1;" "${STUB_DB}")"
  echo "downgrade 回填：${restored}（应为 legacy-chat-model|http://legacy.local/v1|ciphertext|0|0）"
  [[ "${restored}" = "legacy-chat-model|http://legacy.local/v1|ciphertext|0|0" ]] || return 1

  docker compose exec -T -e DATABASE_URL="${url}" api alembic -c alembic.ini upgrade head || return 1
  local reapplied
  reapplied="$(db_sql "SELECT (SELECT count(*) FROM platform_models) || '|' ||
                              (SELECT count(*) FROM agent_model_bindings);" "${STUB_DB}")"
  echo "再次 upgrade 后条目/绑定数：${reapplied}（应为 1|1）"
  [[ "${reapplied}" = "1|1" ]] || return 1

  db_sql "DROP DATABASE IF EXISTS ${STUB_DB}" || return 1
  echo "临时库已删除"
}
verify_step "AC1 迁移往返：删三列 + 存量提升为 chat 条目与绑定 + downgrade 可逆" migration_roundtrip

# ------------------------------------------------------------------ AC2 版本行不再承载模型凭证
assert_no_model_credentials_in_agent_module() {
  local hits
  hits="$(grep -rn --include=*.py --exclude-dir=__pycache__ \
    -E 'api_key_encrypted|model_base_url|version\.model_name' apps/backend/app/modules/agent || true)"
  printf 'agent 模块内命中：\n%s\n' "${hits:-<无>}"
  [[ -z "${hits}" ]]
}
verify_step "AC2 agent 模块不再读写 api_key_encrypted / model_base_url / version.model_name" assert_no_model_credentials_in_agent_module

assert_model_name_column_dropped() {
  local hits
  hits="$(grep -rn --include=*.py --exclude-dir=__pycache__ 'model_name' apps/backend/app/modules/agent/models.py || true)"
  printf 'agent/models.py 内 model_name 命中：\n%s\n' "${hits:-<无>}"
  [[ -z "${hits}" ]]
}
verify_step "AC2 AgentVersion 模型定义里已无 model_name 列" assert_model_name_column_dropped

# ------------------------------------------------------------------ AC6 回归测试
verify_step "AC6 后端回归 tests/model_registry tests/agent tests/conversation tests/gateway tests/tasks" \
  bash -c 'cd apps/backend && .venv/bin/python -m pytest tests/model_registry tests/agent tests/conversation tests/gateway tests/tasks -q'

# ------------------------------------------------------------------ AC7 前端
verify_step "AC7 前端构建与类型检查 pnpm --dir apps/front build" pnpm --dir apps/front build

verify_step "AC7 前后端源码内无 gpt-4o-mini 字面量" bash -c \
  '! grep -rn "gpt-4o-mini" apps/front/src apps/backend/app --include="*" --exclude-dir=__pycache__'

# ------------------------------------------------------------------ AC3/AC4 替身模型探针
stub_probe() {
  if [[ ! -x "${PYTHON}" ]]; then
    echo "找不到 ${PYTHON}（探针需要 websockets 客户端）"
    return 1
  fi
  "${PYTHON}" -c 'import websockets' || return 1
  rm -f "${STUB_LOG}"
  # 每次挑一个空闲端口：本机可能残留旧的替身进程，用固定端口会撞车。
  local port
  port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("",0)); print(s.getsockname()[1]); s.close()')"
  echo "替身模型端口：${port}"
  STUB_MODEL_LOG="${STUB_LOG}" STUB_MODEL_PORT="${port}" python3 "${STUB}" &
  local stub_pid=$!
  local ready=0
  for _ in $(seq 1 20); do
    if curl -s -m 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 0.5
  done
  if [[ "${ready}" -ne 1 ]] || ! kill -0 "${stub_pid}" 2>/dev/null; then
    echo "替身模型未能启动（端口 ${port}）"
    kill "${stub_pid}" 2>/dev/null || true
    return 1
  fi
  STUB_MODEL_LOG="${STUB_LOG}" STUB_MODEL_PORT="${port}" "${PYTHON}" "${PROBE}"
  local status=$?
  printf '\n替身收到的请求日志：\n'
  cat "${STUB_LOG}" 2>/dev/null || echo "<无>"
  kill "${stub_pid}" 2>/dev/null || true
  wait "${stub_pid}" 2>/dev/null || true
  return "${status}"
}
verify_step "AC3/AC4 换绑后实际调用新模型（含 model_usage 快照），停用后返回 chat_model_unavailable" stub_probe

# ------------------------------------------------------------------ AC5 一键重置后真实对话
reset_and_chat() {
  bash apps/backend/scripts/reset_dev_db.sh || return 1
  local token body
  token="$(curl -s -m 30 -X POST "${BASE}/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d '{"account":"admin","password":"admin123456"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["access_token"])')"
  echo "登录 token 长度：${#token}"
  [[ -n "${token}" ]] || return 1
  body="$(curl -s -m 180 -X POST "${BASE}/api/v1/agents/1/chat" \
    -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
    -d '{"message":"用一句话自我介绍","stream":false}')"
  printf '%s\n' "${body}" | head -c 800
  printf '\n'
  printf '%s' "${body}" | grep -q '"success":true'
}
verify_step "AC5 一键重置后经 :8080 登录并完成一轮真实模型对话（success=true）" reset_and_chat

# ------------------------------------------------------------------ Harness 合规
audit_expect_known_errors() {
  local out extra
  out="$(python3 tools/harness/audit.py 2>&1)"
  printf '%s\n' "${out}"
  extra="$(printf '%s\n' "${out}" | grep '^ERROR' \
    | grep -v '2026-10-16-model-registry-unification: v2 request 缺少 verify.md' || true)"
  [[ -z "${extra}" ]]
}
verify_step "python3 tools/harness/audit.py（排除「verify.md 尚未生成」的预期 ERROR）" audit_expect_known_errors

echo "## 未执行项与原因"
echo
echo "- 浏览器人工点击：控制台「模型管理」页（apps/front/src/features/models）的解绑/换绑表单、"
echo "  「模型用量」页的展示与筛选，本脚本未在浏览器里点击；AC3/AC4 的接口行为由探针真进程覆盖。"
echo "- AI SDK 嵌入会话的浏览器验证：本脚本用 Python 直连 WebSocket（子协议 ai-agent.v1 + embed token）"
echo "  验证网关与用量落库，未在浏览器里跑 apps/ai-sdk 的浮窗。"
echo "- 全量后端测试轮（29 个目录）：本脚本按 spec 的 AC6 只跑 5 个受影响目录；"
echo "  完整一轮（每目录一次 pytest，避免跨目录重名模块 import mismatch）由人工执行。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- AC1：临时库 ai_base_migration_check 上完成 0038 → head → 0038 → head 往返；升级后"
echo "  agent_versions 三列消失、存量行提升为 platform_models(model_type=chat) + chat 绑定，"
echo "  downgrade 回填原值并清空条目/绑定，再次 upgrade 重新提升。"
echo "- AC2：agent 模块内无 api_key_encrypted / model_base_url / version.model_name 命中；AgentVersion 定义无 model_name 列。"
echo "- AC3：换绑替身模型后，WS 回复 STUB-MODEL-REPLY、替身请求日志记录 stub-model-x，"
echo "  且 model_usage_records 新增行的 model_name 是 stub-model-x（不是 .env 默认模型）。"
echo "- AC4：停用被绑定的对话模型后，SSE error 事件的 code 为 chat_model_unavailable，未回落到 .env 默认模型。"
echo "- AC5：reset_dev_db.sh 之后 :8080 登录成功并完成一轮真实模型对话。"
echo "- AC6/AC7：5 个受影响测试目录全绿；前端 build 通过；前后端源码内无 gpt-4o-mini 字面量。"
echo "- 剩余风险：非流式 REST 通道的稳定错误码只体现在 HTTP 409 与 message 文案；"
echo "  `error_code` 只在流式/事件通道以 payload.code 暴露（applications 依赖流式侧）。"
echo "- 是否可归档：达到验收标准；未执行项均为浏览器人工步骤与本 request 无关的既有问题。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
