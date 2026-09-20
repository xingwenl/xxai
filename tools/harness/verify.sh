#!/usr/bin/env bash
# Harness v2 验证脚本运行器。
#
# 执行 tools/harness/verify/<request-id>.sh，把真实输出写入
# docs/harness/requests/<request-id>/verify.md，并保留脚本退出码。
#
# 约定：
#   - 验证脚本向 stdout 输出真实证据（命令与结果）。
#   - 脚本若已自行输出下面三个 H2 章节，则原文采用：
#       ## 已执行的命令与结果 / ## 未执行项与原因 / ## 验收结论
#   - 脚本若只输出裸证据，则由本脚本补齐后两个章节为待填占位。
#
# 用法：
#   tools/harness/verify.sh <request-id>
#   tools/harness/verify.sh <request-id> --print    # 只打印，不写文件

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQUEST_ID="${1:-}"
PRINT_ONLY="${2:-}"

if [[ -z "$REQUEST_ID" ]]; then
  echo "用法：tools/harness/verify.sh <request-id> [--print]" >&2
  exit 2
fi

SCRIPT="$ROOT/tools/harness/verify/${REQUEST_ID}.sh"
REQ_DIR="$ROOT/docs/harness/requests/${REQUEST_ID}"
OUT_FILE="$REQ_DIR/verify.md"

if [[ ! -f "$SCRIPT" ]]; then
  echo "未找到验证脚本：tools/harness/verify/${REQUEST_ID}.sh" >&2
  exit 2
fi

if [[ ! -d "$REQ_DIR" ]]; then
  echo "未找到 request 目录：docs/harness/requests/${REQUEST_ID}/" >&2
  exit 2
fi

if [[ ! -x "$SCRIPT" ]]; then
  echo "验证脚本不可执行：chmod +x tools/harness/verify/${REQUEST_ID}.sh" >&2
  exit 2
fi

TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_OUT"' EXIT

echo "▶ 执行 tools/harness/verify/${REQUEST_ID}.sh"
set +e
bash "$SCRIPT" >"$TMP_OUT" 2>&1
SCRIPT_STATUS=$?
set -e

RAW="$(cat "$TMP_OUT")"
NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"

render() {
  echo "---"
  echo "source: script"
  echo "request: ${REQUEST_ID}"
  echo "ranAt: \"${NOW}\""
  echo "exitCode: ${SCRIPT_STATUS}"
  echo "---"
  echo

  if grep -q '^## 已执行的命令与结果' <<<"$RAW"; then
    # 脚本自带章节结构，原文采用。
    printf '%s\n' "$RAW"
  else
    echo "## 已执行的命令与结果"
    echo
    echo '```text'
    printf '%s\n' "$RAW"
    echo '```'
    echo
    echo "## 未执行项与原因"
    echo
    echo "- 脚本未声明未执行项。若确有无法在本机执行的项目，请在验证脚本中补上「## 未执行项与原因」章节。"
    echo
    echo "## 验收结论"
    echo
    echo "- 待人工补写：是否达到 spec.md 的验收标准；剩余风险；是否可归档。"
    echo "- 脚本退出码：${SCRIPT_STATUS}"
  fi
}

if [[ "$PRINT_ONLY" == "--print" ]]; then
  render
else
  render >"$OUT_FILE"
  echo "✔ 已写入 docs/harness/requests/${REQUEST_ID}/verify.md"
fi

echo "退出码：${SCRIPT_STATUS}"
exit "$SCRIPT_STATUS"
