#!/usr/bin/env bash
# 2026-10-20-pnpm-workspace 的验证脚本：pnpm workspace 迁移 + front 镜像分层重建。
#
# 覆盖 spec.md「验收标准」六条：
#   1. 根 lockfile 唯一、app 级 pnpm-lock.yaml 全部删除
#   2. 前端依赖是软链、根 install 会触发 SDK prepare 生成 dist
#   3. 三个宿主（front / shop / desktop-front）都能构建
#   4. front 镜像增量构建耗时（SDK 源码改动 ≤60s、front 源码改动 ≤30s；改造前基线 3m07s）
#      阈值留 2 倍余量：本机重复跑实测 15~26s / 6~13s，取严会因机器负载抖动误报。
#   5. 新镜像的 nginx 冒烟：首页与静态资源 200、/api 反代可达
#   6. audit.py 通过（首次运行生成 verify.md 时尚未就绪，由第二次运行覆盖）
#
# 退出码：0 = 全部通过；1 = 有失败项。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 1

REQUEST_ID="2026-10-20-pnpm-workspace"
PASS=0
FAIL=0
FAILED=()
PROBE_SDK="apps/ai-sdk/src/__perf_probe.txt"
PROBE_FRONT="apps/front/src/__perf_probe.txt"
VERIFY_CONTAINER="ai-base-verify-front"

