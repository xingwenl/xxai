#!/usr/bin/env bash
# ai-base 一键部署脚本（CentOS 7 + Docker Compose + 宿主机 nginx）
# 用法：
#   bash deploy/deploy.sh             # 构建启动容器 + 部署 nginx 配置
#   bash deploy/deploy.sh --no-nginx  # 只构建启动容器，不修改宿主机 nginx
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILES=(-f "$REPO_ROOT/docker-compose.yml" -f "$REPO_ROOT/deploy/docker-compose.prod.yml")

SKIP_NGINX=0
[[ "${1:-}" == "--no-nginx" ]] && SKIP_NGINX=1

cd "$REPO_ROOT"

echo "==> 0/5 环境检查"
for cmd in docker curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[错误] 缺少命令 $cmd，请先运行：bash deploy/install-docker.sh"
    exit 1
  fi
done
# 优先使用 Docker Compose v2 插件（Docker 26 自带），其次独立 docker-compose 二进制
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "[错误] 缺少 docker compose，请先运行：bash deploy/install-docker.sh"
  exit 1
fi

echo "==> 1/5 检查 .env 配置"
if [[ ! -f .env ]]; then
  cp deploy/.env.prod.example .env
  echo "[提示] 已生成 .env 模板，请先编辑 .env 填入真实配置后再运行。"
  echo "       必改项：DB_PASSWORD / SKILL_RUNNER_SHARED_SECRET / OPENAI_API_KEY / EMBED_ORIGIN"
  exit 1
fi

# 读取 .env 中指定 key 的值（等号分隔，忽略注释）
get_env() {
  grep -E "^$1=" .env | head -1 | cut -d= -f2-
}
check_secret() {
  local value
  value="$(get_env "$1")"
  if [[ -z "$value" || "$value" == "change-me"* || "$value" == "Dd123456" ]]; then
    echo "[错误] .env 中 $1 未正确配置（当前值：${value:-空}），请修改后重试。"
    exit 1
  fi
}
check_secret DB_PASSWORD
check_secret SKILL_RUNNER_SHARED_SECRET

echo "==> 2/5 确保数据卷存在"
# 根目录 compose 把 postgres 卷声明为 external，首次部署必须先创建
docker volume create backend_postgres_data >/dev/null 2>&1 || true

# 日志目录按服务分开（api / worker / wechat-bot），提前创建避免 Docker 以 root 身份生成目录；
# 应用内 app-<date>.log 由后端自行按天轮转与清理，这里只准备目录。
mkdir -p apps/backend/logs/api apps/backend/logs/worker apps/backend/logs/wechat-bot

echo "==> 3/5 构建镜像"
# skill-runner 为 api 的技能沙箱，必启；wechat-bot-worker 按 WECHAT_BOT_ENABLED 决定
EXTRA_SERVICES="skill-runner"
if [[ "$(get_env WECHAT_BOT_ENABLED)" == "true" ]]; then
  EXTRA_SERVICES="$EXTRA_SERVICES wechat-bot-worker"
fi
"${DC[@]}" "${COMPOSE_FILES[@]}" build api worker front $EXTRA_SERVICES

echo "==> 4/5 启动服务（db redis api worker front $EXTRA_SERVICES）"
"${DC[@]}" "${COMPOSE_FILES[@]}" up -d db redis api worker front $EXTRA_SERVICES

echo "==> 等待后端就绪（健康检查 /api/v1/system/health）"
ready=0
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/api/v1/system/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != 1 ]]; then
  echo "[警告] 后端 120 秒内未就绪，请排查日志："
  echo "       ${DC[*]} ${COMPOSE_FILES[*]} logs --tail=100 api"
else
  echo "后端已就绪。"
fi

echo "==> 5/5 部署宿主机 nginx 配置"
if [[ "$SKIP_NGINX" == 1 ]]; then
  echo "已跳过 nginx（--no-nginx）。"
else
  if ! command -v nginx >/dev/null 2>&1; then
    echo "未检测到 nginx，正在安装（EPEL 源）..."
    yum install -y epel-release nginx
  fi
  cp "$SCRIPT_DIR/nginx/ai-base.conf" /etc/nginx/conf.d/ai-base.conf
  nginx -t
  systemctl enable nginx >/dev/null 2>&1 || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx
  echo "nginx 配置已生效：/etc/nginx/conf.d/ai-base.conf"
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "================ 部署完成 ================"
echo "前端页面 : http://${IP:-服务器IP}/   （经 nginx）"
echo "API 健康 : curl http://127.0.0.1:8000/api/v1/system/health"
echo "日志查看 : ${DC[*]} ${COMPOSE_FILES[*]} logs -f api worker"
echo "文件日志 : apps/backend/logs/{api,worker,wechat-bot}/app-<日期>.log（容器内按服务分开）"
echo "备份数据 : bash deploy/backup.sh（首次建议先做一次）"
echo "=========================================="
echo "下一步（有域名时开启 HTTPS）："
echo "  yum install -y epel-release certbot python2-certbot-nginx"
echo "  certbot --nginx -d 你的域名"
