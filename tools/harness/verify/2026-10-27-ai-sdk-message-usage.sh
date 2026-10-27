#!/usr/bin/env bash
# 验证脚本：ai-sdk 逐轮 / 会话用量展示（2026-10-27-ai-sdk-message-usage）
#
# 目标：用真实运行输出证明本轮改动成立
#   1) 后端归一化：缓存明细从 langchain usage 明细进到可相加的整数（含 priority_/flex_ 前缀、
#      OpenAI / DeepSeek 两套回退、已归一化数据的往返不丢）；
#   2) 落库与事件：网关一轮对话后，`message_completed.payload.usage` 与
#      assistant 消息 `message_metadata["usage"]` 都有明细与 provider，计费表仍只记三个 token 数；
#   3) 快照与契约：`build_message_snapshots` 透出 `usage`，`ConversationMessageRead` 可选接收，
#      OpenAPI 里 `MessageUsage` 与 `/api/v1/embed/conversations/{id}/messages` 的用法齐备；
#   4) SDK：解析/求和/口径纯函数、chip 与明细卡、会话累计、历史映射都有断言；
#   5) 打包：`pnpm --filter xxai-agent build` 通过且产物含 chip 文案与类名；
#   6) 回归：受影响后端包测试与 ruff、SDK 类型检查。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
# 脚本只读运行，不修改任何仓库文件。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$ROOT/apps/backend"
SDK="$ROOT/apps/ai-sdk"
PY="$BACKEND/.venv/bin/python"
FAIL=0
UNEXECUTED=1

verify_step() {
  local title="$1"
  shift
  echo "### $title"
  echo '```'
  if "$@" 2>&1 | tail -25; then
    echo "--- PASS: $title"
  else
    echo "--- FAIL: $title"
    FAIL=1
  fi
  echo '```'
  echo
}

echo "## 已执行的命令与结果"
echo

verify_step "后端：用量归一化与 provider 推导单测" \
  bash -c "cd $BACKEND && $PY -m pytest tests/agent_runtime/test_usage.py -q"

verify_step "后端：消息快照透出 usage（含坏数据不炸）" \
  bash -c "cd $BACKEND && $PY -m pytest tests/conversation/test_message_snapshot_usage.py -q"

verify_step "后端：embed 消息快照响应契约（usage 可选）" \
  bash -c "cd $BACKEND && $PY -m pytest tests/embed/test_message_usage_contract.py -q"

verify_step "后端：网关端到端（payload + 元数据 + 计费表分工）" \
  bash -c "cd $BACKEND && $PY -m pytest tests/gateway/test_chat_flow.py -q"

echo "### 后端：OpenAPI 里 MessageUsage 与消息快照路由齐备"
echo '```'
if (cd "$BACKEND" && "$PY" - <<'PY'
import sys

sys.path.insert(0, ".")

from main import app

schema = app.openapi()["components"]["schemas"]
assert "MessageUsage" in schema, "缺少 MessageUsage 组件"
assert "usage" in schema["ConversationMessageRead"]["properties"], "快照响应缺 usage 字段"
path = app.openapi()["paths"]["/api/v1/embed/conversations/{conversation_id}/messages"]
assert "get" in path, "缺少消息快照 GET"
print("PASS  MessageUsage 已注册，ConversationMessageRead.usage 存在，快照路由已注册")
PY
); then
  echo "--- PASS"
else
  echo "--- FAIL"
  FAIL=1
fi
echo '```'
echo

verify_step "后端：受影响包回归" \
  bash -c "cd $BACKEND && $PY -m pytest tests/agent_runtime tests/conversation tests/embed tests/model_usage -q"

verify_step "后端：改动文件 ruff 检查" \
  bash -c "cd $BACKEND && $PY -m ruff check app/modules/agent_runtime/usage.py app/modules/agent_runtime/langchain_adapter.py app/modules/agent_runtime/events.py app/modules/conversation/runtime.py app/modules/conversation/serializers.py app/modules/embed/schemas.py app/modules/gateway/runtime.py tests/agent_runtime/test_usage.py tests/conversation/test_message_snapshot_usage.py tests/embed/test_message_usage_contract.py tests/gateway/test_chat_flow.py"

verify_step "SDK：用量解析与口径纯函数" \
  bash -c "cd $SDK && pnpm exec vitest run src/core/__tests__/usage.test.ts"

verify_step "SDK：chip 文案与明细行" \
  bash -c "cd $SDK && pnpm exec vitest run src/ui/__tests__/usage-view.test.ts"

verify_step "SDK：chip 展开/收起交互（jsdom 真点）" \
  bash -c "cd $SDK && pnpm exec vitest run src/ui/__tests__/usage-chip.component.test.ts"

verify_step "SDK：消息与列表渲染面（用户消息不出 chip、会话累计）" \
  bash -c "cd $SDK && pnpm exec vitest run src/ui/__tests__/usage-surface.ssr.test.ts"

verify_step "SDK：历史映射透传 usage" \
  bash -c "cd $SDK && pnpm exec vitest run src/history/__tests__/map-history.test.ts"

verify_step "SDK：src 全量单测（不含 scripts/ 下的打包门禁用例）" \
  bash -c "cd $SDK && pnpm exec vitest run src"

verify_step "SDK：类型检查" \
  bash -c "cd $SDK && pnpm type-check"

verify_step "SDK：构建" \
  bash -c "cd $SDK && pnpm build"

echo "### SDK：产物含 chip 文案与类名"
echo '```'
if (cd "$SDK" && grep -c "本轮用量" dist/xxai-agent.es.js >/dev/null \
  && grep -q "用量 " dist/xxai-agent.es.js \
  && grep -q "本会话累计" dist/xxai-agent.es.js \
  && grep -q "xxai-usage-chip" dist/style.css \
  && grep -q "xxai-session-usage" dist/style.css); then
  echo "PASS  dist 内命中「本轮用量」「用量 」「本会话累计」与两个类名"
else
  echo "FAIL  dist 产物缺文案或样式类名"
  FAIL=1
fi
echo '```'
echo

verify_step "仓库：空白错误检查" \
  bash -c "cd $ROOT && git diff --check"

echo "## 未执行项与原因"
echo
echo "- 真实模型下的缓存命中数字：需要供应商（DeepSeek / OpenAI）返回 usage 明细的真实调用，本地只覆盖了替身模型与归一化单测。"
echo "- 浏览器里的最终视觉核对（chip 圆角、明细卡宽度、窄窗 375px 换行）：需要人工打开 demo 页面看截图，脚本未跑无头浏览器。"
echo "- 存量消息（本方案上线前产生的 assistant 消息）的兼容表现：本地库没有对应数据，只能靠「缺 usage 不渲染 chip」的单测与契约断言，未做真实历史会话回放。"
echo '- `apps/ai-sdk/scripts/verify-package.test.mjs`：预存在失败（`npm pack --dry-run --json` 的 stdout 被 `prepare` 的 vite 构建日志污染成非 JSON），与本轮改动无关，未作为通过项。'
echo "- 端到端「刷新页面后 chip 仍在」：需要前端 + 后端 + 浏览器联调，脚本只验证了历史映射函数与快照字段两段。"
echo

echo "## 验收结论"
echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "通过：归一化、落库/事件、快照契约、SDK 展示与历史回放映射、构建与回归测试全部成功；未执行为真实供应商数字、浏览器视觉与存量消息回放。"
else
  echo "未通过：脚本内有失败项，见上方输出。"
fi

if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
if [[ "$UNEXECUTED" -ne 0 ]]; then
  exit 3
fi
exit 0