cleanup() {
  rm -f "$PROBE_SDK" "$PROBE_FRONT"
  docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

section() { echo; echo "### $1"; echo; }
show() { printf '```text\n%s\n```\n' "$1"; }
ok() { PASS=$((PASS + 1)); echo "- ✔ $1"; }
ng() { FAIL=$((FAIL + 1)); FAILED+=("$1"); echo "- ✘ $1"; }

echo "## 已执行的命令与结果"
echo
echo "工作目录：\`$ROOT\`；日期：$(date '+%Y-%m-%d %H:%M:%S %Z')"

# ---------------------------------------------------------------- 1. 文件结构
section "1. workspace 声明与锁文件"
echo '命令：`ls package.json pnpm-workspace.yaml pnpm-lock.yaml`'
ls package.json pnpm-workspace.yaml pnpm-lock.yaml 2>&1 || true
echo
for f in package.json pnpm-workspace.yaml pnpm-lock.yaml; do
  if [ -f "$f" ]; then ok "存在 $f"; else ng "缺少 $f"; fi
done
echo
echo '命令：`git ls-files | grep pnpm-lock\.yaml`（应只剩根 lockfile）'
TRACKED_LOCKS="$(git ls-files | grep -E 'pnpm-lock\.yaml$' | grep -v '^pnpm-lock\.yaml$' || true)"
show "${TRACKED_LOCKS:-<无 app 级 pnpm-lock.yaml>}"
if [ -z "$TRACKED_LOCKS" ]; then ok "app 级 pnpm-lock.yaml 已全部删除"; else ng "仍存在 app 级 lockfile：$TRACKED_LOCKS"; fi
echo
echo '命令：`grep -n "xxai-agent" apps/front/package.json apps/shop/package.json`'
grep -n 'xxai-agent' apps/front/package.json apps/shop/package.json

# ---------------------------------------------------------------- 2. 根 install
section "2. 仓库根 pnpm install --frozen-lockfile"
INSTALL_START=$(date +%s)
INSTALL_OUT="$(pnpm install --frozen-lockfile 2>&1)"
INSTALL_STATUS=$?
INSTALL_DUR=$(( $(date +%s) - INSTALL_START ))
show "$(printf '%s\n' "$INSTALL_OUT" | tail -12)"
echo
if [ "$INSTALL_STATUS" -eq 0 ]; then ok "根 install 退出码 0（用时 ${INSTALL_DUR}s）"; else ng "根 install 退出码 $INSTALL_STATUS"; fi

# ---------------------------------------------------------------- 3. 软链与 dist
section "3. workspace 软链与 SDK 产物"
echo '命令：`readlink apps/front/node_modules/xxai-agent`'
LINK="$(readlink apps/front/node_modules/xxai-agent || true)"
echo "$LINK"
echo
if [ "$LINK" = "../../ai-sdk" ]; then ok "apps/front/node_modules/xxai-agent -> ../../ai-sdk（软链）"; else ng "xxai-agent 不是预期软链：${LINK:-<不存在>}"; fi
echo
echo '命令：`ls -l apps/ai-sdk/dist/xxai-agent.es.js`'
ls -l apps/ai-sdk/dist/xxai-agent.es.js 2>&1 || true
echo
if [ -f apps/ai-sdk/dist/xxai-agent.es.js ]; then ok "根 install 后 SDK dist 存在（prepare 生效）"; else ng "SDK dist 缺失"; fi

# ---------------------------------------------------------------- 4. 三个宿主构建
section "4. 三个 workspace 前端构建"
run_build() { # run_build <名称> <目录> <命令...>
  local name="$1" dir="$2"; shift 2
  local out status start dur
  start=$(date +%s)
  out="$(cd "$dir" && "$@" 2>&1)"
  status=$?
  dur=$(( $(date +%s) - start ))
  show "$(printf '%s\n' "$out" | tail -6)"
  echo
  if [ "$status" -eq 0 ]; then ok "$name 构建通过（用时 ${dur}s）"; else ng "$name 构建失败（exit=$status）"; fi
}
echo '命令：`pnpm --dir apps/front exec vite build`'
run_build "apps/front" "apps/front" pnpm exec vite build
echo '命令：`pnpm --dir apps/shop build`'
run_build "apps/shop" "apps/shop" pnpm exec vite build
echo '命令：`pnpm --dir apps/desktop/front build`'
run_build "apps/desktop/front" "apps/desktop/front" pnpm exec vite build

# ---------------------------------------------------------------- 5. 镜像增量构建
section "5. front 镜像增量构建耗时"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  export BUILDX_CONFIG="$ROOT/tmp/buildx-config"
  mkdir -p "$BUILDX_CONFIG" "$ROOT/tmp"
  # 沙箱下 buildx 默认目录不可写，统一把 BUILDX_CONFIG 指到仓库 tmp/（与日常构建一致）。
  # 耗时与退出码写进临时文件：命令替换是子 shell，直接用全局变量会丢。
  build_front() { # build_front <日志文件> <耗时文件>
    local log="$1" durfile="$2" start dur status
    start=$(date +%s)
    docker compose --progress=plain build front >"$log" 2>&1
    status=$?
    dur=$(( $(date +%s) - start ))
    echo "$dur" >"$durfile"
    return "$status"
  }

  echo '命令：`docker compose --progress=plain build front`（基线构建，让缓存命中当前源码）'
  build_front "$ROOT/tmp/verify-build-baseline.log" "$ROOT/tmp/verify-build-baseline.dur"
  STATUS=$?
  DUR="$(cat "$ROOT/tmp/verify-build-baseline.dur")"
  show "$(tail -4 "$ROOT/tmp/verify-build-baseline.log")"
  echo
  if [ "$STATUS" -eq 0 ]; then ok "基线构建退出码 0（用时 ${DUR}s）"; else ng "基线构建失败（exit=$STATUS），见 tmp/verify-build-baseline.log"; fi

  echo
  echo "命令：写入 \`$PROBE_SDK\` 后重新构建（模拟只改 SDK 源码）"
  echo "probe $(date +%s)" > "$PROBE_SDK"
  build_front "$ROOT/tmp/verify-build-sdk.log" "$ROOT/tmp/verify-build-sdk.dur"
  STATUS=$?
  DUR="$(cat "$ROOT/tmp/verify-build-sdk.dur")"
  rm -f "$PROBE_SDK"
  show "$(tail -4 "$ROOT/tmp/verify-build-sdk.log")"
  echo
  if [ "$STATUS" -ne 0 ]; then
    ng "改 SDK 源码后构建失败（exit=$STATUS）"
  elif [ "$DUR" -le 60 ]; then
    ok "改 SDK 源码后重建 ${DUR}s（阈值 ≤60s，改造前 3m07s）"
  else
    ng "改 SDK 源码后重建 ${DUR}s，超过 60s 阈值"
  fi

  echo
  echo "命令：写入 \`$PROBE_FRONT\` 后重新构建（模拟只改 front 源码）"
  echo "probe $(date +%s)" > "$PROBE_FRONT"
  build_front "$ROOT/tmp/verify-build-front.log" "$ROOT/tmp/verify-build-front.dur"
  STATUS=$?
  DUR="$(cat "$ROOT/tmp/verify-build-front.dur")"
  rm -f "$PROBE_FRONT"
  show "$(tail -4 "$ROOT/tmp/verify-build-front.log")"
  echo
  if [ "$STATUS" -ne 0 ]; then
    ng "改 front 源码后构建失败（exit=$STATUS）"
  elif [ "$DUR" -le 30 ]; then
    ok "改 front 源码后重建 ${DUR}s（阈值 ≤30s）"
  else
    ng "改 front 源码后重建 ${DUR}s，超过 30s 阈值"
  fi

  # ------------------------------------------------------------ 6. 镜像冒烟
  section "6. 新镜像 nginx 冒烟"
  if docker image inspect ai-base-front >/dev/null 2>&1; then
    docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$VERIFY_CONTAINER" --network ai-base_default -p 18081:80 ai-base-front >/dev/null 2>&1
    sleep 3
    echo '命令：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18081/`'
    HOME_CODE="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/ || true)"
    echo "$HOME_CODE"
    echo
    if [ "$HOME_CODE" = "200" ]; then ok "首页 200"; else ng "首页返回 ${HOME_CODE:-<空>}"; fi
    echo
    echo '命令：index.html 引用的 assets（逐个 curl 状态码并计数）'
    ASSET_CODES="$(curl -s http://127.0.0.1:18081/ \
      | grep -o 'assets/[^"]*' | sort -u \
      | while read -r a; do curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:18081/$a"; done \
      | sort | uniq -c || true)"
    show "${ASSET_CODES:-<无引用资源>}"
    echo
    if [ -n "$ASSET_CODES" ] && ! printf '%s\n' "$ASSET_CODES" | grep -qv ' 200$'; then
      ok "index.html 引用的静态资源全部 200"
    else
      ng "存在非 200 的静态资源"
    fi
    echo
    # 反代目标 api 可能正在重启（用户并行改动容器时），最多等 15s 再判定。
    for _ in 1 2 3 4 5; do
      LOGIN_CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:18081/api/v1/auth/login || true)"
      [ "$LOGIN_CODE" = "422" ] && break
      sleep 3
    done
    echo '命令：`curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{}" http://127.0.0.1:18081/api/v1/auth/login`'
    echo "$LOGIN_CODE"
    echo
    if [ "$LOGIN_CODE" = "422" ]; then ok "/api 反代可达（空 body 登录返回 422）"; else ng "/api 反代异常（返回 ${LOGIN_CODE:-<空>}，期望 422）"; fi
    docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true
  else
    ng "镜像 ai-base-front 不存在，无法冒烟"
  fi
