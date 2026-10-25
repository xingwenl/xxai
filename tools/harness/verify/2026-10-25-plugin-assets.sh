#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-25-plugin-assets
#
# 覆盖范围：宿主新增「子应用资产」能力（存储 + REST + SDK），以及念记用它做「粘贴/拖拽图片」。
#   · 后端：存储层与 REST 语义（去重、魔数、配额、缓存头、读写权限差异）跑单测
#   · 前端：宿主 SDK 的 assets 命名空间与念记的图片链路都要能类型检查 + 构建
#   · 产物：dist 里确实是声明了 assets 权限的插件，且图片资产端点/提示语进了 bundle
#   · 端到端：用临时 HOME 起真实宿主服务（create_app + uvicorn），无头 Chrome 走
#     #/app/note 深链进真实 iframe（SDK 由宿主注入），在正文里派发 paste/drop 后断言
#     资产真的落盘、正文写入站内路径、预览态 <img> 真的加载成功。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 守则：只写真实执行过的命令；每一步失败计 FAIL 但继续跑完其余步骤（不 set -e 提前退出），
# 结尾统一收口；无法自动化的项显式写进「未执行项与原因」。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
LAST_STATUS=0
BROWSER_PROBE_SKIPPED=0
PROBE_DIR="$(mktemp -d)"
export PROBE_DIR
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
    LAST_STATUS=0
  else
    LAST_STATUS=$?
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
      LAST_STATUS=0
    else
      LAST_STATUS=$?
      echo "结果：失败"
      FAIL=1
    fi
    popd >/dev/null 2>&1
  else
    echo "结果：失败（目录不存在：${dir}）"
    LAST_STATUS=1
    FAIL=1
  fi
  echo
}

# 执行一个外部探针脚本，并把探针源码全文打进证据块（verify.md 里能看到真正跑了什么）。
# 约定：退出码 0 通过 / 3 未执行（需要人工或环境缺失，计入 UNEXECUTED）/ 其它为失败。
verify_step_probe() {
  local name="$1"; shift
  local script="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  sed 's/^/  /' "$script"
  echo "  # 执行：$* ${script}"
  echo '```'
  echo
  "$@" "$script"
  LAST_STATUS=$?
  case $LAST_STATUS in
    0) echo "结果：通过" ;;
    3) echo "结果：未执行（原因见上方输出）"; UNEXECUTED=$((UNEXECUTED + 1)) ;;
    *)
      echo "结果：失败"
      FAIL=1
      ;;
  esac
  echo
}

echo "## 已执行的命令与结果"
echo

# 1. 后端：存储层与 REST 语义是这次改动的核心，单测覆盖去重/魔数/配额/缓存头/读写权限差异。
#    只点名本任务相关的三个文件：test_host_api.py 等他人未提交改动不在本脚本范围内。
verify_step_in "apps/desktop" \
  "宿主后端单测（资产存储 + plugin-data 回归 + 服务端回归）" \
  .venv/bin/python -m pytest tests/test_plugin_assets.py tests/test_plugin_data.py tests/test_server.py -q

# 2. 后端风格检查：新模块与改动文件必须过 ruff（仓库 CI 同规则）。
verify_step_in "apps/desktop" \
  "后端风格检查（ruff check 改动文件）" \
  .venv/bin/python -m ruff check desktop_app/plugin_assets.py desktop_app/server.py desktop_app/paths.py desktop_app/protocol.py

# 3. 宿主前端类型检查：SDK 的 assets 命名空间与 api.ts 的新导出必须自洽。
verify_step_in "apps/desktop/front" \
  "宿主前端类型检查（tsc --noEmit）" \
  pnpm exec tsc --noEmit

# 4. 宿主前端构建：端到端探针需要真实的宿主 UI 产物（iframe 注入 SDK 的逻辑在里面）。
verify_step_in "apps/desktop/front" \
  "宿主前端构建（产物给端到端探针用）" \
  pnpm build

# 5. 念记构建：tsc --noEmit + vite build，产物要能被宿主当插件托管。
verify_step_in "apps/note" \
  "念记构建（tsc --noEmit + vite build）" \
  pnpm build

# 6. 产物与契约断言：接线细节（权限、端点、提示语、方法说明）必须真的出现在构建产物里。
cat > "${PROBE_DIR}/dist_probe.sh" <<'SH'
#!/usr/bin/env bash
# 断言念记产物声明了 assets 权限、图片链路真的进了 bundle，且对外文档与契约同步。
set -euo pipefail

DIST="apps/note/dist"

for artifact in index.html manifest.json icon.svg; do
  if [[ ! -f "$DIST/$artifact" ]]; then
    echo "缺少产物：${DIST}/${artifact}（构建是否成功？）" >&2
    exit 1
  fi
