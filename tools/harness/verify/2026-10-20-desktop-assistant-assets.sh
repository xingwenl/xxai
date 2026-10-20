#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-20-desktop-assistant-assets
#
# 覆盖范围：ai-sdk 上传 MIME 解析与 accept 列表（单测 + 类型检查 + 构建产物）、宿主前端
# 构建与 baseUrl 注入、宿主 `/api/v1/*` 同源转发（pytest），以及一条对真实 AI Base 的
# 端到端探针（xlsx 上传 201 / 会话列表 200 / octet-stream 被拒 / 401 透传）。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
PROBE_DIR="$(mktemp -d)"
trap 'rm -rf "$PROBE_DIR"' EXIT

# 执行一条验证命令并打印结果。
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

# 在指定目录内执行命令（不用子 shell，保证 FAIL 能传出来）。
verify_step_in() {
  local dir="$1"; shift
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "cd ${dir} && $*"
  echo '```'
  echo
  if pushd "$dir" >/dev/null 2>&1; then
    if "$@"; then
      echo "结果：通过"
    else
      echo "结果：失败"
      FAIL=1
    fi
    popd >/dev/null 2>&1
  else
    echo "结果：失败（目录不存在：${dir}）"
    FAIL=1
  fi
  echo
}

# ── 1. ai-sdk：MIME 解析 ───────────────────────────────────────────────────
verify_step_in apps/ai-sdk "ai-sdk 上传 MIME 单测（vitest：扩展名映射 / 类型兜底 / accept 只含 MIME）" \
  ./node_modules/.bin/vitest run src/core/__tests__/upload-mime.test.ts --reporter=dot
# 注意：ai-sdk 的 `pnpm type-check`（vue-tsc 全量）当前在既有文件
# src/core/__tests__/websocket.test.ts:278 报 TS2741（`__promisify__` 缺失，Node 类型版本漂移），
# 与本 request 无关，因此这里只对本 request 新增的 upload-mime.ts 做严格类型检查。
verify_step_in apps/ai-sdk "ai-sdk 新增 upload-mime.ts 严格类型检查（tsc --strict）" \
  ./node_modules/.bin/tsc --noEmit --strict --skipLibCheck --target ES2020 \
  --module ESNext --moduleResolution bundler --lib ES2020,DOM src/core/upload-mime.ts
verify_step_in apps/ai-sdk "重建 ai-sdk dist（宿主前端消费的是 dist 产物，不是源码）" pnpm build

# ── 2. 宿主前端：构建产物断言 ──────────────────────────────────────────────
verify_step_in apps/desktop/front "宿主前端类型检查（tsc --noEmit）" ./node_modules/.bin/tsc --noEmit
verify_step_in apps/desktop/front "宿主前端生产构建（front/dist 由内嵌服务托管）" pnpm build

bundle_probe() {
  local bundle
  bundle="$(ls apps/desktop/front/dist/assets/index-*.js 2>/dev/null | head -1)"
  if [[ -z "$bundle" ]]; then
    echo "未找到构建产物 apps/desktop/front/dist/assets/index-*.js"
    return 1
  fi
  echo "产物：${bundle}"
  local rc=0
  # accept 已改为纯 MIME 列表：应包含图片 + 开放文档 MIME，且不再出现扩展名 token
  if grep -q 'image/webp`,`text/plain`,`text/markdown`,`text/csv`' "$bundle"; then
    echo "✓ accept 为纯 MIME 列表"
  else
    echo "✗ accept 未包含预期 MIME 列表"
    rc=1
  fi
  if grep -q 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' "$bundle"; then
    echo "✓ 产物内含 xlsx MIME（可用于类型兜底与 file 重建）"
  else
    echo "✗ 产物内缺少 xlsx MIME"
    rc=1
  fi
  if grep -q '"\.xlsx", "\.pptx"\|\.xlsx, \.pptx\|,\.xlsx,\.pptx' "$bundle"; then
    echo "✗ 产物仍残留扩展名 accept token"
    rc=1
  else
    echo "✓ 产物内无扩展名 accept token"
  fi
  # 渲染层的 HTTP 调用走宿主同源转发
  if grep -q '/api/v1' "$bundle"; then
    echo "✓ 渲染层已按宿主同源路径（/api/v1）拼 HTTP 根"
  else
    echo "✗ 产物内未找到 /api/v1 同源路径"
    rc=1
  fi
  return "$rc"
}
verify_step "宿主构建产物断言（accept 只含 MIME、含 xlsx MIME、走宿主同源 /api/v1）" bundle_probe

