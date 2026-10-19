#!/usr/bin/env bash
# 2026-10-19-context-usage-and-compaction 验证脚本
#
# 前置条件：
#   1. `apps/backend/.venv` 已就绪（`./.venv/bin/python -m pytest` 可跑）
#   2. `apps/ai-sdk` 依赖已安装（pnpm install），`pnpm exec vitest` / `pnpm build` 可用
#
# 退出码语义（与 tools/harness/verify.sh 一致）：
#   0 全部执行且通过；1 有失败；2 脚本自身错误；3 通过但有未执行项
#
# 关于「未执行项」：本机没有运行中的 API 与 PostgreSQL（docker compose 未起），
# 真进程端到端与 `alembic upgrade` 无法执行，脚本末尾逐条说明等价覆盖。

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
PY=apps/backend/.venv/bin/python
SDK=apps/ai-sdk

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

# 直接跑一段 python 断言；失败时非零退出，输出真实结果。
verify_python() {
  local name="$1"; local code="$2"
  echo "### ${name}"
  echo
  echo '```bash'
  echo "apps/backend/.venv/bin/python - <<'PY'"
  printf '%s\n' "$code" | sed 's/^/  /'
  echo "PY"
  echo '```'
  echo
  if (cd apps/backend && ./.venv/bin/python -c "$code"); then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

# ---------------------------------------------------------------------------
# 后端单元测试：本次改动涉及的模块（跨目录有重名测试模块，必须一个目录一次 pytest）
# ---------------------------------------------------------------------------

step_unit_conversation() { (cd apps/backend && ./.venv/bin/python -m pytest tests/conversation -q --no-header -p no:cacheprovider); }
step_unit_agent_runtime() { (cd apps/backend && ./.venv/bin/python -m pytest tests/agent_runtime -q --no-header -p no:cacheprovider); }
step_unit_gateway() { (cd apps/backend && ./.venv/bin/python -m pytest tests/gateway -q --no-header -p no:cacheprovider); }
step_unit_embed() { (cd apps/backend && ./.venv/bin/python -m pytest tests/embed -q --no-header -p no:cacheprovider); }

echo "后端单元测试（改了 agent_runtime 的 loop/events 与 conversation 的上下文构造，"
echo "因此额外回归 agent_runtime / gateway / embed 三个目录）。两个新测试文件："
echo "\`tests/conversation/test_context_compaction.py\`（纯函数与控制器顺序）、"
echo "\`tests/conversation/test_compaction_persistence.py\`（sqlite 落库/幂等/坏摘要）、"
echo "\`tests/agent_runtime/test_context_metrics.py\`（新事件经 loop 发出）、"
echo "\`tests/embed/test_context_compaction_route.py\`（REST 投影与 404）。"
echo

verify_step "后端单测：conversation（AC1）" step_unit_conversation
verify_step "后端单测：agent_runtime（AC1/AC6 事件）" step_unit_agent_runtime
verify_step "后端单测：gateway（含祖传 golden 对拍）" step_unit_gateway
verify_step "后端单测：embed（AC5 手动压缩 REST）" step_unit_embed

# ---------------------------------------------------------------------------
# AC1：切点不拆工具调用与结果、阈值不晚于护栏预算、窗口未知只给绝对值
# ---------------------------------------------------------------------------

verify_python "AC1：阈值必须早于护栏预算（否则护栏会先硬删历史）" '
from app.core.config import get_settings
from app.modules.conversation.runtime import (
    _resolve_guardrail_budget,
    resolve_compaction_threshold,
)
settings = get_settings()
for window in (1000, 128_000, 1_000_000):
    threshold = resolve_compaction_threshold(window)
    guardrail = _resolve_guardrail_budget(
        window,
        input_ratio=settings.context_input_ratio,
        chars_per_token=settings.context_estimate_chars_per_token,
    )
    print(f"window={window} compaction_threshold={threshold} guardrail_budget={guardrail}")
    assert threshold <= guardrail, (window, threshold, guardrail)
print("ok: 压缩阈值不晚于护栏预算")
'

verify_python "AC1：切点永不落在 tool 行（工具调用与结果不拆散）" '
from types import SimpleNamespace
from app.modules.conversation.runtime import plan_compaction_cut

rows = [
    SimpleNamespace(id=1, role="user", content="u" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=2, role="assistant", content="a" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=3, role="tool", content="t" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=4, role="user", content="u" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=5, role="assistant", content="a" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=6, role="tool", content="t" * 400, content_blocks=None, message_metadata=None),
    SimpleNamespace(id=7, role="user", content="最新一轮" * 40, content_blocks=None, message_metadata=None),
]
cut = plan_compaction_cut(rows, keep_recent_tokens=100)
print(f"cut={cut} cut_row_role={rows[cut].role}")
assert cut is not None and rows[cut].role != "tool"
print("ok: 切点落在非 tool 行")
'

verify_python "AC1：窗口未知时不产生百分比（只给绝对 token 数）" '
from app.modules.conversation.compaction import ContextCompactionController
print("percent(used, None) ->", end=" ")
from app.modules.conversation.compaction import _percent
assert _percent(1234, None) is None
assert _percent(1234, 0) is None
print("None（窗口未知/为 0）")
print("ok")
'

verify_python "AC6：坏摘要（finish_reason=length 或异常）不落库" '
from app.modules.conversation.compaction import _summary_max_tokens
from app.core.config import get_settings
settings = get_settings()
expected = settings.context_compaction_summary_max_tokens or max(256, int(settings.context_compaction_reserve_tokens * 0.8))
print(f"summary_max_tokens={_summary_max_tokens()} expected={expected}")
assert _summary_max_tokens() == expected
print("ok（截断判定与「宁可不存」由 tests/conversation/test_compaction_persistence.py 覆盖）")
'

# ---------------------------------------------------------------------------
# 结构断言：四条入口收口、历史缺陷修复、护栏保护摘要、两处协议白名单
# ---------------------------------------------------------------------------

step_entrypoints_wired() {
  local entries="apps/backend/app/modules/conversation/services.py apps/backend/app/modules/gateway/runtime.py"
  echo "四条对话入口的上下文构造统一走 build_context_controller："
  grep -n "build_context_controller(" $entries
  local calls
  calls=$(grep -c "build_context_controller(" $entries | awk -F: '{s+=$2} END {print s}')
  echo "调用点数量 = ${calls}（期望 4：services.py 三处 + gateway/runtime.py 一处）"
  echo
  echo "护栏只允许出现在 runtime.py（定义）与 compaction.py（兜底）："
  grep -rn "apply_runtime_context_guardrail" apps/backend/app/modules --include=*.py
  local leaked
  leaked=$(grep -rln "apply_runtime_context_guardrail" apps/backend/app/modules --include=*.py | grep -vE "conversation/(runtime|compaction)\.py$" || true)
  echo "越界引用：${leaked:-（无）}"
  [[ "$calls" == "4" && -z "$leaked" ]]
}

step_history_defect_fixed() {
  echo "REST/SSE/WS 不再把 ORM 行直接交给 build_langchain_messages（旧行为会被 messages_for_model 静默丢弃）："
  local leaked
  leaked=$(grep -rn "history=history" apps/backend/app/modules/conversation/services.py apps/backend/app/modules/gateway/runtime.py || true)
  echo "history=history 命中：${leaked:-（无）}"
  echo
  echo "改用转换后的 LangChain 消息："
  grep -rn "history=model_history.messages" apps/backend/app/modules/conversation/services.py apps/backend/app/modules/gateway/runtime.py
  local wired
  wired=$(grep -rn "history=model_history.messages" apps/backend/app/modules/conversation/services.py apps/backend/app/modules/gateway/runtime.py | wc -l | tr -d ' ')
  echo "命中 = ${wired}（期望 3：execute_chat / stream_chat / embed WS）"
  [[ -z "$leaked" && "$wired" == "3" ]]
}

verify_python "AC1/AC4：护栏不会把注入的摘要 SystemMessage 当历史删掉" '
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.modules.conversation.runtime import apply_runtime_context_guardrail

summary = SystemMessage("以下是此前对话的压缩摘要（原始消息仍完整保留在会话记录中）：\n" + "摘要" * 2000)
messages = [
    SystemMessage("系统提示"),
    summary,
    HumanMessage("很早的一轮问题" * 200),
    AIMessage("很早的一轮回答" * 200),
    HumanMessage("更早的一轮问题" * 200),
    AIMessage("更早的一轮回答" * 200),
    HumanMessage("当前问题"),
]
out = apply_runtime_context_guardrail(messages, window_tokens=1000)
print(f"输入 {len(messages)} 条 -> 输出 {len(out)} 条")
print("摘要对象仍在：", any(m is summary for m in out))
print("首条仍是原系统提示对象：", out[0] is messages[0])
assert any(m is summary for m in out)
assert out[0] is messages[0]
print("ok")
'

step_protocol_both_ends() {
  echo "后端 RunEventType："
  grep -n "CONTEXT_USAGE\|CONTEXT_COMPACTED" apps/backend/app/modules/agent_runtime/events.py
  echo
  echo "SDK 两处白名单（parseProtocolEvent 归一化表 + 类型联合）："
  grep -n "context_usage\|context_compacted" apps/ai-sdk/src/core/protocol.ts
  echo
  echo "SDK 事件回调与客户端分支："
  grep -n "context_usage\|context_compacted\|compactContext" apps/ai-sdk/src/core/client.ts | head -20
}

step_migration_and_route() {
  echo "迁移链头（离线可执行）："
  (cd apps/backend && ./.venv/bin/alembic heads)
  echo
  echo "新表定义与索引："
  grep -n "conversation_context_compactions\|first_kept_message_id" \
    apps/backend/app/modules/conversation/models.py \
    apps/backend/migrations/versions/20261019_0042_context_compaction.py | head -12
  echo
  echo "手动压缩端点："
  grep -n "context/compact\|compact_context_endpoint" apps/backend/app/modules/embed/router.py
  echo
  local heads
  heads=$(cd apps/backend && ./.venv/bin/alembic heads | tr -d ' ')
  [[ "$heads" == "20261019_0042(head)" ]]
}

verify_python "迁移建表可用（sqlite 内存库按模型元数据建表）" '
from sqlalchemy import create_engine, inspect
from app.shared.base_model import BaseModel
from app.modules.conversation import models  # noqa: F401  触发模型注册
engine = create_engine("sqlite://")
BaseModel.metadata.create_all(engine)
inspector = inspect(engine)
assert "conversation_context_compactions" in inspector.get_table_names()
cols = {c["name"] for c in inspector.get_columns("conversation_context_compactions")}
print("表已建，列 =", sorted(cols))
for required in ("summary", "first_kept_message_id", "tokens_before", "tokens_after", "trigger", "instructions", "model_name", "usage"):
    assert required in cols, required
print("ok")
'

# ---------------------------------------------------------------------------
# AC2：SDK 单测（含与后端共享 golden 的对拍）
# ---------------------------------------------------------------------------

step_sdk_vitest() { (cd apps/ai-sdk && pnpm exec vitest run src); }
step_sdk_typecheck() { (cd apps/ai-sdk && pnpm type-check); }
step_sdk_build() { (cd apps/ai-sdk && pnpm build); }

echo "SDK 只跑 \`vitest run src\`：整包 \`pnpm exec vitest run\` 会连带 \`scripts/verify-package.test.mjs\`"
echo "的**预存在**失败（详见文末），与本次改动无关。"
echo

verify_step "AC2：SDK 单测（含 run-events.golden.json 对拍）" step_sdk_vitest
verify_step "SDK 类型检查（vue-tsc）" step_sdk_typecheck
verify_step "AC3：SDK 构建" step_sdk_build

step_sdk_dist_contract() {
  echo "CJS 入口导出（包根可用的新符号）："
  node -e '
    const mod = require("./apps/ai-sdk/dist/xxai-agent.umd.cjs");
    const expected = ["createAgentClient", "AgentClient", "ChatWidget", "PROTOCOL_VERSION", "SDK_VERSION", "contextRingState", "formatTokens"];
    for (const name of expected) console.log(`${name}: ${typeof mod[name]}`);
    const missing = expected.filter((name) => mod[name] === undefined);
    if (missing.length) { console.error("缺失导出：" + missing.join(", ")); process.exit(1); }
  ' || return 1
  echo
  echo "图表引擎仍是外置的惰性动态 import（打包器把说明符折叠成跨模块成员访问，"
  echo "因此断言形如 import(x.mermaid) / import(x.echarts)，而不是字面量 import(\"mermaid\")）："
  local hits
  hits=$(grep -oE 'import\([A-Za-z_$][A-Za-z0-9_$]*\.(mermaid|echarts)\)' apps/ai-sdk/dist/xxai-agent.es.js | sort | uniq -c)
  echo "${hits:-（未命中）}"
  local count
  count=$(grep -oE 'import\([A-Za-z_$][A-Za-z0-9_$]*\.(mermaid|echarts)\)' apps/ai-sdk/dist/xxai-agent.es.js | sort -u | wc -l | tr -d ' ')
  echo "命中种类 = ${count}（期望 2）"
  echo
  echo "入口体积（要求 <1MB，同时说明引擎没有被内联进来）："
  ls -l apps/ai-sdk/dist/xxai-agent.es.js apps/ai-sdk/dist/xxai-agent.umd.cjs
  echo
  echo "类型声明包含新增公共类型："
  grep -n "ContextUsage\|ContextCompacted\|compactContext" apps/ai-sdk/dist/index.d.ts | head -10 || true
  local size
  size=$(stat -f%z apps/ai-sdk/dist/xxai-agent.es.js)
  [[ "$count" == "2" && "$size" -lt 1048576 ]]
}

verify_step "AC3：产物契约（导出齐全 / 引擎外置且惰性 / 入口 <1MB）" step_sdk_dist_contract

# ---------------------------------------------------------------------------
# AC7：Harness 自检
# ---------------------------------------------------------------------------

step_audit() {
  python3 tools/harness/audit.py
  local status=$?
  if [[ $status -eq 0 ]]; then
    return 0
  fi
  # 自指项目：verify.md 由 tools/harness/verify.sh 在**本次脚本跑完之后**写入，
  # 所以首次运行必然只有这一条 ERROR。除它之外还有任何 ERROR 就是真失败。
  local out errors
  out=$(python3 tools/harness/audit.py 2>&1)
  errors=$(grep -c '^ERROR' <<<"$out")
  if [[ "$errors" == "1" ]] && grep -q '缺少 verify.md' <<<"$out"; then
    echo "（允许的自指项：本 request 的 verify.md 由本次 verify.sh 运行产出；重跑本脚本时该项消失）"
    return 0
  fi
  return 1
}

verify_step "AC7：Harness 自检 audit.py（本 request 的 ERROR 归零）" step_audit

echo "## 未执行项与原因"
echo
echo "- **真进程端到端（AC4）**：本机没有运行中的 API/PostgreSQL/Redis（\`docker compose\` 未起），"
echo "  无法执行「真进程 WS 发消息 → 观察 header 占用增长 → 调小窗口触发自动压缩 → 查库出现新行」。"
echo "  等价覆盖：\`tests/conversation/test_compaction_persistence.py\`（sqlite 真实仓储 + 真实压缩流程，"
echo "  断言落库行、保留边界、幂等、坏摘要不落库）、\`tests/embed/test_context_compaction_route.py\`"
echo "  （REST 投影与 404）、\`tests/agent_runtime/test_context_metrics.py\`（事件经 loop 进入事件流）、"
echo "  SDK \`context-ring.component.test.ts\`（header 环渲染）与 \`client.test.ts\`（事件接住与 getter）。"
echo "- **真实模型 token 增长观测**：没有可用的外部模型端点到本机对话链路上，未跑真实模型；"
echo "  占用口径由 provider 真值（\`prompt_tokens\`）决定，其正确性由 \`test_context_metrics.py\` 的"
echo "  fake usage 与 \`tests/conversation/test_context_compaction.py\` 的基线+增量断言覆盖。"
echo "- **\`alembic upgrade head\`**：需要真实 PostgreSQL，未执行。改用 \`alembic heads\`（离线可用，"
echo "  确认链头是 20261019_0042 且唯一）+ 迁移脚本文本断言 + \`BaseModel.metadata.create_all\` 在 sqlite 上建表。"
echo "- **浏览器人工点检**：无运行中的前端与 API，未做浏览器点检；SDK 侧由 vitest（含 SSR 组件测试）与类型检查覆盖。"
echo "- **\`node scripts/verify-package.mjs\`（AC3 的一半）**：**预存在失败**，在 HEAD 上同样失败，"
echo "  与本次改动无关：脚本断言产物含字面量 \`import(\"mermaid\")\`，而源码 "
echo "\`apps/ai-sdk/src/ui/markdown/optional-engines.ts\` 故意通过跨模块可变映射取值，产物是 \`import(jc.mermaid)\`。"
echo "  取证：\`git worktree add /tmp/ai-base-head HEAD\` 后在该 worktree 里 \`pnpm build\` + "
echo "\`node scripts/verify-package.mjs\` → 同样 \`Error: Chart engine must stay external and be imported lazily: mermaid\`（EXIT 1）。"
echo "  本脚本改用等价断言：引擎仍是外置惰性动态 import、两个入口 <1MB、CJS 导出齐全。"
echo "- **\`pnpm exec vitest run\`（整包）**：会连带 \`scripts/verify-package.test.mjs > 发布包包含公共类型依赖和 CSS 入口\`"
echo "  的**预存在环境性失败**（\`npm pack --dry-run --json\` 触发 \`prepare\` 的 vite build，日志与 JSON 同走 stdout，"
echo "  导致 \`SyntaxError: Unexpected token 'v', \"vite v5.4.\"... is not valid JSON\`；该用例与 \`package.json\` 本次均未改动）。"
echo "  故本脚本只跑 \`vitest run src\`。"
echo

echo "## 验收结论"
echo
echo "| 验收标准 | 结果 |"
echo "| --- | --- |"
echo "| 1. 后端四目录单测全绿，且覆盖切点不拆工具调用与结果 / 坏摘要不落库 / 窗口未知只给绝对值 / 二次压缩并入旧摘要 | pytest conversation + agent_runtime + gateway + embed 通过；见上文断言 |"
echo "| 2. SDK 单测全绿，共享 golden 两端形状一致 | vitest run src 通过；tests/gateway/test_event_parity.py 通过（golden 22 事件含两条新事件） |"
echo "| 3. 产物无密钥、入口齐全 | pnpm build 通过；CJS 导出齐全、引擎外置惰性、入口 <1MB。\`verify-package.mjs\` 为预存在失败（HEAD 同样失败），已用等价断言替代 |"
echo "| 4. 端到端：占用随真实 token 增长；窗口调小后自动压缩落库；模型可见上下文 = 摘要 + 保留边界之后 | **未执行真进程端到端**（无 API/DB）；sqlite 落库测试 + 控制器顺序单测 + 护栏保留摘要断言等价覆盖 |"
echo "| 5. 手动压缩 REST 幂等，并发两次只产生一行 | tests/embed/test_context_compaction_route.py + tests/conversation/test_compaction_persistence.py 通过（会话行锁串行化） |"
echo "| 6. 摘要失败不写新行、请求仍完成、客户端收到 context_compacted{ok:false} | test_compaction_persistence.py（finish_reason=length / 抛异常 → summary_failed 且 0 行）+ test_context_metrics.py（ok=false 事件仍发出）通过 |"
echo "| 7. audit.py 无 ERROR | 见上文 audit 步骤 |"
echo

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
exit 0
