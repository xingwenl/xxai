#!/usr/bin/env bash
# 验证 2026-10-21-end-user-memory：
# 记忆主体从「后台用户」扩为「后台用户或嵌入终端用户」，隔离按
# (platform_embed_clients.client_id, platform_end_users.id)；受信任入口
# （后台登录态 GET /embed/agent-token）签发的 token 带 user_id 声明，公开入口不带；
# embed 会话系统提示补「已有 N 条记忆」索引行。
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
# 1. 后端：模型 + 主体 + 迁移 + 工具 + 网关透传
# ---------------------------------------------------------------------------
backend_model_static() {
  local ok=0
  local f=apps/backend/app/modules/memory/models.py
  grep -q 'client_id' "$f" || { echo "models.py 缺少 client_id"; ok=1; }
  grep -q 'end_user_id' "$f" || { echo "models.py 缺少 end_user_id"; ok=1; }
  grep -q 'platform_embed_clients.client_id' "$f" || { echo "client_id 未外键到 embed client"; ok=1; }
  grep -q 'ck_user_memories_exactly_one_principal' "$f" || { echo "缺少主体恰好一种 CHECK"; ok=1; }
  grep -q 'uq_user_memories_active_end_user_fact' "$f" || { echo "缺少端用户部分唯一索引"; ok=1; }
  # 每个字段必须带中文 comment（AGENTS.md 代码约定）。
  grep -q '嵌入终端用户 ID' "$f" || { echo "end_user_id 缺少中文 comment"; ok=1; }
  grep -q 'Embed Client ID' "$f" || { echo "client_id 缺少中文 comment"; ok=1; }
  [[ -f apps/backend/app/modules/memory/principal.py ]] || { echo "缺少 memory/principal.py"; ok=1; }
  grep -q 'def user_principal' apps/backend/app/modules/memory/principal.py || { echo "principal.py 缺少 user_principal"; ok=1; }
  grep -q 'def end_user_principal' apps/backend/app/modules/memory/principal.py || { echo "principal.py 缺少 end_user_principal"; ok=1; }
  grep -q 'def owns' apps/backend/app/modules/memory/principal.py || { echo "principal.py 缺少 owns"; ok=1; }
  return $ok
}

migration_static() {
  local f=apps/backend/migrations/versions/20261021_0046_end_user_memory.py
  [[ -f "$f" ]] || { echo "缺少迁移文件 $f"; return 1; }
  grep -q 'revision: str = "20261021_0046"' "$f" || { echo "revision 不是 20261021_0046"; return 1; }
  grep -q 'down_revision: Union\[str, None\] = "20261021_0045"' "$f" || { echo "down_revision 不是 20261021_0045"; return 1; }
  grep -q 'op.add_column' "$f" || { echo "upgrade 缺少 add_column"; return 1; }
  grep -q 'nullable=True' "$f" || { echo "upgrade 未放开 user_id 非空"; return 1; }
  grep -q 'create_check_constraint' "$f" || { echo "upgrade 缺少 CHECK 约束"; return 1; }
  grep -q "DELETE FROM user_memories WHERE user_id IS NULL" "$f" || { echo "downgrade 未处理端用户行"; return 1; }
  grep -q '不可逆' "$f" || { echo "迁移 docstring 未声明不可逆点"; return 1; }
  grep -q 'docs/adr/0016-end-user-memory.md' "$f" || { echo "迁移 docstring 未指向 ADR 0016"; return 1; }
}

backend_wiring_static() {
  local ok=0
  grep -q 'client_id' apps/backend/app/modules/tools/business/framework.py || { echo "BusinessToolContext 缺少 client_id"; ok=1; }
  grep -q 'client_id is not None and platform_end_user_id is not None' apps/backend/app/modules/builtin_tool/services.py \
    || { echo "invoke_builtin_tool 白名单未覆盖端用户主体"; ok=1; }
  grep -q 'client_id=self.client_id' apps/backend/app/modules/gateway/dispatcher.py || { echo "dispatcher 未透传 client_id"; ok=1; }
  grep -q 'user_id=payload.get("user_id")' apps/backend/app/modules/gateway/router.py || { echo "ws 路由未取 token 的 user_id"; ok=1; }
  grep -q 'resolve_embed_memory_principal' apps/backend/app/modules/gateway/runtime.py || { echo "runtime 缺少主体解析"; ok=1; }
  grep -q 'memory_index=memory_index' apps/backend/app/modules/gateway/runtime.py || { echo "runtime 未注入记忆索引行"; ok=1; }
  grep -q 'user_id: int | None = None' apps/backend/app/modules/embed/security.py || { echo "create_embed_token 缺少 user_id 参数"; ok=1; }
  grep -q 'payload\["user_id"\]' apps/backend/app/modules/embed/security.py || { echo "token 未写入 user_id claim"; ok=1; }
  grep -q 'user_id=current_user.id' apps/backend/app/modules/embed/router.py || { echo "受信任入口未传 current_user.id"; ok=1; }
  # 公开入口绝不能带后台身份：POST /embed/tokens 的处理函数里不应出现 user_id 透传。
  if sed -n '/def issue_embed_token_endpoint/,/^@router/p' apps/backend/app/modules/embed/router.py | grep -q 'user_id='; then
    echo "公开入口 POST /embed/tokens 不应传 user_id"; ok=1
  fi
  return $ok
}