# ── 3. 宿主后端：转发实现与测试 ────────────────────────────────────────────
verify_step_in apps/desktop "桌面宿主后端全量测试（排除他人未提交改动导致的既有失败）" \
  .venv/bin/python -m pytest tests/ -q \
  --deselect tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off
verify_step_in apps/desktop "转发相关文件 lint（ruff）" \
  .venv/bin/ruff check desktop_app tests/test_agent_proxy.py

# ── 4. 真实 AI Base 端到端探针 ─────────────────────────────────────────────
cat >"${PROBE_DIR}/probe_forward.py" <<'PYPROBE'
"""真实链路探针：渲染层同源路径 -> 宿主 /api/v1 转发 -> 真实 AI Base。"""

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import desktop_app.server as server
from desktop_app.agent_config import AgentConfigStore
from desktop_app.manager import PluginManager

config_path = Path.home() / ".desktop-app" / "agent.json"
if not config_path.exists():
    print(f"SKIP: 未找到 {config_path}（未在设置页配置智能体后端）")
    sys.exit(2)
store = AgentConfigStore(config_path)
try:
    config = store.load()
except Exception as exc:  # noqa: BLE001 - 探针只关心能否继续
    print(f"SKIP: 智能体配置不可读：{exc}")
    sys.exit(2)
if config is None:
    print("SKIP: 智能体后端未配置")
    sys.exit(2)
print(f"AI Base：{config.base_url} / agent_id={config.agent_id}")

tmp = Path(tempfile.mkdtemp())
manager = PluginManager(
    builtin_dir=tmp / "builtin", user_dir=tmp / "user", state_file=tmp / "state.json"
)
client = TestClient(server.create_app(manager, agent_config_store=store))

# 与桌面渲染层相同的来源换 token（走宿主 /api/desktop/agent-token）
token_resp = client.post("/api/desktop/agent-token", json={"origin": "http://127.0.0.1:8765"})
if token_resp.status_code != 200:
    print(f"SKIP: 换发 token 失败（AI Base 未启动或凭证失配）：{token_resp.status_code} {token_resp.text[:200]}")
    sys.exit(2)
token = token_resp.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
fake_xlsx = b"PK\x03\x04" + b"\x00" * 64  # 只验证受理与 MIME 判定，不验证解析

upload = client.post(
    "/api/v1/embed/assets",
    files={"file": ("verify.xlsx", fake_xlsx, XLSX_MIME)},
    headers=headers,
)
assert upload.status_code == 201, f"xlsx 上传应 201，实际 {upload.status_code} {upload.text[:200]}"
print("✓ xlsx 上传经宿主转发：201", json.dumps(upload.json(), ensure_ascii=False)[:160])

conversations = client.get(
    "/api/v1/embed/conversations", params={"page": 1, "page_size": 20}, headers=headers
)
assert conversations.status_code == 200, (
    f"会话列表应 200（原跨域失败点），实际 {conversations.status_code} {conversations.text[:200]}"
)
print("✓ 会话列表经宿主转发：200（不再触发 CORS）")

octet = client.post(
    "/api/v1/embed/assets",
    files={"file": ("verify.xlsx", fake_xlsx, "application/octet-stream")},
    headers=headers,
)
assert octet.status_code == 400, f"octet-stream 应被后端拒绝为 400，实际 {octet.status_code}"
assert "不支持的文件类型" in octet.text, octet.text[:200]
print("✓ octet-stream 经宿主转发被后端拒绝：400（说明 MIME 兜底必要，且状态码透传）")

anon = client.get("/api/v1/embed/conversations")
assert anon.status_code == 401, f"无 token 应由上游返回 401，实际 {anon.status_code}"
print("✓ 无 Authorization 时上游 401 透传（转发不绕过鉴权）")

print("RESULT OK")
PYPROBE

forward_probe() {
  HOME="$HOME" PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python "${PROBE_DIR}/probe_forward.py"
}

