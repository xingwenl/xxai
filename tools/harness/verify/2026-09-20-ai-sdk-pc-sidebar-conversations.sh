#!/usr/bin/env bash
# Harness v2 验证脚本：AI SDK PC 双栏布局 + 左侧会话列表 + 软删除会话。
#
# 覆盖：
#   1. 后端单测（含跨主体越权 404、软删除不销毁消息/用量记录、列表排序）
#   2. 后端 lint
#   3. SDK 类型检查 / 单测 / 构建 / 包产物校验
#   4. 真实浏览器（Chrome CDP）验证双栏布局与切换会话无串台
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

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

echo "## 已执行的命令与结果"
echo

verify_step "后端：embed / conversation / gateway 单测" \
  bash -c "cd apps/backend && poetry run pytest tests/embed tests/conversation tests/gateway -q 2>&1 | tail -20"

verify_step "后端：ruff 检查本次改动的模块" \
  bash -c "cd apps/backend && poetry run ruff check app/modules/embed/schemas.py app/modules/embed/services.py app/modules/embed/router.py app/modules/conversation/repositories.py tests/embed/test_conversation_list.py"

verify_step "SDK：类型检查" \
  bash -c "cd apps/ai-sdk && npm run type-check 2>&1 | tail -10"

verify_step "SDK：单元测试（含会话切换状态重置回归）" \
  bash -c "cd apps/ai-sdk && npm run test -- --run 2>&1 | grep -E 'Test Files|Tests ' | tail -5"

verify_step "SDK：构建 + 包产物校验" \
  bash -c "cd apps/ai-sdk && npm run build >/dev/null 2>&1 && npm run verify-package 2>&1 | tail -3"

# 真实浏览器验证：需要本机 Chrome + 一个静态服务。
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ -x "$CHROME" ]] && python3 -c "import websockets" 2>/dev/null; then
  # 起静态服务供页面加载 dist 产物；退出时清理。
  python3 -m http.server 8791 --directory apps/ai-sdk >/dev/null 2>&1 &
  HTTPD_PID=$!
  trap 'kill "$HTTPD_PID" 2>/dev/null' EXIT
  sleep 1.5
  verify_step "浏览器：PC 双栏布局与会话切换（Chrome CDP）" \
    python3 apps/ai-sdk/scripts/verify-pc-sidebar.py
  kill "$HTTPD_PID" 2>/dev/null
  wait "$HTTPD_PID" 2>/dev/null
  trap - EXIT
else
  echo "### 浏览器：PC 双栏布局与会话切换（Chrome CDP）"
  echo
  echo "结果：未执行（本机缺少 Chrome 或 python websockets）"
  echo
  UNEXECUTED=1
fi

echo "## 未执行项与原因"
echo
echo "- 真实 PostgreSQL 上的会话列表查询计划：本机单测使用 sqlite 内存库，未在 PostgreSQL 上执行 EXPLAIN 验证索引使用；需在部署环境补做。"
echo "- 真实后端联调（端到端：浏览器 → FastAPI → PostgreSQL）：本次浏览器验证用 stub 的 fetch 隔离 UI 行为，未连真实网关与数据库。"
echo "- 软删除会话的磁盘附件清理：本 request 明确不做物理清理（保留附件与用量记录），故无清理项可验证。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 待人工补写：是否达到 spec.md 的验收标准；剩余风险；是否可归档。"
echo "- 脚本退出码将在运行后写入 verify.md 的 frontmatter。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