done
if ! ls "$DIST"/assets/*.js >/dev/null 2>&1; then
  echo "缺少产物：${DIST}/assets/*.js（vite 没产出 JS bundle？）" >&2
  exit 1
fi

# manifest 必须声明 assets，否则宿主不会注入 sdk.assets（粘贴图片会静默降级）。
if ! python3 - "$DIST/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
perms = manifest.get("permissions") or []
missing = [p for p in ("storage", "tools", "assets") if p not in perms]
if missing:
    print(f"manifest.permissions 缺少：{missing}（当前 {perms}）", file=sys.stderr)
    sys.exit(1)
if manifest.get("id") != "note":
    print(f"manifest.id 应为 note，实际 {manifest.get('id')!r}", file=sys.stderr)
    sys.exit(1)
PY
then
  echo "manifest 校验失败" >&2
  exit 1
fi

# bundle 里必须出现：资产端点前缀（正文引用与 <img> 都靠它）、拖拽浮层文案、上传失败的中文提示。
JS="$(ls "$DIST"/assets/*.js | head -n 1)"
for needle in \
  "/api/desktop/plugin-assets/note/" \
  "松开即可插入图片" \
  "图片" \
  "image/webp"
do
  if ! grep -qF "$needle" "$JS"; then
    echo "bundle 里找不到：${needle}（图片链路没被打进产物？）" >&2
    exit 1
  fi
done

# 契约与文档同步：tools.json 的读写方法说明里要讲清「图片是本地资产路径，模型读不到像素」。
if ! grep -q "plugin-assets" apps/note/tools.json; then
  echo "apps/note/tools.json 的方法说明没提资产路径，AI 侧不知道图片长什么样" >&2
  exit 1
fi
if ! grep -q "plugin-assets" apps/note/README.md; then
  echo "apps/note/README.md 没有图片/资产说明" >&2
  exit 1
fi
if ! grep -q "assets" apps/desktop/README.md; then
  echo "apps/desktop/README.md 没有 assets 权限或 SDK 说明" >&2
  exit 1
fi

echo "manifest/assets/bundle/文档 断言全部命中"
SH
chmod +x "${PROBE_DIR}/dist_probe.sh"
verify_step_probe "产物与契约断言（manifest 权限、bundle 里的资产端点与提示语、tools.json 与两份 README）" \
  "${PROBE_DIR}/dist_probe.sh" bash

# 7. 端到端：真实宿主服务 + 真实 iframe + 真实 SDK，粘贴与拖拽各插一张图。
#    探针自己起 uvicorn 与无头 Chrome，缺 Chrome / 缺构建产物时退出码 3（计入未执行项）。
verify_step_probe "端到端（临时 HOME 起真实宿主，无头 Chrome 进 #/app/note，粘贴/拖拽图片 → 资产落盘 → 预览渲染）" \
  "tools/harness/verify/2026-10-25-plugin-assets.browser.mjs" node

echo "## 未执行项与原因"
echo
echo "- 真实桌面应用（PyInstaller 打包的 WW.app）里的同一条链路：探针跑的是 create_app + uvicorn 起的同一份服务，"
echo "  但 pywebview 外壳、系统剪贴板（从截图工具直接粘贴）与打包资源路径没有覆盖，需要在 0.2.5 主包里人工点一遍。"
echo "- 从系统剪贴板粘贴真实截图（含 macOS 截图 .png 与微信/飞书复制的图片）：探针用页内 canvas 造图，"
echo "  没有走系统剪贴板，需要人工验证。"
echo "- 配额触顶（单插件 64 MiB / 500 个文件）时的界面提示：后端有单测，但前端提示文案需人工造量验证。"
echo "- 动图 GIF 原样直传后的动画是否守恒：需要人工用动图验证。"
echo "- 真实模型调用（note_* 工具在全局助手里读写含图片的笔记）：需要后台 Embed Client + Agent + HostToolPolicy 绑定。"
if [[ "${BROWSER_PROBE_SKIPPED}" -eq 1 ]]; then
  echo "- 第 7 步端到端探针因本机缺少 Chrome 或构建产物被跳过（原因见上）。"
fi
echo
echo "## 验收结论"
echo
if [[ "$FAIL" -ne 0 ]]; then
  echo "存在失败项，不能视为完成。"
elif [[ "$UNEXECUTED" -ne 0 ]]; then
  echo "自动化项全部通过；另有 ${UNEXECUTED} 项未执行，需按上面清单人工补齐后才能在 spec 的验收标准上打勾。"
else
  echo "全部通过。"
fi
echo
if [[ "$FAIL" -ne 0 ]]; then
  exit 1
elif [[ "$UNEXECUTED" -ne 0 ]]; then
  exit 3
fi
exit 0