echo "### 真实 AI Base 转发链路（xlsx 上传 201 / 会话列表 200 / octet-stream 400 / 401 透传）"
echo
echo '```bash'
echo 'HOME=$HOME PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python probe_forward.py'
echo '```'
echo
forward_probe
probe_rc=$?
if [[ $probe_rc -eq 0 ]]; then
  echo "结果：通过"
elif [[ $probe_rc -eq 2 ]]; then
  echo "结果：未执行（本机 AI Base 未配置或未运行）"
  UNEXECUTED=1
else
  echo "结果：失败"
  FAIL=1
fi
echo

echo "## 未执行项与原因"
echo
echo "- 真机文件面板：macOS pywebview 窗口里点「上传文件」后系统面板实际能选中 \`.xlsx\`/\`.pdf\`——脚本只验证了 accept 已改为纯 MIME（且实测这 10 个 MIME 在 \`UTType.typeWithMIMEType_\` 全部映射成功），没有在 pywebview 窗口里手动点选文件。"
echo "- 悬浮窗内的上传交互细节（缩略图、上传进度、失败重试、附件气泡样式）：宿主前端与 ai-sdk 都没有前端测试框架，脚本用类型检查 + 构建 + 真实 HTTP 探针覆盖行为，未做浏览器点击/截图断言。"
echo "- 真实模型读取附件内容：探针只证明「后端受理 xlsx（201）」与「MIME 判定正确」，没有用模型真正解析一个有效 xlsx 并总结（需要有效文件、模型支持与额度）。"
echo "- `apps/ai-sdk` 的全量 `pnpm type-check`（vue-tsc）：既有文件 `src/core/__tests__/websocket.test.ts:278` 报 TS2741（`__promisify__` 缺失），在本 request 改动前就会失败，与本任务无关，未修复；脚本改为只对新增的 `upload-mime.ts` 做 `tsc --strict` 检查。"
echo "- Windows / Linux 的文件面板与 MIME 映射：本机只有 macOS 环境，未在其它平台执行；其它平台不走 \`UTType\`，但 \`file.type\` 为空时的扩展名兜底是平台无关的。"
if [[ $UNEXECUTED -ne 0 ]]; then
  echo "- 真实 AI Base 转发探针：本机未找到可用的 `~/.desktop-app/agent.json` 或后端不可达，已跳过（见上一步「未执行」）。"
fi
echo "- \`tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off\`：仓库内他人未提交改动导致 \`NameError: name 'subprocess' is not defined\`（\`tests/test_host_api.py:210\`），与本 request 无关，已从 pytest 中 deselect，未修复该文件。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 已由脚本证明：ai-sdk 的 \`accept\` 是纯 MIME 列表（产物内不再出现 \`.xlsx\` 这类扩展名 token），扩展名 → MIME 的映射与 \`withResolvedMimeType\` 重建有 10 例单测；宿主前端构建产物里渲染层按 \`\${location.origin}/api/v1\` 拼 HTTP 根（不再由 WS endpoint 推导出跨域的 \`127.0.0.1:8000\`）。"
echo "- 已由脚本证明：宿主 \`/api/v1/{path:path}\` 转发会透传方法、查询串、\`Authorization\`、\`Content-Type\` 与原始 body，并透传上游状态码；未配置后端返回 503、路径穿越返回 400、网络错误 502（6 例 pytest）。"
echo "- 已由真实链路探针证明（若本机配置可用）：同一个 \`POST /api/v1/embed/assets\` 用 xlsx MIME 返回 201、\`GET /api/v1/embed/conversations\` 返回 200，即原报错里「跨域被拦」的两个接口都能正常走通；\`application/octet-stream\` 仍被后端以「不支持的文件类型」拒绝，说明 MIME 兜底不是可选项。"
echo "- 尚未证明：真机文件面板的可用性、悬浮窗上传交互的视觉与手感、模型对附件内容的解析（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。"
echo "- 剩余风险：转发接口把 \`/api/v1/*\` 全量放行到配置的 \`baseUrl\`，安全边界依赖该地址由用户本人配置（设置页）且 token 由渲染层携带；未新增后端 CORS 豁免，也未放开任何鉴权。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
