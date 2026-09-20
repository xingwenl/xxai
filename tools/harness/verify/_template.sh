#!/usr/bin/env bash
# Harness v2 验证脚本模板。
#
# 用法：
#   1. 复制为 tools/harness/verify/<request-id>.sh
#   2. 把下面的 verify_step 调用替换为本 request 的真实验证命令
#   3. chmod +x tools/harness/verify/<request-id>.sh
#   4. 运行 tools/harness/verify.sh <request-id>
#
# 守则：
#   - 只写**真实执行过**的命令，不写"应该通过"。
#   - 必须显式声明未执行项与原因（缺环境、缺权限、需人工联调）。
#   - 退出码即验证结论：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 本脚本保留三个 H2 章节，运行器会原文采用，不再自动补占位。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0

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

echo "## 已执行的命令与结果"
echo

# ↓↓↓ 替换为真实验证命令；下面仅为示例，必须删除或替换 ↓↓↓
verify_step "示例：占位命令" python3 -c "print('replace me')"
# ↑↑↑ 替换为真实验证命令 ↑↑↑

echo "## 未执行项与原因"
echo
# 有未执行项时保留下面一行并置 UNEXECUTED=1；
# 确实全部执行完则改为「- 无未执行项。」并删掉 UNEXECUTED=1。
echo "- <未执行项>：<原因，例如本机无 Docker socket 权限>"
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
