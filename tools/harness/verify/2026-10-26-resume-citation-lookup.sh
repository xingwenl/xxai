#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-26-resume-citation-lookup
#
# 覆盖范围：确认-续跑路径补全 citations 时是否只读单条消息（路由层不再全量扫描会话）、
# 新增的 ConversationRepository.get_message 是否按「主键 + 会话归属」取数并拒绝跨会话 ID、
# 续跑响应里的 citations 是否与挂起前落库内容一致，以及 ruff 与 harness 审计。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 守则：只写真实执行过的命令；每一步失败计 FAIL 但继续跑完其余步骤（不 set -e 提前退出），
# 结尾统一收口；无法自动化的项显式写进「未执行项与原因」。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
BACKEND="apps/backend"
ROUTER="$BACKEND/app/modules/conversation/router.py"
REPO="$BACKEND/app/modules/conversation/repositories.py"
TEST_FILE="$BACKEND/tests/conversation/test_run_confirmation_resume.py"

# 执行一条验证命令并打印结果。
# 用法：verify_step "<人类可读名称>" <命令> [参数...]
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

# 断言某文件中某模式的出现次数等于期望值。
# 用法：verify_grep_count "<名称>" "<文件>" "<模式>" <期望次数>
verify_grep_count() {
  local name="$1" file="$2" pattern="$3" expected="$4"
  local actual
  actual="$(grep -c "$pattern" "$file" || true)"
  echo "### ${name}"
  echo
  echo '```bash'
  echo "grep -c '$pattern' $file  # 期望 ${expected}，实际 ${actual}"
  echo '```'
  echo
  if [[ "$actual" == "$expected" ]]; then
    echo "结果：通过"
  else
    echo "结果：失败（期望 ${expected}，实际 ${actual}）"
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

verify_grep_count "路由层不再全量扫描会话消息" "$ROUTER" 'list_messages' 0
verify_grep_count "仓储层新增 get_message" "$REPO" 'async def get_message' 1

verify_step "仓储层 get_message 的归属与单条查询断言" \
  bash -c "cd $BACKEND && .venv/bin/python -m pytest tests/conversation/test_run_confirmation_resume.py -q 2>&1 | tail -20"

verify_step "会话、embed、agent 相关回归测试" \
  bash -c "cd $BACKEND && .venv/bin/python -m pytest tests/conversation tests/embed tests/agent -q 2>&1 | tail -20"

verify_step "改动文件 ruff 检查" \
  bash -c "cd $BACKEND && .venv/bin/python -m ruff check app/modules/conversation/router.py app/modules/conversation/repositories.py tests/conversation/test_run_confirmation_resume.py 2>&1 | tail -10"

verify_step "Harness 审计" \
  python3 tools/harness/audit.py

echo "## 未执行项与原因"
echo
echo "- 真实前后端联调「工具审批挂起 → 确认续跑 → citations 回显」：需要起后端与前端并构造一次会挂起的工具调用，"
echo "  本脚本只做进程内回归，未做人工联调。"
echo "- 浏览器端引用卡片渲染：本次不改返回契约，未做前端回归。"
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