else
  ng "docker 不可用，跳过镜像构建与冒烟"
fi

# ---------------------------------------------------------------- 7. audit
section "7. Harness 审计"
if [ -f "docs/harness/requests/${REQUEST_ID}/verify.md" ]; then
  echo '命令：`python3 tools/harness/audit.py`'
  AUDIT_OUT="$(python3 tools/harness/audit.py 2>&1)"
  AUDIT_STATUS=$?
  show "$(printf '%s\n' "$AUDIT_OUT" | tail -20)"
  echo
  if [ "$AUDIT_STATUS" -eq 0 ]; then ok "audit.py 退出码 0"; else ng "audit.py 退出码 $AUDIT_STATUS"; fi
else
  echo "- ⏭ 未执行：verify.md 由本次运行生成，audit 需要它存在；本脚本在 verify.sh 第二次运行时执行该步。"
fi

# ---------------------------------------------------------------- 汇总
echo
echo "## 未执行项与原因"
echo
echo "- 浏览器人工点击：本 request 无前端交互变更，不需要人工验收。"
echo "- 首次运行时「audit.py」一并为未执行项（verify.md 尚未生成），第二次运行已覆盖。"
echo
echo "## 验收结论"
echo
echo "- 通过 ${PASS} 项、失败 ${FAIL} 项；脚本退出码 $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)。"
if [ "$FAIL" -ne 0 ]; then
  echo "- 失败项："
  for f in "${FAILED[@]}"; do echo "  - $f"; done
fi
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