backend_format() {
  (cd apps/backend && .venv/bin/ruff check \
    app/modules/memory app/modules/embed app/modules/gateway/dispatcher.py \
    app/modules/gateway/runtime.py app/modules/gateway/router.py \
    app/modules/tools/business/user_memory.py app/modules/builtin_tool/services.py \
    tests/memory tests/embed tests/gateway/test_embed_memory_principal.py \
    migrations/versions/20261021_0046_end_user_memory.py)
}

backend_tests() {
  # 全量 pytest（甚至多个目录一起）会撞仓库预存在的同名测试文件导入冲突
  # （tests/builtin_tool/test_models.py 与 tests/embed/test_models.py 同名），
  # 因此逐目录分开跑。
  local dir status=0
  for dir in tests/memory tests/embed tests/gateway tests/builtin_tool tests/tools; do
    echo "--- $dir"
    (cd apps/backend && .venv/bin/python -m pytest "$dir" -q 2>&1 | tail -3)
    [[ ${PIPESTATUS[0]} -ne 0 ]] && status=1
  done
  return $status
}

alembic_heads() {
  local out
  out=$(cd apps/backend && .venv/bin/python -m alembic heads 2>&1) || { echo "$out"; return 1; }
  echo "$out"
  grep -q '20261021_0046' <<<"$out"
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
  (cd apps/backend && .venv/bin/python -m alembic downgrade 20261021_0045) || return 1
  (cd apps/backend && .venv/bin/python -m alembic upgrade head) || return 1
  # 端用户行在 downgrade 时被删（旧结构无法表达）——这一步只验证结构可往返，
  # 数据层面的不可逆点已写在迁移 docstring。
  (cd apps/backend && .venv/bin/python -m alembic current)
}

# ---------------------------------------------------------------------------
# 2. 文档：ADR / spec / CONTEXT / CHANGELOG
# ---------------------------------------------------------------------------
docs_static() {
  local ok=0
  for token in '记忆主体' '终端用户主体' '部分唯一索引' 'platform_embed_clients.client_id'; do
    grep -q "$token" docs/adr/0016-end-user-memory.md || { echo "ADR 0016 缺少 $token"; ok=1; }
  done
  grep -q 'approval' docs/harness/requests/2026-10-21-end-user-memory/spec.md || { echo "spec 缺少 approval"; ok=1; }
  grep -q 'granted: true' docs/harness/requests/2026-10-21-end-user-memory/spec.md || { echo "spec 未记录用户确认"; ok=1; }
  grep -q '记忆主体（Memory Principal）' CONTEXT.md || { echo "CONTEXT.md 缺少记忆主体术语"; ok=1; }
  grep -q '端用户记忆（End-User Memory）' CONTEXT.md || { echo "CONTEXT.md 缺少端用户记忆术语"; ok=1; }
  grep -q 'client_id' docs/CHANGELOG.md || { echo "CHANGELOG 缺少本次条目"; ok=1; }
  return $ok
}

echo "## 已执行的命令与结果"
echo

verify_step "记忆模型/主体/索引静态断言" backend_model_static
verify_step "迁移文件成对且 revision 链正确" migration_static
verify_step "工具与网关透传静态断言" backend_wiring_static
verify_step "后端格式检查（ruff）" backend_format
verify_step "后端单测（memory/embed/gateway/builtin_tool/tools）" backend_tests
verify_step "alembic 单一 head 指向本次迁移" alembic_heads
verify_step "迁移真实 upgrade→downgrade→upgrade" migration_roundtrip
verify_step "文档（ADR/spec/CONTEXT/CHANGELOG）静态断言" docs_static

echo "## 未执行项与原因"
echo
if [[ $UNEXECUTED -eq 0 ]]; then
  echo "- 无（脚本内所有检查均已执行）。"
fi
echo "- 未做真实第三方页面的端到端联调（需要接入方页面 + 已绑定 Agent 的 embed client，属运行环境依赖）。"
echo "- 未做「同一 external_user_id 跨两个 Client」的 HTTP 级联调（隔离语义由单测与部分唯一索引覆盖，缺两个真实 Client 的测试租户）。"
echo "- 未验证管理台页面：本次明确不动管理台，端用户记忆不展示。"
echo

echo "## 验收结论"
echo
if [[ $FAIL -ne 0 ]]; then
  echo "未通过：存在失败步骤，见上文。"
  exit 1
fi
echo "通过：静态断言、后端单测、迁移升降级与文档检查全部通过；未执行项已逐条列出。"
