#!/usr/bin/env bash
# 前端本地快速迭代：本机 vite build + 官方 nginx 镜像挂载 dist，跳过 front 镜像构建。
#
#   tools/front-local.sh          # 构建并（重）启动 8080 的前端容器
#   tools/front-local.sh build    # 只重新构建 dist（改完代码跑这个，2~3 秒）
#
# 细节见仓库根 docker-compose.front-local.yml 的注释。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

build_frontend() {
  # `pnpm build` 会先跑 tsc -b，而仓库现有 TypeScript 基线错误会让它失败
  # （镜像构建里也是直接 `pnpm exec vite build`），这里保持同样口径。
  #
  # VITE_API_URL 必须与镜像构建的 build arg 一致（/api/v1）：api 层只写相对路径，
  # baseURL 为空时请求会打到 /platforms/... 而不是 /api/v1/platforms/...，会被 nginx
  # 的 SPA fallback 接走，表现为接口全部异常地返回 index.html。
  (cd apps/front && VITE_API_URL="${VITE_API_URL:-/api/v1}" pnpm exec vite build)
}

case "${1:-up}" in
  build)
    build_frontend
    echo "[front-local] dist 已更新，nginx 直接读挂载目录，刷新浏览器即可"
    ;;
  up)
    build_frontend
    # front 仍然 depends_on api，默认 compose 文件里的网络与依赖关系全部保留
    docker compose -f docker-compose.yml -f docker-compose.front-local.yml up -d front
    echo "[front-local] http://localhost:${FRONT_PORT:-8080} 已指向本机 apps/front/dist"
    echo "[front-local] 改完代码只需重跑：tools/front-local.sh build"
    ;;
  *)
    echo "用法: $0 [up|build]" >&2
    exit 2
    ;;
esac
